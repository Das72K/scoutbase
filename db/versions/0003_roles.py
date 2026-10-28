"""Create group roles, login users and least-privilege grants.

WHY: Each component gets only the access it needs, enforced by the database rather than by
application code: the pipeline builds the warehouse, the API reads it and owns app data but
can only append to the audit log, and analysts get read-only access to marts.

Design:
  * NOLOGIN group roles hold the privileges:  scoutbase_pipeline, scoutbase_app, scoutbase_readonly
  * LOGIN users are members of exactly one group: <group>_user, password from the environment
  * scoutbase_pipeline_user runs as its group (ALTER ROLE ... SET role), so tables built by
    dbt are owned by scoutbase_pipeline and the default privileges below apply to them.
  * Tables in app/audit are created by migrations, i.e. by the migration owner (current_user).
  * Roles are cluster-wide, but grants live in each database. Several SCOUTBASE databases can
    share one cluster (the working database and the test suite's scoutbase_test), so upgrade
    creates the roles only if they are missing, and downgrade drops them only once no other
    database depends on them.

Revision ID: 0003
Revises: 0002
"""

import os

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

GROUPS = ("scoutbase_pipeline", "scoutbase_app", "scoutbase_readonly")


def _password(group: str) -> str:
    env_var = f"{group.upper()}_PASSWORD"
    value = os.environ.get(env_var)
    if not value:
        raise RuntimeError(f"{env_var} must be set (see .env.example)")
    return "'" + value.replace("'", "''") + "'"  # SQL string literal


def upgrade() -> None:
    # --- 1. Lock down the public schema --------------------------------------------------
    op.execute("""
        REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    """)

    # --- 2. Group roles (privileges) and login users (members) ---------------------------
    # An existing role was created by another SCOUTBASE database on this cluster: reuse it.
    for group in GROUPS:
        op.execute(f"""
            DO $roles$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{group}') THEN
                    CREATE ROLE {group} NOLOGIN;
                END IF;
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{group}_user') THEN
                    CREATE ROLE {group}_user LOGIN PASSWORD {_password(group)} IN ROLE {group};
                END IF;
            END $roles$;
        """)
    op.execute("""
        ALTER ROLE scoutbase_pipeline_user SET role = 'scoutbase_pipeline';
    """)

    # --- 3. scoutbase_pipeline: builds raw -> staging -> core -> marts --------------------
    op.execute("""
        GRANT USAGE, CREATE ON SCHEMA raw, staging, core, marts TO scoutbase_pipeline;
    """)

    # --- 4. scoutbase_app: reads core + marts, read/write app, append-only audit ---------
    op.execute("""
        GRANT USAGE ON SCHEMA core, marts, app, audit TO scoutbase_app;

        -- core/marts tables are built by the pipeline (dbt) ...
        ALTER DEFAULT PRIVILEGES FOR ROLE scoutbase_pipeline IN SCHEMA core, marts
            GRANT SELECT ON TABLES TO scoutbase_app;
        -- ... or occasionally by a migration (e.g. a seeded dim_date).
        ALTER DEFAULT PRIVILEGES IN SCHEMA core, marts
            GRANT SELECT ON TABLES TO scoutbase_app;

        ALTER DEFAULT PRIVILEGES IN SCHEMA app
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO scoutbase_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA app
            GRANT USAGE, SELECT ON SEQUENCES TO scoutbase_app;

        -- INSERT only: no SELECT, UPDATE, DELETE or TRUNCATE on the audit log.
        ALTER DEFAULT PRIVILEGES IN SCHEMA audit
            GRANT INSERT ON TABLES TO scoutbase_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA audit
            GRANT USAGE ON SEQUENCES TO scoutbase_app;
    """)

    # --- 5. scoutbase_readonly: SELECT on marts only --------------------------------------
    op.execute("""
        GRANT USAGE ON SCHEMA marts TO scoutbase_readonly;

        ALTER DEFAULT PRIVILEGES FOR ROLE scoutbase_pipeline IN SCHEMA marts
            GRANT SELECT ON TABLES TO scoutbase_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA marts
            GRANT SELECT ON TABLES TO scoutbase_readonly;
    """)


def downgrade() -> None:
    # DROP OWNED BY revokes every grant and default privilege that mentions the roles in this
    # database and drops objects they own (e.g. dbt tables). It never touches other databases.
    names = [name for g in reversed(GROUPS) for name in (f"{g}_user", g)]
    roles = ", ".join(names)
    op.execute(f"DROP OWNED BY {roles};")

    # pg_shdepend records, per database, every object and privilege that refers to a role. If
    # another database still has any, the roles stay: dropping them would fail (or break it).
    op.execute(f"""
        DO $roles$ BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_shdepend d
                  JOIN pg_roles r ON r.oid = d.refobjid AND d.refclassid = 'pg_authid'::regclass
                 WHERE r.rolname = ANY (ARRAY[{", ".join(f"'{n}'" for n in names)}])
                   AND d.dbid <> (SELECT oid FROM pg_database WHERE datname = current_database())
            ) THEN
                DROP ROLE {roles};
            ELSE
                RAISE NOTICE 'scoutbase roles kept: another database on this cluster still uses them';
            END IF;
        END $roles$;
    """)

    # Not re-granted on purpose: since PostgreSQL 15, PUBLIC has no CREATE on schema public
    # by default, so leaving it revoked *is* the pre-0003 state on PG16.
