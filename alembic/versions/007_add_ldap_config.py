"""Add ldap_config table

Revision ID: 007_add_ldap_config
Revises: 006_add_user_restrictions
Create Date: 2026-04-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_add_ldap_config"
down_revision: str | None = "006_add_user_restrictions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ldap_config table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("ldap_config"):
        op.create_table(
            "ldap_config",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("host", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("port", sa.Integer(), nullable=False, server_default="389"),
            sa.Column("use_ssl", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("auth_type", sa.String(length=20), nullable=False, server_default="SIMPLE"),
            sa.Column("bind_dn", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("bind_password", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("base_dn", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        print("Skipping creation of 'ldap_config' because it already exists")


def downgrade() -> None:
    """Drop ldap_config table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("ldap_config"):
        op.drop_table("ldap_config")
    else:
        print("Skipping drop of 'ldap_config' because it does not exist")
