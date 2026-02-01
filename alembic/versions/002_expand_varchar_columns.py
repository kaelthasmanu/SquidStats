"""Expand VARCHAR columns from 50 to 255 characters

This migration addresses the column length expansion that was previously
handled in the manual migrate_database() function. It expands VARCHAR
columns that were too short to accommodate longer values.

Tables affected:
- denied_logs: username, ip, method, status columns
- system_metrics: cpu_usage column

Note: For SQLite, this uses batch operations due to limited ALTER TABLE support.

Revision ID: 002_expand_varchar_columns
Revises: 001_initial_schema
Create Date: 2026-02-01 10:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_expand_varchar_columns"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def get_db_type():
    """Get the database type from environment."""
    import os

    return os.getenv("DATABASE_TYPE", "SQLITE").upper()


def upgrade() -> None:
    """Expand VARCHAR columns to 255 characters."""

    db_type = get_db_type()
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)

    # Check if tables exist before attempting migration
    tables_exist = {
        "denied_logs": inspector.has_table("denied_logs"),
        "system_metrics": inspector.has_table("system_metrics"),
    }

    if db_type == "SQLITE":
        # SQLite requires batch operations for ALTER TABLE
        if tables_exist["denied_logs"]:
            with op.batch_alter_table("denied_logs", schema=None) as batch_op:
                batch_op.alter_column(
                    "username",
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=255),
                    existing_nullable=False,
                )
                batch_op.alter_column(
                    "ip",
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=255),
                    existing_nullable=False,
                )
                batch_op.alter_column(
                    "method",
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=255),
                    existing_nullable=False,
                )
                batch_op.alter_column(
                    "status",
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=255),
                    existing_nullable=False,
                )

        if tables_exist["system_metrics"]:
            with op.batch_alter_table("system_metrics", schema=None) as batch_op:
                batch_op.alter_column(
                    "cpu_usage",
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=255),
                    existing_nullable=False,
                )

    elif db_type in ("MYSQL", "MARIADB"):
        # MySQL/MariaDB use MODIFY COLUMN
        if tables_exist["denied_logs"]:
            op.alter_column(
                "denied_logs",
                "username",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
            )
            op.alter_column(
                "denied_logs",
                "ip",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
            )
            op.alter_column(
                "denied_logs",
                "method",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
            )
            op.alter_column(
                "denied_logs",
                "status",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
            )

        if tables_exist["system_metrics"]:
            op.alter_column(
                "system_metrics",
                "cpu_usage",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
            )

    elif db_type in ("POSTGRESQL", "POSTGRES"):
        # PostgreSQL uses ALTER COLUMN TYPE
        if tables_exist["denied_logs"]:
            op.alter_column(
                "denied_logs",
                "username",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
                postgresql_using="username::character varying(255)",
            )
            op.alter_column(
                "denied_logs",
                "ip",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
                postgresql_using="ip::character varying(255)",
            )
            op.alter_column(
                "denied_logs",
                "method",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
                postgresql_using="method::character varying(255)",
            )
            op.alter_column(
                "denied_logs",
                "status",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
                postgresql_using="status::character varying(255)",
            )

        if tables_exist["system_metrics"]:
            op.alter_column(
                "system_metrics",
                "cpu_usage",
                existing_type=sa.String(length=50),
                type_=sa.String(length=255),
                existing_nullable=False,
                postgresql_using="cpu_usage::character varying(255)",
            )


def downgrade() -> None:
    """Revert VARCHAR columns back to 50 characters.

    WARNING: This may cause data loss if any values exceed 50 characters!
    """

    db_type = get_db_type()
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)

    # Check if tables exist before attempting migration
    tables_exist = {
        "denied_logs": inspector.has_table("denied_logs"),
        "system_metrics": inspector.has_table("system_metrics"),
    }

    if db_type == "SQLITE":
        # SQLite requires batch operations for ALTER TABLE
        if tables_exist["denied_logs"]:
            with op.batch_alter_table("denied_logs", schema=None) as batch_op:
                batch_op.alter_column(
                    "username",
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=50),
                    existing_nullable=False,
                )
                batch_op.alter_column(
                    "ip",
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=50),
                    existing_nullable=False,
                )
                batch_op.alter_column(
                    "method",
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=50),
                    existing_nullable=False,
                )
                batch_op.alter_column(
                    "status",
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=50),
                    existing_nullable=False,
                )

        if tables_exist["system_metrics"]:
            with op.batch_alter_table("system_metrics", schema=None) as batch_op:
                batch_op.alter_column(
                    "cpu_usage",
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=50),
                    existing_nullable=False,
                )

    elif db_type in ("MYSQL", "MARIADB"):
        # MySQL/MariaDB use MODIFY COLUMN
        if tables_exist["denied_logs"]:
            op.alter_column(
                "denied_logs",
                "username",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
            )
            op.alter_column(
                "denied_logs",
                "ip",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
            )
            op.alter_column(
                "denied_logs",
                "method",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
            )
            op.alter_column(
                "denied_logs",
                "status",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
            )

        if tables_exist["system_metrics"]:
            op.alter_column(
                "system_metrics",
                "cpu_usage",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
            )

    elif db_type in ("POSTGRESQL", "POSTGRES"):
        # PostgreSQL uses ALTER COLUMN TYPE
        if tables_exist["denied_logs"]:
            op.alter_column(
                "denied_logs",
                "username",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
                postgresql_using="username::character varying(50)",
            )
            op.alter_column(
                "denied_logs",
                "ip",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
                postgresql_using="ip::character varying(50)",
            )
            op.alter_column(
                "denied_logs",
                "method",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
                postgresql_using="method::character varying(50)",
            )
            op.alter_column(
                "denied_logs",
                "status",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
                postgresql_using="status::character varying(50)",
            )

        if tables_exist["system_metrics"]:
            op.alter_column(
                "system_metrics",
                "cpu_usage",
                existing_type=sa.String(length=255),
                type_=sa.String(length=50),
                existing_nullable=False,
                postgresql_using="cpu_usage::character varying(50)",
            )
