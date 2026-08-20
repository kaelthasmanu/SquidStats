"""Regression tests for startup database repair."""

import bcrypt
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from config import Config
from database.base import Base
from database.database import (
    _ensure_admin_user,
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
