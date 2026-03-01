#!/usr/bin/env python3
"""Database management script for SquidStats.

This script provides convenient commands for managing database migrations
using Alembic. It wraps common Alembic operations with simplified commands.

Usage:
    python manage_db.py init       # Initialize (stamp) database as up-to-date
    python manage_db.py upgrade    # Apply pending migrations
    python manage_db.py downgrade  # Revert last migration
    python manage_db.py current    # Show current migration version
    python manage_db.py history    # Show migration history
    python manage_db.py create     # Create a new migration
"""

import os
import sys
from pathlib import Path

from alembic.config import Config as AlembicConfig
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import inspect

from alembic import command
from database.database import get_engine
from database.models.models import BlacklistDomain
from services.blacklist_service import merge_and_save_blacklist

# Delay import of project modules until runtime (project root added to sys.path above)

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv()


def get_alembic_config():
    """Get Alembic configuration."""
    alembic_ini_path = project_root / "alembic.ini"

    if not alembic_ini_path.exists():
        logger.error(f"alembic.ini not found at {alembic_ini_path}")
        sys.exit(1)

    config = AlembicConfig(str(alembic_ini_path))
    return config


def init_database():
    """Mark database as up-to-date without running migrations.

    Use this for existing databases to initialize Alembic tracking.
    This stamps the database with the latest migration version without
    actually running the migrations (assumes schema already exists).
    """
    config = get_alembic_config()

    logger.info("Initializing database migration tracking...")
    logger.info("This will mark your database as up-to-date with the latest migration.")
    logger.info("Use this ONLY if your database schema is already correct.")

    response = input("Continue? (yes/no): ").lower().strip()
    if response != "yes":
        logger.info("Operation cancelled.")
        return

    try:
        # Stamp database with the latest revision
        command.stamp(config, "head")
        logger.info("✓ Database initialized successfully!")
        logger.info("Your database is now tracked by Alembic.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        sys.exit(1)


def upgrade_database(revision="head"):
    """Apply pending migrations to the database.

    Args:
        revision: Target revision (default: 'head' for latest)
    """
    config = get_alembic_config()

    logger.info(f"Upgrading database to revision: {revision}")

    try:
        command.upgrade(config, revision)
        logger.info("✓ Database upgraded successfully!")
    except Exception as e:
        logger.error(f"Failed to upgrade database: {e}")
        sys.exit(1)


def downgrade_database(revision="-1"):
    """Revert database migrations.

    Args:
        revision: Target revision (default: '-1' for one step back)
    """
    config = get_alembic_config()

    logger.warning(f"Downgrading database to revision: {revision}")
    logger.warning("This operation may result in data loss!")

    response = input("Continue? (yes/no): ").lower().strip()
    if response != "yes":
        logger.info("Operation cancelled.")
        return

    try:
        command.downgrade(config, revision)
        logger.info("✓ Database downgraded successfully!")
    except Exception as e:
        logger.error(f"Failed to downgrade database: {e}")
        sys.exit(1)


def show_current():
    """Show current migration version."""
    config = get_alembic_config()

    try:
        command.current(config, verbose=True)
    except Exception as e:
        logger.error(f"Failed to show current version: {e}")
        sys.exit(1)


def show_history():
    """Show migration history."""
    config = get_alembic_config()

    try:
        command.history(config, verbose=True)
    except Exception as e:
        logger.error(f"Failed to show history: {e}")
        sys.exit(1)


def create_migration(message=None):
    """Create a new migration.

    Args:
        message: Migration message/description
    """
    config = get_alembic_config()

    if not message:
        message = input("Enter migration message: ").strip()
        if not message:
            logger.error("Migration message is required!")
            sys.exit(1)

    try:
        command.revision(config, message=message, autogenerate=True)
        logger.info("✓ Migration created successfully!")
    except Exception as e:
        logger.error(f"Failed to create migration: {e}")
        sys.exit(1)


def migrate_env_blacklist(auto_confirm: bool = False):
    """Migrate domains listed in BLACKLIST_DOMAINS (from .env) into DB table.

    - Reads `BLACKLIST_DOMAINS` environment variable (comma separated)
    - Checks that the `blacklist_domains` table exists in the DB
    - Skips if the env var is empty or not set
    - Uses `services.blacklist_service.merge_and_save_blacklist` to insert/update rows
    """

    val = os.getenv("BLACKLIST_DOMAINS")
    if not val:
        logger.info("No BLACKLIST_DOMAINS found in environment; nothing to migrate.")
        return

    # Trim surrounding quotes if present
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        val = val[1:-1]

    items = [d.strip() for d in val.split(",") if d.strip()]
    if not items:
        logger.info("BLACKLIST_DOMAINS is empty after parsing; nothing to migrate.")
        return

    # Verify table exists
    engine = get_engine()
    inspector = inspect(engine)
    table_name = BlacklistDomain.__tablename__
    if not inspector.has_table(table_name):
        logger.error(
            f"Table '{table_name}' does not exist in the database. Run migrations first."
        )
        return

    # Confirm with user (or auto-confirm)
    logger.info(f"Found {len(items)} domains to migrate into '{table_name}'.")
    if not auto_confirm:
        ans = input("Proceed with migration? (yes/no): ").strip().lower()
        if ans != "yes":
            logger.info("Migration cancelled by user.")
            return

    # Use merge function which will avoid duplicates and reactivate entries
    try:
        merge_and_save_blacklist(
            set(items), source="env_migration", added_by="migrate_env"
        )
        logger.info("✓ BLACKLIST_DOMAINS migrated into database successfully.")
    except Exception:
        logger.exception("Failed migrating BLACKLIST_DOMAINS into DB")
        return


def show_help():
    """Show help message."""
    help_text = """
SquidStats Database Management Tool

Commands:
  init         Initialize database migration tracking (for existing databases)
  upgrade      Apply pending migrations to the database
  downgrade    Revert the last migration (use with caution!)
  current      Show current database migration version
  history      Show complete migration history
  create       Create a new migration file
  help         Show this help message

Examples:
  python manage_db.py init           # First time setup for existing database
  python manage_db.py upgrade        # Apply all pending migrations
  python manage_db.py current        # Check current version
  python manage_db.py create "add user email field"  # Create new migration

  python manage_db.py migrate-env-blacklist   # Migrate BLACKLIST_DOMAINS from .env to DB

For more information, see the Alembic documentation:
https://alembic.sqlalchemy.org/
"""
    print(help_text)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)

    command_name = sys.argv[1].lower()

    commands = {
        "init": init_database,
        "upgrade": upgrade_database,
        "downgrade": downgrade_database,
        "current": show_current,
        "history": show_history,
        "create": lambda: create_migration(sys.argv[2] if len(sys.argv) > 2 else None),
        "migrate-env-blacklist": migrate_env_blacklist,
        "help": show_help,
    }

    if command_name not in commands:
        logger.error(f"Unknown command: {command_name}")
        show_help()
        sys.exit(1)

    commands[command_name]()


if __name__ == "__main__":
    main()
