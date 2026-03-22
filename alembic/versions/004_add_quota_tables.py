"""Add quota management tables

Revision ID: 004_add_quota_tables
Revises: 003_add_blacklist_domains
Create Date: 2026-03-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_add_quota_tables"
down_revision: str | None = "003_add_blacklist_domains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create quota schema tables."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("quota_users"):
        op.create_table(
            "quota_users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=False),
            sa.Column("quota_mb", sa.Integer(), nullable=False, default=0),
            sa.Column("used_mb", sa.BigInteger(), nullable=False, default=0),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("username"),
        )
        op.create_index("ix_quota_users_username", "quota_users", ["username"])
    else:
        print("Skipping creation of 'quota_users' because it already exists")

    if not inspector.has_table("quota_groups"):
        op.create_table(
            "quota_groups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("group_name", sa.String(length=255), nullable=False),
            sa.Column("quota_mb", sa.Integer(), nullable=False, default=0),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("group_name"),
        )
        op.create_index("ix_quota_groups_group_name", "quota_groups", ["group_name"])
    else:
        print("Skipping creation of 'quota_groups' because it already exists")

    if not inspector.has_table("quota_rules"):
        op.create_table(
            "quota_rules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("policy", sa.String(length=50), nullable=False),
            sa.Column("active", sa.Integer(), nullable=True, default=1),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_quota_rules_active", "quota_rules", ["active"])
    else:
        print("Skipping creation of 'quota_rules' because it already exists")

    if not inspector.has_table("quota_events"):
        op.create_table(
            "quota_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("group_name", sa.String(length=255), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_quota_events_created_at", "quota_events", ["created_at"])
    else:
        print("Skipping creation of 'quota_events' because it already exists")


def downgrade() -> None:
    """Drop quota schema tables."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("quota_events"):
        try:
            op.drop_index("ix_quota_events_created_at", table_name="quota_events")
        except Exception:
            pass
        op.drop_table("quota_events")

    if inspector.has_table("quota_rules"):
        try:
            op.drop_index("ix_quota_rules_active", table_name="quota_rules")
        except Exception:
            pass
        op.drop_table("quota_rules")

    if inspector.has_table("quota_groups"):
        try:
            op.drop_index("ix_quota_groups_group_name", table_name="quota_groups")
        except Exception:
            pass
        op.drop_table("quota_groups")

    if inspector.has_table("quota_users"):
        try:
            op.drop_index("ix_quota_users_username", table_name="quota_users")
        except Exception:
            pass
        op.drop_table("quota_users")
