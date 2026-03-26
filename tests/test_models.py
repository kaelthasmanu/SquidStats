"""
Tests for database models and dynamic table creation.
"""

import os
import sys
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.models import (
    AdminUser,
    BlacklistDomain,
    DeniedLog,
    Log,
    LogMetadata,
    Notification,
    QuotaEvent,
    QuotaGroup,
    QuotaRule,
    QuotaUser,
    SystemMetrics,
    User,
    create_dynamic_models,
)


class TestStaticModels:
    """Test that static model schemas are correct."""

    def test_all_static_tables_created(self, in_memory_engine):
        inspector = inspect(in_memory_engine)
        tables = inspector.get_table_names()
        expected = [
            "log_metadata",
            "denied_logs",
            "system_metrics",
            "notifications",
            "blacklist_domains",
            "admin_users",
            "quota_users",
            "quota_groups",
            "quota_rules",
            "quota_events",
        ]
        for table in expected:
            assert table in tables, f"Table '{table}' should exist"

    def test_admin_user_columns(self, in_memory_engine):
        inspector = inspect(in_memory_engine)
        columns = {c["name"] for c in inspector.get_columns("admin_users")}
        assert {"id", "username", "password_hash", "salt", "role", "is_active"}.issubset(columns)

    def test_quota_user_columns(self, in_memory_engine):
        inspector = inspect(in_memory_engine)
        columns = {c["name"] for c in inspector.get_columns("quota_users")}
        assert {"id", "username", "group_name", "quota_mb", "used_mb"}.issubset(columns)

    def test_notification_columns(self, in_memory_engine):
        inspector = inspect(in_memory_engine)
        columns = {c["name"] for c in inspector.get_columns("notifications")}
        assert {"id", "type", "message", "message_hash", "source", "read"}.issubset(columns)


class TestDynamicModels:
    """Test dynamic user/log table creation."""

    def test_create_dynamic_models(self, in_memory_engine):
        DynUser, DynLog = create_dynamic_models(
            in_memory_engine, "user_20250326", "log_20250326"
        )
        inspector = inspect(in_memory_engine)
        tables = inspector.get_table_names()
        assert "user_20250326" in tables
        assert "log_20250326" in tables

    def test_dynamic_model_columns(self, in_memory_engine):
        DynUser, DynLog = create_dynamic_models(
            in_memory_engine, "user_test", "log_test"
        )
        inspector = inspect(in_memory_engine)

        user_cols = {c["name"] for c in inspector.get_columns("user_test")}
        assert {"id", "username", "ip", "created_at"}.issubset(user_cols)

        log_cols = {c["name"] for c in inspector.get_columns("log_test")}
        assert {"id", "user_id", "url", "response", "data_transmitted"}.issubset(log_cols)

    def test_dynamic_model_insert(self, in_memory_engine):
        DynUser, DynLog = create_dynamic_models(
            in_memory_engine, "user_ins", "log_ins"
        )
        Session = sessionmaker(bind=in_memory_engine)
        session = Session()

        user = DynUser(username="testuser", ip="192.168.1.1")
        session.add(user)
        session.commit()

        result = session.query(DynUser).filter_by(username="testuser").first()
        assert result is not None
        assert result.ip == "192.168.1.1"
        session.close()


class TestModelCRUD:
    """Test basic CRUD on static models."""

    def test_create_notification(self, db_session):
        notif = Notification(
            type="info",
            message="Test notification",
            message_hash="abc123",
            source="test",
        )
        db_session.add(notif)
        db_session.commit()

        result = db_session.query(Notification).first()
        assert result.message == "Test notification"
        assert result.source == "test"
        assert result.read == 0

    def test_create_blacklist_domain(self, db_session):
        domain = BlacklistDomain(
            domain="evil.com",
            source="custom",
            added_by="admin",
        )
        db_session.add(domain)
        db_session.commit()

        result = db_session.query(BlacklistDomain).filter_by(domain="evil.com").first()
        assert result is not None
        assert result.active == 1

    def test_create_quota_user(self, db_session):
        user = QuotaUser(
            username="user1",
            group_name="group1",
            quota_mb=1024,
            used_mb=512,
        )
        db_session.add(user)
        db_session.commit()

        result = db_session.query(QuotaUser).filter_by(username="user1").first()
        assert result.quota_mb == 1024
        assert result.used_mb == 512
        assert result.group_name == "group1"

    def test_create_quota_group(self, db_session):
        group = QuotaGroup(group_name="devs", quota_mb=10240)
        db_session.add(group)
        db_session.commit()

        result = db_session.query(QuotaGroup).filter_by(group_name="devs").first()
        assert result.quota_mb == 10240

    def test_create_denied_log(self, db_session):
        denied = DeniedLog(
            username="baduser",
            ip="10.0.0.5",
            url="http://blocked.com",
            method="GET",
            status="TCP_DENIED/403",
            response=403,
            data_transmitted=0,
        )
        db_session.add(denied)
        db_session.commit()

        result = db_session.query(DeniedLog).first()
        assert result.username == "baduser"
        assert result.response == 403

    def test_create_system_metrics(self, db_session):
        metric = SystemMetrics(
            cpu_usage="25.5",
            ram_usage_bytes=4 * 1024**3,
            swap_usage_bytes=0,
            net_sent_bytes_sec=1000,
            net_recv_bytes_sec=2000,
        )
        db_session.add(metric)
        db_session.commit()

        result = db_session.query(SystemMetrics).first()
        assert result.cpu_usage == "25.5"

    def test_create_log_metadata(self, db_session):
        meta = LogMetadata(last_position=12345, last_inode=67890)
        db_session.add(meta)
        db_session.commit()

        result = db_session.query(LogMetadata).first()
        assert result.last_position == 12345

    def test_create_quota_event(self, db_session):
        event = QuotaEvent(
            event_type="user_quota_exceeded",
            username="user1",
            detail="Exceeded 1024 MB",
        )
        db_session.add(event)
        db_session.commit()

        result = db_session.query(QuotaEvent).first()
        assert result.event_type == "user_quota_exceeded"
