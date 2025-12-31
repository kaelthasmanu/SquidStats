import logging
import os
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
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

# Cargar variables de entorno desde .env
load_dotenv()

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
    db_type = os.getenv("DATABASE_TYPE", "SQLITE").upper()
    conn_str = os.getenv("DATABASE_STRING_CONNECTION", "squidstats.db")
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
    db_type = os.getenv("DATABASE_TYPE", "SQLITE").upper()
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
    db_type = os.getenv("DATABASE_TYPE", "SQLITE").upper()

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
    engine = get_engine()
    db_type = os.getenv("DATABASE_TYPE", "SQLITE").upper()
    inspector = inspect(engine)
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        with engine.connect() as conn:
            # Ensure admin_users table exists for authentication
            if not inspector.has_table("admin_users"):
                logger.info("Creating admin_users table (missing)")
                AdminUser.__table__.create(bind=engine, checkfirst=True)
                conn.commit()
                # Refresh inspector after table creation
                inspector = inspect(engine)

                # Create default admin user if table was just created
                _create_default_admin_user(conn, engine)

            # Check if admin user exists, create if not
            try:
                session = get_session()
                existing_admin = (
                    session.query(AdminUser).filter_by(username="admin").first()
                )
                if not existing_admin:
                    logger.info("Admin user not found, creating default admin user")
                    _create_default_admin_user(conn, engine)
                else:
                    logger.info("Admin user already exists")
                session.close()
            except Exception as e:
                logger.warning(f"Could not check/create admin user: {e}")

            # Define expected schema for all tables
            expected_schemas = {
                "user_base": {
                    "username": {"type": "VARCHAR(255)", "nullable": False},
                    "ip": {"type": "VARCHAR(255)", "nullable": False},
                },
                "log_base": {"url": {"type": "TEXT", "nullable": False}},
                "denied_logs": {
                    "username": {"type": "VARCHAR(255)", "nullable": False},
                    "ip": {"type": "VARCHAR(255)", "nullable": False},
                    "url": {"type": "TEXT", "nullable": False},
                    "method": {"type": "VARCHAR(255)", "nullable": False},
                    "status": {"type": "VARCHAR(255)", "nullable": False},
                },
                "system_metrics": {
                    "cpu_usage": {"type": "VARCHAR(255)", "nullable": False}
                },
            }
            for table_name, expected_columns in expected_schemas.items():
                if not inspector.has_table(table_name):
                    logger.info(f"Table {table_name} doesn't exist, skipping migration")
                    continue
                logger.info(f"Checking schema for table: {table_name}")
                current_columns = inspector.get_columns(table_name)
                for column_name, expected_spec in expected_columns.items():
                    # Find current column info
                    current_column = next(
                        (col for col in current_columns if col["name"] == column_name),
                        None,
                    )
                    if not current_column:
                        logger.warning(
                            f"Column {column_name} not found in {table_name}"
                        )
                        continue
                    logger.info(
                        f"Checking {table_name}.{column_name}: current type = {current_column['type']}"
                    )
                    # Check if migration is needed
                    needs_migration = _column_needs_migration(
                        current_column, expected_spec, db_type
                    )
                    if needs_migration:
                        logger.info(
                            f"Migrating {table_name}.{column_name} to {expected_spec['type']}"
                        )
                        _migrate_column(
                            conn, table_name, column_name, expected_spec, db_type
                        )
                    else:
                        logger.info(
                            f"No migration needed for {table_name}.{column_name}"
                        )
            # Also check dynamic tables (user_YYYYMMDD, log_YYYYMMDD)
            _migrate_dynamic_tables(conn, inspector, db_type)
            conn.commit()
            logger.info("Database migration completed successfully")
    except Exception as e:
        logger.warning(
            f"Migration warning (this might be expected if already migrated): {e}"
        )
    finally:
        logger.setLevel(original_level)


def _column_needs_migration(current_column, expected_spec, db_type):
    current_type = str(current_column["type"]).upper()
    expected_type = expected_spec["type"].upper()
    logger.debug(
        f"Checking migration: current='{current_type}' vs expected='{expected_type}'"
    )
    # Normalize type representations across different databases
    if db_type in ("MYSQL", "MARIADB"):
        # MySQL type mapping
        if "VARCHAR(255)" in expected_type and (
            "VARCHAR" in current_type or "CHAR" in current_type
        ):
            # Extract current length
            import re

            match = re.search(r"VARCHAR\((\d+)\)", current_type)
            if match:
                current_length = int(match.group(1))
                logger.debug(
                    f"MySQL VARCHAR: current length={current_length}, expected=255"
                )
                return current_length != 255  # Changed from < to != for exact match
            else:
                # If no length found, assume it needs migration
                return True
        elif "TEXT" in expected_type and "TEXT" not in current_type:
            return True
    elif db_type in ("POSTGRESQL", "POSTGRES"):
        # PostgreSQL type mapping
        if "VARCHAR(255)" in expected_type:
            if "CHARACTER VARYING" in current_type or "VARCHAR" in current_type:
                import re

                match = re.search(
                    r"(?:CHARACTER VARYING|VARCHAR)\((\d+)\)", current_type
                )
                if match:
                    current_length = int(match.group(1))
                    logger.debug(
                        f"PostgreSQL VARCHAR: current length={current_length}, expected=255"
                    )
                    return current_length != 255  # Changed from < to != for exact match
                # If no length specified, it might need migration
                return "(" not in current_type
            else:
                # Different type entirely, needs migration
                return True
        elif "TEXT" in expected_type and "TEXT" not in current_type:
            return True
    elif db_type == "SQLITE":
        # SQLite is more flexible with types, but let's still check for obvious differences
        if "VARCHAR(255)" in expected_type and (
            "VARCHAR" in current_type or "CHAR" in current_type
        ):
            import re

            match = re.search(r"VARCHAR\((\d+)\)", current_type)
            if match:
                current_length = int(match.group(1))
                logger.debug(
                    f"SQLite VARCHAR: current length={current_length}, expected=255"
                )
                return current_length != 255
        # For SQLite, generally don't migrate unless there's a significant type difference
        return False
    return False


def _migrate_column(conn, table_name, column_name, expected_spec, db_type):
    try:
        if db_type in ("MYSQL", "MARIADB"):
            nullable_clause = "" if expected_spec["nullable"] else "NOT NULL"
            sql = f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} {expected_spec['type']} {nullable_clause}"
            conn.execute(text(sql))
            logger.info(
                f"Migrated {table_name}.{column_name} to {expected_spec['type']}"
            )
        elif db_type in ("POSTGRESQL", "POSTGRES"):
            sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE {expected_spec['type']}"
            conn.execute(text(sql))
            logger.info(
                f"Migrated {table_name}.{column_name} to {expected_spec['type']}"
            )
        elif db_type == "SQLITE":
            logger.info(
                f"SQLite migration skipped for {table_name}.{column_name} (flexible typing)"
            )
    except Exception as e:
        logger.error(f"Failed to migrate {table_name}.{column_name}: {e}")


def _migrate_dynamic_tables(conn, inspector, db_type):
    # Get all table names that match the dynamic pattern
    all_tables = inspector.get_table_names()
    user_tables = [t for t in all_tables if re.match(r"user_\d{8}$", t)]
    logger.info(f"Found {len(user_tables)} dynamic user tables: {user_tables}")
    # Define expected schema for dynamic tables
    user_schema = {
        "username": {"type": "VARCHAR(255)", "nullable": False},
        "ip": {
            "type": "VARCHAR(255)",
            "nullable": False,
        },
    }
    # Migrate user tables
    for table_name in user_tables:
        logger.info(f"Checking dynamic table: {table_name}")
        current_columns = inspector.get_columns(table_name)
        for column_name, expected_spec in user_schema.items():
            current_column = next(
                (col for col in current_columns if col["name"] == column_name), None
            )
            if current_column:
                logger.info(
                    f"Checking {table_name}.{column_name}: current type = {current_column['type']}"
                )
                if _column_needs_migration(current_column, expected_spec, db_type):
                    logger.info(
                        f"Migrating dynamic table {table_name}.{column_name} to {expected_spec['type']}"
                    )
                    _migrate_column(
                        conn, table_name, column_name, expected_spec, db_type
                    )
                else:
                    logger.info(f"No migration needed for {table_name}.{column_name}")


def _create_default_admin_user(conn, engine):
    """Create the default admin user using FIRST_PASSWORD from environment."""
    try:
        import bcrypt

        # Get FIRST_PASSWORD from environment
        first_password = os.getenv("FIRST_PASSWORD", "").strip()

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
