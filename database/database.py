import os
import sqlite3
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from loguru import logger
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Table,
    create_engine,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from alembic import command
from config import Config
from database.base import Base  # noqa: F401
from database.models import (
    AdminUser,
    DeniedLog,
    LogMetadata,
    Notification,
    SystemMetrics,
)
from database.models.models import BlacklistDomain, create_dynamic_models

_engine = None
_Session = None
dynamic_model_cache: dict[str, Any] = {}

# SQLite startup failures can be transient when another process is closing the
# database or when its WAL files are being initialized.  Keep this bounded so
# a permanent filesystem/corruption problem fails clearly instead of hanging
# application startup forever.
SQLITE_MIGRATION_RETRY_DELAYS = (1.0, 2.0, 4.0)


def get_table_suffix() -> str:
    return date.today().strftime("%Y%m%d")


def _normalize_sqlite_path(path_str: str) -> Path:
    path_str = path_str.strip()

    if path_str in ("", "."):
        raise ValueError(
            "DATABASE_STRING_CONNECTION for SQLITE must contain a database path"
        )

    if path_str == ":memory:" or path_str == "sqlite:///:memory:":
        return Path(":memory:")

    if path_str.startswith("sqlite:///"):
        path_str = path_str[len("sqlite:///") :]

    if not path_str:
        raise ValueError(
            "DATABASE_STRING_CONNECTION for SQLITE must contain a database path"
        )

    project_root = Path(__file__).resolve().parents[1]
    db_path = Path(path_str)

    if not db_path.is_absolute():
        db_path = project_root / db_path

    if path_str.endswith("/") or db_path.is_dir():
        db_path = db_path / "squidstats.db"

    return db_path


def get_database_url() -> str:
    db_type = Config.DATABASE_TYPE
    conn_str = Config.DATABASE_STRING_CONNECTION
    if db_type == "SQLITE":
        db_path = _normalize_sqlite_path(conn_str)
        if str(db_path) == ":memory:":
            return "sqlite:///:memory:"
        return f"sqlite:///{db_path}"
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
                        "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = :dbname"
                    ),
                    {"dbname": database_name},
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
                        text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                        {"dbname": database_name},
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
    db_type = Config.DATABASE_TYPE
    if db_type == "SQLITE":
        _engine = create_engine(
            db_url,
            echo=False,
            future=True,
            connect_args={"timeout": 30, "check_same_thread": False},
        )

        # Enable WAL journal mode and set synchronous=NORMAL for the connection.
        # WAL allows concurrent reads while a write is in progress and dramatically
        # reduces "database is locked" errors in multi-threaded apps.
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragmas(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    else:
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
    """Create every static table and the dynamic tables for one day.

    ``create_all(checkfirst=True)`` is intentionally used here in addition to
    Alembic.  Alembic tracks *schema versions*, but a table can be deleted
    manually while the version remains at ``head``; in that case Alembic has
    no pending migration to run.  SQLAlchemy creates only tables that are
    absent and leaves existing tables and their data untouched.
    """
    existing_tables = set(inspect(engine).get_table_names())

    # All models that inherit from database.base.Base are registered in this
    # metadata, including tables added in later migrations.
    Base.metadata.create_all(engine, checkfirst=True)

    LogMetadata.__table__.create(engine, checkfirst=True)
    DeniedLog.__table__.create(engine, checkfirst=True)
    SystemMetrics.__table__.create(engine, checkfirst=True)
    Notification.__table__.create(engine, checkfirst=True)  # Add notifications table
    BlacklistDomain.__table__.create(engine, checkfirst=True)
    # New quota tables for the admin quota feature
    from database.models.models import QuotaEvent, QuotaGroup, QuotaRule, QuotaUser

    QuotaUser.__table__.create(engine, checkfirst=True)
    QuotaGroup.__table__.create(engine, checkfirst=True)
    QuotaRule.__table__.create(engine, checkfirst=True)
    QuotaEvent.__table__.create(engine, checkfirst=True)

    user_table_name, log_table_name = get_dynamic_table_names(date_suffix)

    logger.info(f"CreateTable_{date_suffix or 'today'}")

    if not table_exists(engine, user_table_name) or not table_exists(
        engine, log_table_name
    ):
        logger.info(
            f"Creating dynamic tables for date suffix '{date_suffix}': {user_table_name}, {log_table_name}"
        )
        # Use create_dynamic_models to define and create the per-day user/log tables
        try:
            create_dynamic_models(engine, user_table_name, log_table_name)
        except Exception as e:
            logger.error(f"Error creating dynamic user/log tables: {e}")
            raise

    created_tables = sorted(
        set(inspect(engine).get_table_names()).difference(existing_tables)
    )
    if created_tables:
        logger.warning(
            "Database schema repair created missing tables: {}",
            ", ".join(created_tables),
        )


def repair_database_schema(engine, date_suffix: str = None) -> list[str]:
    """Repair missing application tables without deleting or altering data.

    Returns the names of tables created during this repair.  Rows that were
    previously deleted cannot be recovered by recreating an empty table; a
    database backup is required for data recovery.
    """
    before = set(inspect(engine).get_table_names())
    current_suffix = date_suffix or get_table_suffix()
    create_dynamic_tables(engine, date_suffix=current_suffix)

    # Keep historical user/log pairs consistent as well.  If one side of a
    # known pair was removed, recreate only that side and preserve the other.
    known_suffixes = {current_suffix}
    for table_name in inspect(engine).get_table_names():
        if table_name.startswith(("user_", "log_")):
            _, suffix = table_name.split("_", 1)
            if suffix.isdigit() and len(suffix) == 8:
                known_suffixes.add(suffix)

    for historical_suffix in sorted(known_suffixes):
        user_table_name, log_table_name = get_dynamic_table_names(historical_suffix)
        current_tables = set(inspect(engine).get_table_names())
        if (
            user_table_name not in current_tables
            or log_table_name not in current_tables
        ):
            create_dynamic_tables(engine, date_suffix=historical_suffix)

    after = set(inspect(engine).get_table_names())
    created_tables = sorted(after.difference(before))

    missing_static_tables = set(Base.metadata.tables).difference(after)
    if missing_static_tables:
        raise RuntimeError(
            "Database schema repair could not create tables: "
            + ", ".join(sorted(missing_static_tables))
        )

    return created_tables


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

    DynamicUser, DynamicLog = create_dynamic_models(
        engine, user_table_name, log_table_name
    )

    dynamic_model_cache[cache_key] = (DynamicUser, DynamicLog)
    return DynamicUser, DynamicLog


def _verify_sqlite_database(engine):
    """Verify that SQLite can read, validate, and write the database.

    The write check is performed inside a transaction and rolled back. It
    exercises the main database file without leaving a sentinel table or
    changing application data behind.
    """
    check_table = f"_squidstats_startup_check_{uuid.uuid4().hex}"
    check_table_definition = Table(
        check_table,
        MetaData(),
        Column("id", Integer, nullable=False),
    )

    logger.info("Checking SQLite database access and integrity...")
    with engine.connect() as connection:
        quick_check = connection.exec_driver_sql("PRAGMA quick_check").scalar()
        if str(quick_check).lower() != "ok":
            raise RuntimeError(
                f"SQLite integrity check failed: PRAGMA quick_check returned {quick_check!r}"
            )

        # End any transaction opened implicitly by the read before acquiring
        # the write lock for the actual read/write capability check.
        connection.rollback()
        transaction_started = False
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            transaction_started = True
            check_table_definition.create(connection)
            connection.execute(check_table_definition.insert().values(id=1))
            connection.rollback()
            transaction_started = False
        except Exception:
            if transaction_started:
                connection.rollback()
            raise

    logger.info("✓ SQLite database read/write and integrity checks passed")


def _is_transient_sqlite_error(error: Exception) -> bool:
    """Return whether an SQLite error is worth retrying during startup."""
    if Config.DATABASE_TYPE != "SQLITE":
        return False

    candidates = []
    current = error
    for _ in range(5):
        if current is None or current in candidates:
            break
        candidates.append(current)
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)

    is_sqlite_operational_error = any(
        isinstance(candidate, (OperationalError, sqlite3.OperationalError))
        for candidate in candidates
    )
    if not is_sqlite_operational_error:
        return False

    error_text = " ".join(str(candidate).lower() for candidate in candidates)
    transient_markers = (
        "database is locked",
        "database table is locked",
        "database schema is locked",
        "disk i/o error",
        "unable to open database file",
        "database or disk is full",
    )
    return any(marker in error_text for marker in transient_markers)


def _dispose_database_engine_after_failure():
    """Close pooled connections before a migration retry."""
    if _engine is not None:
        _engine.dispose()


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
    """Run migrations with bounded retries for transient SQLite failures."""
    total_attempts = len(SQLITE_MIGRATION_RETRY_DELAYS) + 1

    for attempt in range(1, total_attempts + 1):
        try:
            _migrate_database_once()
            return
        except Exception as error:
            is_last_attempt = attempt == total_attempts
            if is_last_attempt or not _is_transient_sqlite_error(error):
                raise

            delay = SQLITE_MIGRATION_RETRY_DELAYS[attempt - 1]
            logger.warning(
                "Transient SQLite startup error on migration attempt {}/{}: {}. "
                "Retrying in {} seconds...",
                attempt,
                total_attempts,
                error,
                delay,
            )
            _dispose_database_engine_after_failure()
            time.sleep(delay)


def _migrate_database_once():
    """Run one migration attempt, including the SQLite preflight checks."""
    try:
        # Get Alembic configuration
        alembic_ini_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "alembic.ini"
        )

        if not os.path.exists(alembic_ini_path):
            logger.warning("alembic.ini not found. Skipping Alembic migrations.")
            logger.warning(
                "Running model-based schema repair instead; "
                "please restore alembic.ini for future migrations."
            )
            engine = get_engine()
            if Config.DATABASE_TYPE == "SQLITE":
                _verify_sqlite_database(engine)
            repaired_tables = repair_database_schema(engine)
            if repaired_tables:
                logger.warning(
                    "Startup database repair recreated: {}",
                    ", ".join(repaired_tables),
                )
            _ensure_admin_user(engine)
            return

        alembic_cfg = AlembicConfig(alembic_ini_path)

        engine = get_engine()
        if Config.DATABASE_TYPE == "SQLITE":
            _verify_sqlite_database(engine)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()
            existing_tables = set(inspect(conn).get_table_names())

        # If the version table is missing but there is an existing schema,
        # preserve that schema and repair it before recording its migration
        # state.  Running the initial migration against a partially existing
        # schema would try to recreate tables that are already there.
        application_tables = existing_tables.difference({"alembic_version"})

        if current_rev is None:
            logger.info("Database is not currently tracked by Alembic.")
            if application_tables:
                logger.info(
                    "Existing schema detected without migration tracking; "
                    "repairing missing tables before marking it as current."
                )
                repair_database_schema(engine)
                command.stamp(alembic_cfg, "head")
                logger.info("✓ Existing database marked as up-to-date with migrations.")
            else:
                logger.info("No existing schema found. Running initial migrations...")
                command.upgrade(alembic_cfg, "head")
                logger.info("✓ Database schema created successfully.")
        else:
            logger.info(f"Current database version: {current_rev}")
            logger.info("Checking for pending migrations...")
            command.upgrade(alembic_cfg, "head")
            logger.info("✓ Database migrations completed successfully.")

        # Alembic does not rerun a migration when a table is removed after the
        # migration reached head.  Always perform this idempotent repair at
        # startup, including after an entirely new database was migrated.
        repaired_tables = repair_database_schema(engine)
        if repaired_tables:
            logger.warning(
                "Startup database repair recreated: {}",
                ", ".join(repaired_tables),
            )
        _ensure_admin_user(engine)

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


def _ensure_admin_user(engine):
    """Ensure admin user exists, create if not."""
    try:
        inspector = inspect(engine)

        if not inspector.has_table("admin_users"):
            logger.warning("admin_users table not found. Cannot create admin user.")
            return False

        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            existing_admin = (
                session.query(AdminUser).filter_by(username="admin").first()
            )
            if not existing_admin:
                logger.info("Admin user not found, creating default admin user...")
                return _create_default_admin_user(session)
            return False
        finally:
            session.close()
    except IntegrityError:
        # Another process may have created the default user between the query
        # and the insert.  The unique username constraint makes this harmless.
        logger.info("Admin user was created concurrently by another process.")
        return False
    except Exception as e:
        logger.warning(f"Could not check/create admin user: {e}")
        return False


def _create_default_admin_user(session):
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
            return False

        # Hash the password
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(first_password.encode("utf-8"), salt)

        now = datetime.now()
        session.add(
            AdminUser(
                username="admin",
                password_hash=password_hash.decode("utf-8"),
                salt=salt.decode("utf-8"),
                role="admin",
                is_active=1,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
        logger.info("✓ Default admin user created successfully with FIRST_PASSWORD")
        return True

    except ImportError:
        logger.error("bcrypt module not available. Cannot create admin user.")
        session.rollback()
    except IntegrityError:
        # Another process may have created the default user after the lookup.
        session.rollback()
        logger.info("Admin user was created concurrently by another process.")
    except Exception as e:
        logger.error(f"Error creating default admin user: {e}")
        session.rollback()
    return False
