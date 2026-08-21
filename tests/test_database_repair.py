"""Regression tests for startup database repair and SQLite startup checks."""

import sqlite3

import bcrypt
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import database.database as db_module
from config import Config
from database.base import Base
from database.database import (
    _ensure_admin_user,
    _is_transient_sqlite_error,
    _verify_sqlite_access,
    create_dynamic_models,
    repair_database_schema,
)
from database.models.models import AdminUser, QuotaUser
from services.database.admin_helpers import get_all_tables_stats


def test_repair_recreates_missing_tables_and_preserves_existing_rows():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    suffix = "20990101"
    user_table = f"user_{suffix}"
    log_table = f"log_{suffix}"
    create_dynamic_models(engine, user_table, log_table)

    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(QuotaUser(username="preserved-user"))
    session.commit()
    session.close()

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE quota_events"))
        connection.execute(text(f"DROP TABLE {log_table}"))

    created = repair_database_schema(engine, date_suffix=suffix)

    tables = set(inspect(engine).get_table_names())
    assert "quota_events" in tables
    assert log_table in tables
    assert "quota_events" in created
    assert log_table in created

    session = Session()
    assert session.query(QuotaUser).filter_by(username="preserved-user").count() == 1
    session.close()
    engine.dispose()


def test_ensure_admin_user_creates_it_once(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(Config, "FIRST_PASSWORD", "test-admin-password")

    assert _ensure_admin_user(engine) is True
    assert _ensure_admin_user(engine) is False

    Session = sessionmaker(bind=engine)
    session = Session()
    admins = session.query(AdminUser).filter_by(username="admin").all()
    assert len(admins) == 1
    assert bcrypt.checkpw(
        b"test-admin-password", admins[0].password_hash.encode("utf-8")
    )
    session.close()
    engine.dispose()


def test_sqlite_table_stats_work_without_dbstat(in_memory_engine, db_session):
    stats = get_all_tables_stats(db_session, in_memory_engine, "SQLITE")

    assert "admin_users" in stats
    assert stats["admin_users"]["rows"] == 0
    assert stats["admin_users"]["size"] >= 0


def test_sqlite_startup_check_validates_access_and_rolls_back_write(tmp_path):
    database_path = tmp_path / "startup-check.db"
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        statements.append(statement)

    _verify_sqlite_access(engine)

    assert database_path.exists()
    tables = set(inspect(engine).get_table_names())
    assert not any(table.startswith("_squidstats_startup_check_") for table in tables)
    assert not any("quick_check" in statement.lower() for statement in statements)
    engine.dispose()


def test_transient_sqlite_errors_are_detected():
    error = OperationalError(
        "migration",
        {},
        sqlite3.OperationalError("database is locked"),
    )

    assert _is_transient_sqlite_error(error) is True
    assert _is_transient_sqlite_error(RuntimeError("database is locked")) is False


def test_migrate_database_retries_transient_errors(monkeypatch):
    attempts = []
    delays = []

    def flaky_migration():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise OperationalError(
                "migration",
                {},
                sqlite3.OperationalError("database is locked"),
            )

    monkeypatch.setattr(db_module, "_migrate_database_once", flaky_migration)
    monkeypatch.setattr(
        db_module, "_dispose_database_engine_after_failure", lambda: None
    )
    monkeypatch.setattr(db_module.time, "sleep", delays.append)

    db_module.migrate_database()

    assert attempts == [1, 2, 3]
    assert delays == [1.0, 2.0]
