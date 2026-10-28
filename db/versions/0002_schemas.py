"""Create the layer schemas.

WHY: Each layer of the ELT flow (raw -> staging -> core -> marts) plus the operational
app data and the audit log lives in its own schema, so permissions can be granted per
layer (see 0003) instead of per table.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE SCHEMA raw;
        COMMENT ON SCHEMA raw     IS 'Provider JSON exactly as received + load metadata. Never modified.';

        CREATE SCHEMA staging;
        COMMENT ON SCHEMA staging IS 'One typed table per provider entity. Rename, cast, deduplicate.';

        CREATE SCHEMA core;
        COMMENT ON SCHEMA core    IS 'Canonical, provider-independent model. Single source of truth.';

        CREATE SCHEMA marts;
        COMMENT ON SCHEMA marts   IS 'Star schema and aggregates for the app and ML. Read-optimised.';

        CREATE SCHEMA app;
        COMMENT ON SCHEMA app     IS 'Operational multi-tenant data (shortlists, reports, contracts). RLS per club.';

        CREATE SCHEMA audit;
        COMMENT ON SCHEMA audit   IS 'Append-only change log written by triggers.';
    """)


def downgrade() -> None:
    # CASCADE: a downgrade past this point intentionally throws away every layer's tables.
    op.execute("""
        DROP SCHEMA IF EXISTS audit   CASCADE;
        DROP SCHEMA IF EXISTS app     CASCADE;
        DROP SCHEMA IF EXISTS marts   CASCADE;
        DROP SCHEMA IF EXISTS core    CASCADE;
        DROP SCHEMA IF EXISTS staging CASCADE;
        DROP SCHEMA IF EXISTS raw     CASCADE;
    """)
