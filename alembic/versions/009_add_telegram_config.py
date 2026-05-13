"""Add telegram_config table

Revision ID: 009_add_telegram_config
Revises: 008_add_ldap_encryption_key
Create Date: 2026-05-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_add_telegram_config"
down_revision: str | None = "008_add_ldap_encryption_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create telegram_config table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("telegram_config"):
        op.create_table(
            "telegram_config",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "api_id", sa.String(length=50), nullable=False, server_default=""
            ),
            sa.Column(
                "api_hash", sa.String(length=512), nullable=False, server_default=""
            ),
            sa.Column(
                "bot_token", sa.String(length=512), nullable=False, server_default=""
            ),
            sa.Column("phone", sa.String(length=50), nullable=False, server_default=""),
            sa.Column(
                "session_name",
                sa.String(length=100),
                nullable=False,
                server_default="squidstats_bot",
            ),
            sa.Column("recipients", sa.Text(), nullable=False, server_default=""),
            sa.Column("encryption_key", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        print("Skipping creation of 'telegram_config' because it already exists")


def downgrade() -> None:
    """Drop telegram_config table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("telegram_config"):
        op.drop_table("telegram_config")
    else:
        print("Skipping drop of 'telegram_config' because it does not exist")
