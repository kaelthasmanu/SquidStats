import logging
import os
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    func,
    inspect,
    text,
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import declarative_base, sessionmaker

from alembic import command
from config import Config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

Base = declarative_base()
_engine = None
_Session = None
dynamic_model_cache: dict[str, Any] = {}


def get_table_suffix() -> str:
    return date.today().strftime("%Y%m%d")


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
    cpu_usage = Column(String(255), nullable=False)  # Ejemplo: "25.5%"
    ram_usage_bytes = Column(BigInteger, nullable=False)
    swap_usage_bytes = Column(BigInteger, nullable=False)
    net_sent_bytes_sec = Column(BigInteger, nullable=False)
    net_recv_bytes_sec = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)  # 'info', 'warning', 'error', 'success'
    message = Column(Text, nullable=False)
    message_hash = Column(
        String(64), nullable=False, index=True
    )  # SHA256 hash for deduplication
    icon = Column(String(100), nullable=True)
    source = Column(
        String(50), nullable=False, index=True
    )  # 'squid', 'system', 'security', 'users', 'git'
    read = Column(Integer, default=0)  # 0 = unread, 1 = read
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration date
    count = Column(
        Integer, default=1
    )  # Number of times this notification was triggered


class AdminUser(Base):
    """Model for admin users with encrypted passwords."""

    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)  # bcrypt hash
    salt = Column(String(64), nullable=False)  # Salt used for hashing
    role = Column(String(50), nullable=False, default="admin")
    is_active = Column(Integer, default=1)  # 1 = active, 0 = inactive
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


def get_database_url() -> str:
    db_type = Config.DATABASE_TYPE
    conn_str = Config.DATABASE_STRING_CONNECTION
    if db_type == "SQLITE":
        if not conn_str.startswith("sqlite:///"):
            return f"sqlite:///{conn_str}"
        return conn_str
    elif db_type in ("MYSQL", "MARIADB"):
        # Ejemplo: mysql+pymysql://user:password@host/dbname
        # El usuario debe poner el string completo en el .env
        if (
            conn_str.startswith("mysql://")
            or conn_str.startswith("mariadb://")
            or conn_str.startswith("mysql+pymysql://")
        ):
            return conn_str
        raise ValueError(
            "DATABASE_STRING_CONNECTION must start with 'mysql://' or 'mariadb://'."
        )
    elif db_type in ("POSTGRESQL", "POSTGRES"):
        # Ejemplo: postgresql://user:password@host:port/dbname
        # o postgresql+psycopg2://user:password@host:port/dbname
        if (
            conn_str.startswith("postgresql://")
            or conn_str.startswith("postgres://")
            or conn_str.startswith("postgresql+psycopg2://")
            or conn_str.startswith("postgresql+psycopg://")
        ):
            return conn_str
        raise ValueError(
            "DATABASE_STRING_CONNECTION must start with 'postgresql://', 'postgres://', 'postgresql+psycopg2://', or 'postgresql+psycopg://'."
        )
    else:
        raise ValueError(f"Database type not supported: {db_type}")


def create_database_if_not_exists():
    db_type = Config.DATABASE_TYPE
    if db_type == "SQLITE":
        # SQLite crea el archivo automáticamente, no necesitamos hacer nada
        logger.info("SQLite database will be created automatically if it doesn't exist")
        return
    elif db_type in ("MYSQL", "MARIADB"):
        try:
            conn_str = os.getenv("DATABASE_STRING_CONNECTION", "")
            parsed_url = urlparse(conn_str)

            database_name = parsed_url.path.lstrip("/")

            if not database_name:
                logger.warning("No database name found in connection string")
                return

            server_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"

            server_engine = create_engine(server_url, echo=False)

            with server_engine.connect() as conn:
                # Verificar si la base de datos existe
                result = conn.execute(
                    text(
                        f"SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = '{database_name}'"
                    )
                )

                if not result.fetchone():
                    conn.execute(
                        text(
                            f"CREATE DATABASE IF NOT EXISTS `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                    )
                    conn.commit()
                    logger.info(f"Database '{database_name}' created successfully")
                else:
                    logger.info(f"Database '{database_name}' already exists")

            server_engine.dispose()

        except Exception as e:
            logger.error(f"Error creating MySQL/MariaDB database: {e}")
            raise
    elif db_type in ("POSTGRESQL", "POSTGRES"):
        try:
            conn_str = os.getenv("DATABASE_STRING_CONNECTION", "")
            parsed_url = urlparse(conn_str)

            database_name = parsed_url.path.lstrip("/")

            if not database_name:
                logger.warning("No database name found in PostgreSQL connection string")
                return

            # Crear URL para conectarse a la base de datos 'postgres' (default)
            server_url = f"{parsed_url.scheme}://{parsed_url.netloc}/postgres"

            # Crear engine con autocommit para evitar transacciones automáticas
            server_engine = create_engine(
                server_url, echo=False, isolation_level="AUTOCOMMIT"
            )

            try:
                with server_engine.connect() as conn:
                    # Verificar si la base de datos existe
                    result = conn.execute(
                        text(
                            f"SELECT 1 FROM pg_database WHERE datname = '{database_name}'"
                        )
                    )

                    if not result.fetchone():
                        # La base de datos no existe, crearla
                        # Usar una versión más simple que sea compatible con la mayoría de configuraciones
                        try:
                            # Primero intentar con template0 para evitar problemas de collation
                            conn.execute(
                                text(
                                    f"CREATE DATABASE \"{database_name}\" WITH ENCODING = 'UTF8' TEMPLATE = template0"
                                )
                            )
                            logger.info(
                                f"PostgreSQL database '{database_name}' created successfully with template0"
                            )
                        except Exception:
                            # Si falla con template0, intentar sin especificar collation
                            try:
                                conn.execute(
                                    text(
                                        f"CREATE DATABASE \"{database_name}\" WITH ENCODING = 'UTF8'"
                                    )
                                )
                                logger.info(
                                    f"PostgreSQL database '{database_name}' created successfully without collation"
                                )
                            except Exception:
                                # Como último recurso, crear la base de datos sin especificar encoding
                                conn.execute(text(f'CREATE DATABASE "{database_name}"'))
                                logger.info(
                                    f"PostgreSQL database '{database_name}' created successfully with default settings"
                                )
                    else:
                        logger.info(
                            f"PostgreSQL database '{database_name}' already exists"
                        )
            finally:
                server_engine.dispose()

        except Exception as e:
            logger.error(f"Error creating PostgreSQL database: {e}")
            raise


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    create_database_if_not_exists()
    db_url = get_database_url()
    _engine = create_engine(db_url, echo=False, future=True)
    return _engine


def get_session():
    global _Session
    engine = get_engine()
    if _Session is None:
        create_dynamic_tables(engine)
        _Session = sessionmaker(bind=engine)
    return _Session()


def table_exists(engine, table_name: str) -> bool:
    inspector = inspect(engine)
    return inspector.has_table(table_name)


def create_dynamic_tables(engine, date_suffix: str = None):
    LogMetadata.__table__.create(engine, checkfirst=True)
    DeniedLog.__table__.create(engine, checkfirst=True)
    SystemMetrics.__table__.create(engine, checkfirst=True)
    Notification.__table__.create(engine, checkfirst=True)  # Add notifications table

    user_table_name, log_table_name = get_dynamic_table_names(date_suffix)

    creation_logger = logging.getLogger(f"CreateTable_{date_suffix or 'today'}")
    creation_logger.propagate = False  # Evita que el log suba al logger raíz
    if not creation_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        creation_logger.addHandler(handler)

    if not table_exists(engine, user_table_name) or not table_exists(
        engine, log_table_name
    ):
        creation_logger.info(
            f"Creating dynamic tables for date suffix '{date_suffix}': {user_table_name}, {log_table_name}"
        )
        DynamicBase = declarative_base()

        class DynamicUser(DynamicBase):
            __tablename__ = user_table_name
            id = Column(Integer, primary_key=True)
            username = Column(String(255), nullable=False)
            ip = Column(String(255), nullable=False)
            created_at = Column(DateTime, default=datetime.now)

        class DynamicLog(DynamicBase):
            __tablename__ = log_table_name
            id = Column(Integer, primary_key=True)
            user_id = Column(Integer, nullable=False)
            url = Column(Text, nullable=False)
            response = Column(Integer, nullable=False)
            request_count = Column(Integer, default=1)
            data_transmitted = Column(BigInteger, default=0)
            created_at = Column(DateTime, default=datetime.now)

        DynamicBase.metadata.create_all(engine, checkfirst=True)


def get_dynamic_table_names(date_suffix: str = None) -> tuple[str, str]:
    if date_suffix is None:
        date_suffix = get_table_suffix()
    return f"user_{date_suffix}", f"log_{date_suffix}"


def get_dynamic_models(date_suffix: str):
    cache_key = f"user_log_{date_suffix}"
    if cache_key in dynamic_model_cache:
        return dynamic_model_cache[cache_key]

    engine = get_engine()
    user_table_name, log_table_name = get_dynamic_table_names(date_suffix)

    user_exists = table_exists(engine, user_table_name)
    log_exists = table_exists(engine, log_table_name)
    if not user_exists or not log_exists:
        logger.warning(
            f"User/log tables for date suffix '{date_suffix}' do not exist. Attempting to recreate..."
        )
        create_dynamic_tables(engine, date_suffix=date_suffix)
        user_exists = table_exists(engine, user_table_name)
        log_exists = table_exists(engine, log_table_name)
        if not user_exists or not log_exists:
            logger.error(
                f"User/log tables for date suffix '{date_suffix}' could not be created or found."
            )
            return None, None

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

    dynamic_model_cache[cache_key] = (DynamicUser, DynamicLog)
    return DynamicUser, DynamicLog


def get_concat_function(column, separator=", "):
    db_type = Config.DATABASE_TYPE

    if db_type in ("POSTGRESQL", "POSTGRES"):
        # PostgreSQL usa STRING_AGG
        return func.string_agg(column, separator)
    else:
        # MySQL, MariaDB y SQLite usan GROUP_CONCAT
        if separator != ", ":
            # Si hay separador personalizado, usarlo
            return func.group_concat(column, separator)
        else:
            # Separador por defecto
            return func.group_concat(column)


def migrate_database():
    """Run Alembic migrations to update the database schema."""
    try:
        # Get Alembic configuration
        alembic_ini_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "alembic.ini"
        )

        if not os.path.exists(alembic_ini_path):
            logger.warning("alembic.ini not found. Skipping Alembic migrations.")
            logger.warning("Please run: python manage_db.py init")
            return

        alembic_cfg = AlembicConfig(alembic_ini_path)

        # Check if database has been initialized with Alembic
        engine = get_engine()
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()

            if current_rev is None:
                # Database not initialized with Alembic yet
                logger.info("Database not yet initialized with Alembic.")
                logger.info("Checking if schema already exists...")

                inspector = inspect(engine)

                # Check if core tables exist
                core_tables_exist = (
                    inspector.has_table("log_metadata")
                    and inspector.has_table("denied_logs")
                    and inspector.has_table("system_metrics")
                    and inspector.has_table("notifications")
                    and inspector.has_table("admin_users")
                )

                if core_tables_exist:
                    # Schema exists, stamp as current version
                    logger.info(
                        "Existing schema detected. Marking database as up-to-date..."
                    )
                    command.stamp(alembic_cfg, "head")
                    logger.info("✓ Database marked as up-to-date with migrations.")

                    # Ensure admin user exists
                    _ensure_admin_user(conn, engine)
                else:
                    # No schema exists, run all migrations
                    logger.info(
                        "No existing schema found. Running initial migrations..."
                    )
                    command.upgrade(alembic_cfg, "head")
                    logger.info("✓ Database schema created successfully.")

                    # Create admin user after migrations
                    _ensure_admin_user(conn, engine)
            else:
                # Database already initialized, run pending migrations
                logger.info(f"Current database version: {current_rev}")
                logger.info("Checking for pending migrations...")

                # Run pending migrations
                command.upgrade(alembic_cfg, "head")
                logger.info("✓ Database migrations completed successfully.")

                # Ensure admin user exists
                _ensure_admin_user(conn, engine)

    except ImportError as e:
        logger.error(f"Alembic not installed: {e}")
        logger.error("Please install: pip install alembic")
        raise
    except Exception as e:
        logger.error(f"Migration error: {e}")
        logger.error(
            "If you have an existing database, please run: python manage_db.py init"
        )
        raise


def _ensure_admin_user(conn, engine):
    """Ensure admin user exists, create if not."""
    try:
        inspector = inspect(engine)

        if not inspector.has_table("admin_users"):
            logger.warning("admin_users table not found. Cannot create admin user.")
            return

        # Check if admin user exists
        session = get_session()
        try:
            existing_admin = (
                session.query(AdminUser).filter_by(username="admin").first()
            )
            if not existing_admin:
                logger.info("Admin user not found, creating default admin user...")
                _create_default_admin_user(conn, engine)
            else:
                logger.debug("Admin user already exists.")
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"Could not check/create admin user: {e}")


def _create_default_admin_user(conn, engine):
    """Create the default admin user using FIRST_PASSWORD from environment."""
    try:
        import bcrypt

        # Get FIRST_PASSWORD from environment
        first_password = Config.FIRST_PASSWORD

        if not first_password:
            logger.warning(
                "FIRST_PASSWORD not set in .env file. Skipping admin user creation."
            )
            logger.warning(
                "Set FIRST_PASSWORD in your .env file to create the admin user."
            )
            return

        # Hash the password
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(first_password.encode("utf-8"), salt)

        # Insert admin user
        from sqlalchemy import text

        insert_query = text("""
            INSERT INTO admin_users (username, password_hash, salt, role, is_active, created_at, updated_at)
            VALUES (:username, :password_hash, :salt, :role, :is_active, :created_at, :updated_at)
        """)

        from datetime import datetime

        now = datetime.now()

        conn.execute(
            insert_query,
            {
                "username": "admin",
                "password_hash": password_hash.decode("utf-8"),
                "salt": salt.decode("utf-8"),
                "role": "admin",
                "is_active": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        conn.commit()
        logger.info("✓ Default admin user created successfully with FIRST_PASSWORD")

    except ImportError:
        logger.error("bcrypt module not available. Cannot create admin user.")
    except Exception as e:
        logger.error(f"Error creating default admin user: {e}")
        conn.rollback()
