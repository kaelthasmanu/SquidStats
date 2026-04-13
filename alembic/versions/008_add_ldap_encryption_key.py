"""Add encryption key column to ldap_config

Revision ID: 008_add_ldap_encryption_key
Revises: 007_add_ldap_config
Create Date: 2026-04-12 00:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_add_ldap_encryption_key"
down_revision: str | None = "007_add_ldap_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("ldap_config"):
        columns = [col["name"] for col in inspector.get_columns("ldap_config")]
        if "encryption_key" not in columns:
            op.add_column(
                "ldap_config",
                sa.Column("encryption_key", sa.String(length=512), nullable=True),
            )
        else:
            print("Skipping creation of 'encryption_key' because it already exists")
    else:
        print("Skipping alter of 'ldap_config' because table does not exist")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("ldap_config"):
        columns = [col["name"] for col in inspector.get_columns("ldap_config")]
        if "encryption_key" in columns:
            op.drop_column("ldap_config", "encryption_key")
        else:
            print("Skipping drop of 'encryption_key' because it does not exist")
    else:
        print("Skipping drop of 'encryption_key' because table does not exist")
