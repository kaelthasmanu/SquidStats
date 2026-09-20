"""Add admin-managed LDAP groups and members.

Revision ID: 013_add_ldap_groups
Revises: 012_add_denied_log_created_at_index
Create Date: 2026-09-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "013_add_ldap_groups"
down_revision: str | None = "012_add_denied_log_created_at_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())

    if not inspector.has_table("ldap_groups"):
        op.create_table(
            "ldap_groups",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=50), nullable=False, server_default="custom"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index("ix_ldap_groups_name", "ldap_groups", ["name"], unique=False)

    if not inspector.has_table("ldap_group_members"):
        op.create_table(
            "ldap_group_members",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["ldap_groups.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("group_id", "username", name="uq_ldap_group_member"),
        )
        op.create_index("ix_ldap_group_members_group_id", "ldap_group_members", ["group_id"], unique=False)
        op.create_index("ix_ldap_group_members_username", "ldap_group_members", ["username"], unique=False)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("ldap_group_members"):
        op.drop_index("ix_ldap_group_members_username", table_name="ldap_group_members")
        op.drop_index("ix_ldap_group_members_group_id", table_name="ldap_group_members")
        op.drop_table("ldap_group_members")
    if inspector.has_table("ldap_groups"):
        op.drop_index("ix_ldap_groups_name", table_name="ldap_groups")
        op.drop_table("ldap_groups")