"""Remove obsolete log_format from squid_config.

Revision ID: 011_remove_log_format
Revises: 010_add_squid_config
Create Date: 2026-08-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_remove_log_format"
down_revision: str | None = "010_add_squid_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_log_format_column() -> bool:
    inspector = inspect(op.get_bind())
    return inspector.has_table("squid_config") and any(
        column["name"] == "log_format"
        for column in inspector.get_columns("squid_config")
    )


def upgrade() -> None:
    """Drop only the obsolete configuration column."""
    if not _has_log_format_column():
        return

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("squid_config", recreate="always") as batch_op:
            batch_op.drop_column("log_format")
    else:
        op.drop_column("squid_config", "log_format")


def downgrade() -> None:
    """Restore the legacy column for explicit migration rollback."""
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("squid_config", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "log_format",
                    sa.String(length=50),
                    nullable=False,
                    server_default="DEFAULT",
                )
            )
    else:
        op.add_column(
            "squid_config",
            sa.Column(
                "log_format",
                sa.String(length=50),
                nullable=False,
                server_default="DEFAULT",
            ),
        )
