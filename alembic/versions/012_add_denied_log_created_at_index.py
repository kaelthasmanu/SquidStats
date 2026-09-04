"""Index denied-log timestamps used by daily reports.

Revision ID: 012_add_denied_log_created_at_index
Revises: 011_remove_log_format
Create Date: 2026-09-03 00:00:00.000000
"""

from collections.abc import Sequence

from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012_add_denied_log_created_at_index"
down_revision: str | None = "011_remove_log_format"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_denied_logs_created_at"
TABLE_NAME = "denied_logs"


def _table_exists() -> bool:
    inspector = inspect(op.get_bind())
    return inspector.has_table(TABLE_NAME)


def _index_exists() -> bool:
    if not _table_exists():
        return False
    inspector = inspect(op.get_bind())
    return any(
        index["name"] == INDEX_NAME for index in inspector.get_indexes(TABLE_NAME)
    )


def upgrade() -> None:
    """Create the index when upgrading an existing installation."""
    if _table_exists() and not _index_exists():
        op.create_index(INDEX_NAME, TABLE_NAME, ["created_at"])


def downgrade() -> None:
    """Remove the report-specific timestamp index."""
    if _index_exists():
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
