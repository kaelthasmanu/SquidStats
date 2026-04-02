"""Add backup_config table

Revision ID: 005_add_backup_config
Revises: 004_add_quota_tables
Create Date: 2026-04-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_add_backup_config"
down_revision: str | None = "004_add_quota_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create backup_config table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("backup_config"):
        op.create_table(
            "backup_config",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "db_type",
                sa.String(length=50),
                nullable=False,
                server_default="sqlite",
            ),
            sa.Column(
                "frequency",
                sa.String(length=50),
                nullable=False,
                server_default="daily_weekly",
            ),
            sa.Column(
                "backup_dir",
                sa.String(length=512),
                nullable=False,
                server_default="/opt/SquidStats/backups",
            ),
            sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        print("Skipping creation of 'backup_config' because it already exists")


def downgrade() -> None:
    """Drop backup_config table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("backup_config"):
        op.drop_table("backup_config")
    else:
        print("Skipping drop of 'backup_config' because it does not exist")
