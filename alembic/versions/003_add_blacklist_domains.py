"""Add blacklist_domains table

Revision ID: 003_add_blacklist_domains
Revises: 002_expand_varchar_columns
Create Date: 2026-02-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_add_blacklist_domains"
down_revision: str | None = "002_expand_varchar_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create blacklist_domains table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("blacklist_domains"):
        op.create_table(
            "blacklist_domains",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=True),
            sa.Column("source_url", sa.String(length=512), nullable=True),
            sa.Column("added_by", sa.String(length=100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("active", sa.Integer(), nullable=True, default=1),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("domain"),
        )

        # Index on domain for fast lookups
        op.create_index("ix_blacklist_domains_domain", "blacklist_domains", ["domain"])
    else:
        # Table already exists; skip creation to allow idempotent upgrades
        print("Skipping creation of 'blacklist_domains' because it already exists")


def downgrade() -> None:
    """Drop blacklist_domains table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    if inspector.has_table("blacklist_domains"):
        # Drop index first if exists
        op.drop_index("ix_blacklist_domains_domain", table_name="blacklist_domains", if_exists=True)
        op.drop_table("blacklist_domains")
    else:
        print("'blacklist_domains' does not exist, skipping downgrade for this table")
