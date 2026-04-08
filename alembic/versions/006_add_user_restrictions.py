"""Add blocked_users and throttled_users tables

Revision ID: 006_add_user_restrictions
Revises: 005_add_backup_config
Create Date: 2026-04-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_user_restrictions"
down_revision: str | None = "005_add_backup_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create blocked_users and throttled_users tables."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("blocked_users"):
        op.create_table(
            "blocked_users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=False),
            sa.Column("ip", sa.String(length=45), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_blocked_users_username", "blocked_users", ["username"])
        op.create_index("ix_blocked_users_ip", "blocked_users", ["ip"])
    else:
        print("Skipping creation of 'blocked_users' because it already exists")

    if not inspector.has_table("throttled_users"):
        op.create_table(
            "throttled_users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=False),
            sa.Column("ip", sa.String(length=45), nullable=False),
            sa.Column("pool_number", sa.Integer(), nullable=False),
            sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_throttled_users_username", "throttled_users", ["username"])
        op.create_index("ix_throttled_users_ip", "throttled_users", ["ip"])
    else:
        print("Skipping creation of 'throttled_users' because it already exists")


def downgrade() -> None:
    """Drop blocked_users and throttled_users tables."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("throttled_users"):
        op.drop_index("ix_throttled_users_ip", table_name="throttled_users")
        op.drop_index("ix_throttled_users_username", table_name="throttled_users")
        op.drop_table("throttled_users")
    else:
        print("Skipping drop of 'throttled_users' because it does not exist")

    if inspector.has_table("blocked_users"):
        op.drop_index("ix_blocked_users_ip", table_name="blocked_users")
        op.drop_index("ix_blocked_users_username", table_name="blocked_users")
        op.drop_table("blocked_users")
    else:
        print("Skipping drop of 'blocked_users' because it does not exist")
