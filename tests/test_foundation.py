"""Foundation tests: extensions, schemas, role permissions, migration round-trip.

Permission tests attempt the forbidden action and expect PostgreSQL to refuse it.
Each one is paired with the allowed action on the same table, so a test cannot pass
just because the table or schema is missing.
"""

import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.errors import InsufficientPrivilege

ROOT = Path(__file__).resolve().parents[1]

EXTENSIONS = {"vector", "pgcrypto", "pg_trgm", "unaccent"}
SCHEMAS = {"raw", "staging", "core", "marts", "app", "audit"}


def pipeline_table(login_as, table_name, schema: str) -> str:
    """Create a table the way dbt will: as scoutbase_pipeline_user."""
    name = table_name(schema)
    pipeline = login_as("scoutbase_pipeline")
    pipeline.execute(f"CREATE TABLE {name} (id int)")
    pipeline.execute(f"INSERT INTO {name} VALUES (1)")
    return name


def owner_table(owner, table_name, schema: str) -> str:
    """Create a table the way a migration will: as the migration owner."""
    name = table_name(schema)
    owner.execute(f"CREATE TABLE {name} (id bigint GENERATED ALWAYS AS IDENTITY, note text)")
    owner.execute(f"INSERT INTO {name} (note) VALUES ('seed')")
    return name


# --- structure -----------------------------------------------------------------------------


def test_extensions_installed(owner):
    rows = owner.execute("SELECT extname FROM pg_extension").fetchall()
    assert EXTENSIONS <= {r[0] for r in rows}


def test_extensions_work(owner):
    assert owner.execute("SELECT '[1,2]'::vector <-> '[1,3]'::vector").fetchone()[0] == 1.0
    assert owner.execute("SELECT unaccent('Răzvan')").fetchone()[0] == "Razvan"
    assert owner.execute("SELECT similarity('Marin', 'Marinn') > 0.5").fetchone()[0]
    assert owner.execute("SELECT length(gen_random_bytes(16))").fetchone()[0] == 16


def test_schemas_exist(owner):
    rows = owner.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
    assert SCHEMAS <= {r[0] for r in rows}


def test_public_schema_not_writable(login_as):
    with pytest.raises(InsufficientPrivilege):
        login_as("scoutbase_app").execute("CREATE TABLE public.sneaky (id int)")


# --- scoutbase_readonly --------------------------------------------------------------------


def test_readonly_can_read_marts(login_as, table_name):
    name = pipeline_table(login_as, table_name, "marts")
    assert login_as("scoutbase_readonly").execute(f"SELECT id FROM {name}").fetchone() == (1,)


def test_readonly_cannot_create_table_in_marts(login_as, table_name):
    with pytest.raises(InsufficientPrivilege):
        login_as("scoutbase_readonly").execute(f"CREATE TABLE {table_name('marts')} (id int)")


def test_readonly_cannot_read_app(owner, login_as, table_name):
    name = owner_table(owner, table_name, "app")
    with pytest.raises(InsufficientPrivilege):
        login_as("scoutbase_readonly").execute(f"SELECT * FROM {name}")


# --- scoutbase_app -------------------------------------------------------------------------


def test_app_can_read_marts_and_core(login_as, table_name):
    app = login_as("scoutbase_app")
    for schema in ("marts", "core"):
        name = pipeline_table(login_as, table_name, schema)
        assert app.execute(f"SELECT id FROM {name}").fetchone() == (1,)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO {t} VALUES (2)",
        "UPDATE {t} SET id = 3",
        "DELETE FROM {t}",
        "TRUNCATE {t}",
        "CREATE TABLE marts.app_was_here (id int)",
    ],
)
def test_app_cannot_write_marts(login_as, table_name, statement):
    name = pipeline_table(login_as, table_name, "marts")
    with pytest.raises(InsufficientPrivilege):
        login_as("scoutbase_app").execute(statement.format(t=name))


def test_app_can_read_and_write_app(owner, login_as, table_name):
    name = owner_table(owner, table_name, "app")
    app = login_as("scoutbase_app")
    app.execute(f"INSERT INTO {name} (note) VALUES ('shortlisted')")
    app.execute(f"UPDATE {name} SET note = 'signed' WHERE note = 'shortlisted'")
    app.execute(f"DELETE FROM {name} WHERE note = 'seed'")
    assert app.execute(f"SELECT note FROM {name}").fetchall() == [("signed",)]


def test_app_can_insert_audit(owner, login_as, table_name):
    name = owner_table(owner, table_name, "audit")
    login_as("scoutbase_app").execute(f"INSERT INTO {name} (note) VALUES ('changed')")
    assert owner.execute(f"SELECT count(*) FROM {name}").fetchone()[0] == 2


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE {t} SET note = 'tampered'",
        "DELETE FROM {t}",
        "TRUNCATE {t}",
    ],
)
def test_app_cannot_modify_audit(owner, login_as, table_name, statement):
    name = owner_table(owner, table_name, "audit")
    with pytest.raises(InsufficientPrivilege):
        login_as("scoutbase_app").execute(statement.format(t=name))
    assert owner.execute(f"SELECT note FROM {name}").fetchall() == [("seed",)]


# --- migrations ----------------------------------------------------------------------------


def role_dependencies(conn, *, this_db: bool) -> int:
    """pg_shdepend rows (objects, grants, default privileges) referring to scoutbase roles."""
    op = "=" if this_db else "<>"
    return conn.execute(f"""
        SELECT count(*) FROM pg_shdepend d
          JOIN pg_roles r ON r.oid = d.refobjid AND d.refclassid = 'pg_authid'::regclass
         WHERE r.rolname LIKE 'scoutbase\\_%'
           AND d.dbid {op} (SELECT oid FROM pg_database WHERE datname = current_database())
    """).fetchone()[0]


def test_downgrade_to_base_then_upgrade_to_head(owner):
    # The round-trip drops everything: only ever run it on the throwaway test database.
    current_db = owner.execute("SELECT current_database()").fetchone()[0]
    assert current_db == os.environ["POSTGRES_DB"] and current_db.endswith("_test")
    roles_used_elsewhere = role_dependencies(owner, this_db=False) > 0
    cfg = Config(str(ROOT / "db" / "alembic.ini"))

    command.downgrade(cfg, "base")
    assert owner.execute("SELECT to_regnamespace('marts')").fetchone()[0] is None
    assert owner.execute(
        "SELECT count(*) FROM pg_extension WHERE extname = ANY(%s)", [list(EXTENSIONS)]
    ).fetchone()[0] == 0
    # No grant, default privilege or object in this database refers to the roles any more ...
    assert role_dependencies(owner, this_db=True) == 0
    # ... and the cluster-wide roles are dropped unless another database (the working one) uses them.
    remaining = owner.execute(
        "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'scoutbase\\_%'"
    ).fetchone()[0]
    assert remaining == (6 if roles_used_elsewhere else 0)

    command.upgrade(cfg, "head")
    rows = owner.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
    assert SCHEMAS <= {r[0] for r in rows}
