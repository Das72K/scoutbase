"""Install PostgreSQL extensions.

WHY: Later layers depend on these: pgvector for player style embeddings, pgcrypto for
encrypted wages and UUIDs, pg_trgm + unaccent for fuzzy player-name matching in the
cross-provider crosswalks (e.g. "Răzvan Marin" vs "Razvan Marin" vs "R. Marin").

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
        CREATE EXTENSION IF NOT EXISTS unaccent;
    """)


def downgrade() -> None:
    op.execute("""
        DROP EXTENSION IF EXISTS unaccent;
        DROP EXTENSION IF EXISTS pg_trgm;
        DROP EXTENSION IF EXISTS pgcrypto;
        DROP EXTENSION IF EXISTS vector;
    """)
