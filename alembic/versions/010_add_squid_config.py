"""Add squid_config table

Revision ID: 010_add_squid_config
Revises: 009_add_telegram_config
Create Date: 2026-06-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_add_squid_config"
down_revision: str | None = "009_add_telegram_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create squid_config table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("squid_config"):
        op.create_table(
            "squid_config",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "squid_host",
                sa.String(length=255),
                nullable=False,
                server_default="127.0.0.1",
            ),
            sa.Column(
                "squid_port", sa.Integer(), nullable=False, server_default="3128"
            ),
            sa.Column(
                "log_format",
                sa.String(length=50),
                nullable=False,
                server_default="DEFAULT",
            ),
            sa.Column(
                "squid_log",
                sa.String(length=512),
                nullable=False,
                server_default="/var/log/squid/access.log",
            ),
            sa.Column(
                "squid_cache_log",
                sa.String(length=512),
                nullable=False,
                server_default="/var/log/squid/cache.log",
            ),
            sa.Column(
                "squid_config_path",
                sa.String(length=512),
                nullable=False,
                server_default="/etc/squid/squid.conf",
            ),
            sa.Column(
                "acl_files_dir",
                sa.String(length=512),
                nullable=False,
                server_default="",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        print("Skipping creation of 'squid_config' because it already exists")


def downgrade() -> None:
    """Drop squid_config table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("squid_config"):
        op.drop_table("squid_config")
    else:
        print("Skipping drop of 'squid_config' because it does not exist")
