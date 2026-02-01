"""Initial schema - create all base tables

This migration creates the foundational schema for SquidStats including:
- log_metadata: tracks log file parsing position
- denied_logs: stores denied requests
- system_metrics: stores system resource usage
- notifications: stores application notifications
- admin_users: stores administrator credentials

Note: Dynamic tables (user_YYYYMMDD, log_YYYYMMDD) are created
programmatically and not managed by migrations.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-02-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create initial schema tables."""

    # Create log_metadata table
    op.create_table(
        "log_metadata",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_position", sa.BigInteger(), nullable=True, default=0),
        sa.Column("last_inode", sa.BigInteger(), nullable=True, default=0),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create denied_logs table
    op.create_table(
        "denied_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("ip", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=255), nullable=False),
        sa.Column("response", sa.Integer(), nullable=True),
        sa.Column("data_transmitted", sa.BigInteger(), nullable=True, default=0),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create system_metrics table
    op.create_table(
        "system_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("cpu_usage", sa.String(length=255), nullable=False),
        sa.Column("ram_usage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("swap_usage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("net_sent_bytes_sec", sa.BigInteger(), nullable=False),
        sa.Column("net_recv_bytes_sec", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create notifications table
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("icon", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("read", sa.Integer(), nullable=True, default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True, default=1),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for notifications
    op.create_index("ix_notifications_message_hash", "notifications", ["message_hash"])
    op.create_index("ix_notifications_source", "notifications", ["source"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    # Create admin_users table
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, default="admin"),
        sa.Column("is_active", sa.Integer(), nullable=True, default=1),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    # Create index for admin_users
    op.create_index("ix_admin_users_username", "admin_users", ["username"])


def downgrade() -> None:
    """Drop all tables created in upgrade."""

    # Drop indexes first
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_source", table_name="notifications")
    op.drop_index("ix_notifications_message_hash", table_name="notifications")

    # Drop tables
    op.drop_table("admin_users")
    op.drop_table("notifications")
    op.drop_table("system_metrics")
    op.drop_table("denied_logs")
    op.drop_table("log_metadata")
