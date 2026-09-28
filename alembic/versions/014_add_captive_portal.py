"""Add captive portal configuration and session tables.

Revision ID: 014_add_captive_portal
Revises: 013_add_ldap_groups
Create Date: 2026-09-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "014_add_captive_portal"
down_revision: str | None = "013_add_ldap_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())

    if not inspector.has_table("captive_portal_config"):
        op.create_table(
            "captive_portal_config",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "portal_title",
                sa.String(length=255),
                nullable=False,
                server_default="SquidStats Portal",
            ),
            sa.Column(
                "portal_public_url",
                sa.String(length=512),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "session_ttl_minutes",
                sa.Integer(),
                nullable=False,
                server_default="480",
            ),
            sa.Column(
                "acl_ttl_seconds", sa.Integer(), nullable=False, server_default="60"
            ),
            sa.Column(
                "acl_negative_ttl_seconds",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if not inspector.has_table("captive_portal_sessions"):
        op.create_table(
            "captive_portal_sessions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("ip", sa.String(length=45), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=False),
            sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("ip"),
        )
        op.create_index(
            "ix_captive_portal_sessions_ip",
            "captive_portal_sessions",
            ["ip"],
            unique=False,
        )
        op.create_index(
            "ix_captive_portal_sessions_username",
            "captive_portal_sessions",
            ["username"],
            unique=False,
        )
        op.create_index(
            "ix_captive_portal_sessions_expires_at",
            "captive_portal_sessions",
            ["expires_at"],
            unique=False,
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())

    if inspector.has_table("captive_portal_sessions"):
        op.drop_table("captive_portal_sessions")

    if inspector.has_table("captive_portal_config"):
        op.drop_table("captive_portal_config")
