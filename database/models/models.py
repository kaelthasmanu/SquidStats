from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import declarative_base

from database.base import Base


class DailyBase(Base):
    __abstract__ = True

    @declared_attr
    def __tablename__(cls):
        return None


class User(DailyBase):
    __tablename__ = "user_base"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    ip = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class Log(DailyBase):
    __tablename__ = "log_base"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    url = Column(Text, nullable=False)
    response = Column(Integer, nullable=False)
    request_count = Column(Integer, default=1)
    data_transmitted = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.now)


class LogMetadata(Base):
    __tablename__ = "log_metadata"
    id = Column(Integer, primary_key=True)
    last_position = Column(BigInteger, default=0)
    last_inode = Column(BigInteger, default=0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DeniedLog(Base):
    __tablename__ = "denied_logs"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    ip = Column(String(255), nullable=False)
    url = Column(Text, nullable=False)
    method = Column(String(255), nullable=False)
    status = Column(String(255), nullable=False)
    response = Column(Integer, nullable=True)
    data_transmitted = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.now)


class SystemMetrics(Base):
    __tablename__ = "system_metrics"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    cpu_usage = Column(String(255), nullable=False)
    ram_usage_bytes = Column(BigInteger, nullable=False)
    swap_usage_bytes = Column(BigInteger, nullable=False)
    net_sent_bytes_sec = Column(BigInteger, nullable=False)
    net_recv_bytes_sec = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    message_hash = Column(String(64), nullable=False, index=True)
    icon = Column(String(100), nullable=True)
    source = Column(String(50), nullable=False, index=True)
    read = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    expires_at = Column(DateTime, nullable=True)
    count = Column(Integer, default=1)


class BlacklistDomain(Base):
    __tablename__ = "blacklist_domains"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(255), nullable=False, unique=True, index=True)
    source = Column(String(50), nullable=True)  # e.g. 'file', 'url', 'custom'
    source_url = Column(String(512), nullable=True)
    added_by = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    salt = Column(String(64), nullable=False)
    role = Column(String(50), nullable=False, default="admin")
    is_active = Column(Integer, default=1)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class QuotaUser(Base):
    __tablename__ = "quota_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False, unique=True, index=True)
    group_name = Column(String(255), nullable=True, index=True)
    quota_mb = Column(Integer, nullable=False, default=0)
    used_mb = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class QuotaGroup(Base):
    __tablename__ = "quota_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String(255), nullable=False, unique=True, index=True)
    quota_mb = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class QuotaRule(Base):
    __tablename__ = "quota_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy = Column(String(50), nullable=False)
    active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class QuotaEvent(Base):
    __tablename__ = "quota_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)
    username = Column(String(255), nullable=True)
    group_name = Column(String(255), nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)


class BackupConfig(Base):
    __tablename__ = "backup_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    db_type = Column(String(50), nullable=False, default="sqlite")
    frequency = Column(String(50), nullable=False, default="daily_weekly")
    backup_dir = Column(String(512), nullable=False, default="/opt/SquidStats/backups")
    enabled = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class BlockedUser(Base):
    __tablename__ = "blocked_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False, index=True)
    ip = Column(String(45), nullable=False, index=True)
    notes = Column(Text, nullable=True)
    active = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ThrottledUser(Base):
    __tablename__ = "throttled_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False, index=True)
    ip = Column(String(45), nullable=False, index=True)
    pool_number = Column(Integer, nullable=False)
    active = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class TelegramConfig(Base):
    """Single-row table that stores Telegram notification settings."""

    __tablename__ = "telegram_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    enabled = Column(Integer, nullable=False, default=0)
    api_id = Column(String(50), nullable=False, default="")
    api_hash = Column(String(512), nullable=False, default="")
    bot_token = Column(String(512), nullable=False, default="")
    phone = Column(String(50), nullable=False, default="")
    session_name = Column(String(100), nullable=False, default="squidstats_bot")
    recipients = Column(Text, nullable=False, default="")
    encryption_key = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class LdapConfig(Base):
    """Single-row table that stores LDAP / Active Directory connection settings."""

    __tablename__ = "ldap_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String(255), nullable=False, default="")
    port = Column(Integer, nullable=False, default=389)
    use_ssl = Column(Integer, nullable=False, default=0)  # 0 = False, 1 = True
    auth_type = Column(String(20), nullable=False, default="SIMPLE")  # SIMPLE | NTLM
    bind_dn = Column(String(512), nullable=False, default="")
    bind_password = Column(String(512), nullable=False, default="")
    encryption_key = Column(String(512), nullable=True)
    base_dn = Column(String(512), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


def create_dynamic_models(engine, user_table_name: str, log_table_name: str):
    """Factory to create dynamic user/log models bound to a fresh declarative base.

    Returns (DynamicUser, DynamicLog) and ensures tables are created on the given engine.
    """
    DynamicBase = declarative_base()

    class DynamicUser(DynamicBase):
        __tablename__ = user_table_name
        id = Column(Integer, primary_key=True, autoincrement=True)
        username = Column(String(255), nullable=False)
        ip = Column(String(255), nullable=False)
        created_at = Column(DateTime, default=datetime.now)

    class DynamicLog(DynamicBase):
        __tablename__ = log_table_name
        id = Column(Integer, primary_key=True, autoincrement=True)
        user_id = Column(Integer, nullable=False)
        url = Column(Text, nullable=False)
        response = Column(Integer, nullable=False)
        request_count = Column(Integer, default=1)
        data_transmitted = Column(BigInteger, default=0)
        created_at = Column(DateTime, default=datetime.now)

    DynamicBase.metadata.create_all(engine, checkfirst=True)
    return DynamicUser, DynamicLog
