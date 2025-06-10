from sqlalchemy import (
    create_engine, Column, Integer, String, ForeignKey,
    BigInteger, Text, DateTime, inspect, text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.declarative import declared_attr
import datetime
import os
import logging
import pytz

# Configuración de la zona horaria para Cuba
TIMEZONE = pytz.timezone('America/Havana')

# Configurar logging para seguimiento
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Base declarativa principal (abstracta para modelos dinámicos)
Base = declarative_base()

def get_table_suffix():
    """
    Devuelve el sufijo de fecha para tablas dinámicas en formato YYYYMMDD.
    Si la hora actual está entre 00:00 y 00:05, se usa el día anterior para evitar inconsistencias
    con tablas que se actualizan justo a medianoche.
    """
    now = datetime.datetime.now(TIMEZONE)
    if now.hour == 0 and now.minute < 5:
        table_date = now - datetime.timedelta(days=1)
        logger.info(f"Ventana de cambio de día. Usando fecha anterior: {table_date.strftime('%Y%m%d')}")
    else:
        table_date = now
    return table_date.strftime("%Y%m%d")


class DailyBase(Base):
    """
    Clase base abstracta para tablas dinámicas diarias.
    Cambia el nombre de tabla automáticamente para incluir sufijo YYYYMMDD.
    """
    __abstract__ = True

    @declared_attr
    def __tablename__(cls):
        return f"{cls.__name__.lower()}_{get_table_suffix()}"


class User(DailyBase):
    """
    Modelo User para tabla diaria dinámica user_YYYYMMDD.
    """
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    ip = Column(String(15), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now)


class Log(DailyBase):
    """
    Modelo Log para tabla diaria dinámica log_YYYYMMDD.
    """
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)  # No FK automática por tablas dinámicas
    url = Column(Text, nullable=False)
    response = Column(Integer)
    request_count = Column(Integer, default=1)
    data_transmitted = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)


class LogMetadata(Base):
    """
    Tabla fija para guardar metadatos como posición e inode del archivo de logs procesado.
    Solo existe una tabla log_metadata sin sufijo.
    """
    __tablename__ = "log_metadata"
    id = Column(Integer, primary_key=True)
    last_position = Column(BigInteger, default=0)
    last_inode = Column(BigInteger, default=0)


def get_engine():
    """
    Crea y retorna el engine SQLAlchemy según variable de entorno:
    - DATABASE_TYPE: 'SQLITE' o 'MARIADB' (default MARIADB)
    - DATABASE_STRING_CONNECTION: cadena de conexión
    """
    db_type = os.getenv("DATABASE_TYPE", "MARIADB")
    conn_str = os.getenv("DATABASE_STRING_CONNECTION")

    if not conn_str:
        logger.error("DATABASE_STRING_CONNECTION no está definido")
        raise ValueError("Cadena de conexión a BD no configurada")

    if db_type.upper() == "SQLITE":
        # Asegurar que el directorio exista (SQLite usa ruta archivo)
        db_dir = os.path.dirname(os.path.abspath(conn_str))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        # Engine para SQLite con check_same_thread para múltiples hilos
        return create_engine(
            f"sqlite:///{conn_str}",
            echo=False,
            connect_args={"check_same_thread": False}
        )
    elif db_type.upper() == "MARIADB":
        # Engine para MariaDB con pool_pre_ping para conexiones persistentes
        return create_engine(conn_str, echo=False, pool_pre_ping=True)

    logger.error(f"Tipo de base de datos no soportado: {db_type}")
    raise ValueError(f"Tipo de BD no soportado: {db_type}")


def get_session():
    """
    Crea una sesión de SQLAlchemy y se asegura de crear las tablas dinámicas si no existen.
    """
    engine = get_engine()
    create_dynamic_tables(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def table_exists(engine, table_name):
    """
    Comprueba si una tabla existe en la base de datos.
    """
    inspector = inspect(engine)
    return inspector.has_table(table_name)


def create_dynamic_tables(engine):
    """
    Crea la tabla fija log_metadata y las tablas dinámicas user_YYYYMMDD y log_YYYYMMDD
    si no existen ya.
    La creación es manual con SQL para mayor control y compatibilidad.
    """
    # Crear tabla fija de metadatos si no existe
    if not table_exists(engine, "log_metadata"):
        LogMetadata.__table__.create(engine)
        logger.info("Tabla log_metadata creada")

    # Obtener sufijo dinámico actual
    table_suffix = get_table_suffix()
    user_table_name = f"user_{table_suffix}"
    log_table_name = f"log_{table_suffix}"

    db_type = os.getenv("DATABASE_TYPE", "MARIADB").upper()

    # Crear tabla user dinámica
    if not table_exists(engine, user_table_name):
        logger.info(f"Creando tabla dinámica: {user_table_name}")
        try:
            if db_type == "SQLITE":
                create_user_sql = text(f"""
                    CREATE TABLE IF NOT EXISTS "{user_table_name}" (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username VARCHAR(255) NOT NULL,
                        ip VARCHAR(15) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            else:
                # MariaDB con índices para username e ip
                create_user_sql = text(f"""
                    CREATE TABLE IF NOT EXISTS `{user_table_name}` (
                        id INTEGER NOT NULL AUTO_INCREMENT,
                        username VARCHAR(255) NOT NULL,
                        ip VARCHAR(15) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        INDEX idx_username (username),
                        INDEX idx_ip (ip)
                    )
                """)
            with engine.connect() as conn:
                conn.execute(create_user_sql)
                conn.commit()
            logger.info(f"Tabla {user_table_name} creada exitosamente")
        except Exception as e:
            logger.error(f"Error creando tabla {user_table_name}: {e}")

    # Crear tabla log dinámica
    if not table_exists(engine, log_table_name):
        logger.info(f"Creando tabla dinámica: {log_table_name}")
        try:
            if db_type == "SQLITE":
                create_log_sql = text(f"""
                    CREATE TABLE IF NOT EXISTS "{log_table_name}" (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        url TEXT NOT NULL,
                        response INTEGER NOT NULL,
                        request_count INTEGER NOT NULL DEFAULT 1,
                        data_transmitted BIGINT NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            else:
                create_log_sql = text(f"""
                    CREATE TABLE IF NOT EXISTS `{log_table_name}` (
                        id INTEGER NOT NULL AUTO_INCREMENT,
                        user_id INTEGER NOT NULL,
                        url TEXT NOT NULL,
                        response INTEGER NOT NULL,
                        request_count INTEGER NOT NULL DEFAULT 1,
                        data_transmitted BIGINT NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        INDEX idx_user_id (user_id),
                        INDEX idx_created_at (created_at),
                        INDEX idx_response (response),
                        FOREIGN KEY (user_id) REFERENCES `{user_table_name}`(id)
                    )
                """)
            with engine.connect() as conn:
                conn.execute(create_log_sql)
                conn.commit()
            logger.info(f"Tabla {log_table_name} creada exitosamente")
        except Exception as e:
            logger.error(f"Error creando tabla {log_table_name}: {e}")


# Caché para modelos dinámicos para no recrearlos en cada llamada
dynamic_model_cache = {}


def get_dynamic_models(date_suffix: str):
    """
    Devuelve modelos SQLAlchemy dinámicos para un sufijo de fecha dado.
    Permite operar con tablas user_YYYYMMDD y log_YYYYMMDD del día deseado.

    Usa cache interna para evitar recrear clases repetidamente.
    """
    if date_suffix in dynamic_model_cache:
        return dynamic_model_cache[date_suffix]

    class UserDynamic(Base):
        __tablename__ = f'user_{date_suffix}'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        username = Column(String(255), nullable=False)
        ip = Column(String(15), nullable=False)
        created_at = Column(DateTime, default=datetime.datetime.now)

    class LogDynamic(Base):
        __tablename__ = f'log_{date_suffix}'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer, nullable=False)
        url = Column(Text, nullable=False)
        response = Column(Integer)
        request_count = Column(Integer, default=1)
        data_transmitted = Column(BigInteger, default=0)
        created_at = Column(DateTime, default=datetime.datetime.now)

    dynamic_model_cache[date_suffix] = (UserDynamic, LogDynamic)
    return dynamic_model_cache[date_suffix]
