"""Regression tests for removing the obsolete Squid log format setting."""

from alembic.config import Config as AlembicConfig
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)

from alembic import command
from config import Config


def test_remove_log_format_migration_preserves_squid_config(tmp_path, monkeypatch):
    database_path = tmp_path / "squidstats.db"
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    metadata = MetaData()
    Table(
        "squid_config",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("squid_host", String(255), nullable=False),
        Column("squid_port", Integer, nullable=False),
        Column("squid_hosts", String(512), nullable=False),
        Column("log_format", String(50), nullable=False),
        Column("squid_log", String(512), nullable=False),
        Column("squid_cache_log", String(512), nullable=False),
        Column("squid_config_path", String(512), nullable=False),
        Column("acl_files_dir", String(512), nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO squid_config "
                "(id, squid_host, squid_port, squid_hosts, log_format, squid_log, "
                "squid_cache_log, squid_config_path, acl_files_dir, created_at) "
                "VALUES (1, '127.0.0.1', 3128, '', 'DETAILED', '/var/log/squid/access.log', "
                "'/var/log/squid/cache.log', '/etc/squid/squid.conf', '', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('010_add_squid_config')")
        )

    old_database_type = Config.DATABASE_TYPE
    old_connection = Config.DATABASE_STRING_CONNECTION
    monkeypatch.setattr(Config, "DATABASE_TYPE", "SQLITE")
    monkeypatch.setattr(Config, "DATABASE_STRING_CONNECTION", str(database_path))

    try:
        alembic_config = AlembicConfig("alembic.ini")
        command.upgrade(alembic_config, "head")
    finally:
        Config.DATABASE_TYPE = old_database_type
        Config.DATABASE_STRING_CONNECTION = old_connection

    columns = {column["name"] for column in inspect(engine).get_columns("squid_config")}
    assert "log_format" not in columns
    assert {"squid_host", "squid_port", "squid_log"}.issubset(columns)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM squid_config")).scalar() == 1

    engine.dispose()
