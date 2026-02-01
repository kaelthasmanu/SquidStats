"""Alembic environment configuration for SquidStats.

This module configures Alembic to work with the SquidStats database models
and supports multiple database backends (SQLite, MySQL/MariaDB, PostgreSQL).
"""

import os

# Import the database configuration and models
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import Config

# Import all models to ensure they're registered with Base.metadata
from database.database import (
    Base,
    get_database_url,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    """Get database URL from application configuration."""
    return get_database_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include object names for better migration tracking
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def include_object(object, name, type_, reflected, compare_to):
    """Filter which database objects to include in migrations.

    This function excludes dynamic tables (user_YYYYMMDD, log_YYYYMMDD)
    from automatic migrations since they are created programmatically.
    """
    # Exclude dynamic tables from migrations
    if type_ == "table":
        # Skip daily user and log tables (they're created dynamically)
        if name.startswith("user_") and name[5:].isdigit() and len(name) == 13:
            return False
        if name.startswith("log_") and name[4:].isdigit() and len(name) == 12:
            return False

    return True


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # Override the sqlalchemy.url in alembic.ini with our dynamic URL
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Include object names for better migration tracking
            include_object=include_object,
            # Compare types to detect schema changes
            compare_type=True,
            # Compare server defaults
            compare_server_default=True,
            # Render as batch for SQLite support
            render_as_batch=Config.DATABASE_TYPE == "SQLITE",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
