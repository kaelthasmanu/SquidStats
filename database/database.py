import os
import logging
from sqlalchemy import (
    create_engine, Column, Integer, String, BigInteger, Text, DateTime,inspect
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.declarative import declared_attr
from typing import Tuple, Dict, Any
from dotenv import load_dotenv
from datetime import datetime, date

# Cargar variables de entorno desde .env
load_dotenv()

# Configurar logging para seguimiento
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

Base = declarative_base()
_engine = None
_Session = None
dynamic_model_cache: Dict[str, Any] = {}

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
    ip = Column(String(15), nullable=False)
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
    ip = Column(String(15), nullable=False)
    url = Column(Text, nullable=False)
    method = Column(String(16), nullable=False)
    status = Column(String(64), nullable=False)
    response = Column(Integer, nullable=True)
    data_transmitted = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.now)

class SystemMetrics(Base):
    __tablename__ = "system_metrics"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    cpu_usage = Column(String(10), nullable=False)  # Ejemplo: "25.5%"
    ram_usage_bytes = Column(BigInteger, nullable=False)
    swap_usage_bytes = Column(BigInteger, nullable=False)
    net_sent_bytes_sec = Column(BigInteger, nullable=False)
    net_recv_bytes_sec = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

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
        if conn_str.startswith("mysql://") or conn_str.startswith("mariadb://") or conn_str.startswith("mysql+pymysql://"):
            return conn_str
        raise ValueError("Para MySQL/MariaDB, especifique el string de conexión completo en DATABASE_STRING_CONNECTION")
    else:
        raise ValueError(f"Tipo de base de datos no soportado: {db_type}")

def get_engine():
    global _engine
    if _engine is not None:
        return _engine
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
    """Crea las tablas principales y diarias si no existen."""
    LogMetadata.__table__.create(engine, checkfirst=True)
    DeniedLog.__table__.create(engine, checkfirst=True)
    SystemMetrics.__table__.create(engine, checkfirst=True)  # Crear tabla de métricas del sistema
    
    # Si no se provee un sufijo, se usan las tablas del día actual.
    user_table_name, log_table_name = get_dynamic_table_names(date_suffix)
    
    # Se genera un logger específico para la fecha, para evitar mensajes duplicados.
    creation_logger = logging.getLogger(f"TableCreation_{date_suffix or 'today'}")
    creation_logger.propagate = False # Evita que el log suba al logger raíz
    if not creation_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        creation_logger.addHandler(handler)

    if not table_exists(engine, user_table_name) or not table_exists(engine, log_table_name):
        creation_logger.info(f"Creando tablas dinámicas para la fecha del sufijo '{date_suffix}': {user_table_name}, {log_table_name}")
        DynamicBase = declarative_base()

        class DynamicUser(DynamicBase):
            __tablename__ = user_table_name
            id = Column(Integer, primary_key=True)
            username = Column(String(255), nullable=False)
            ip = Column(String(15), nullable=False)
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

def get_dynamic_table_names(date_suffix: str = None) -> Tuple[str, str]:
    """Devuelve los nombres de las tablas de usuario y log para un sufijo de fecha dado."""
    if date_suffix is None:
        date_suffix = get_table_suffix()
    return f"user_{date_suffix}", f"log_{date_suffix}"

def get_dynamic_models(date_suffix: str):
    """Devuelve modelos dinámicos de usuario y log para el sufijo de fecha dado."""
    cache_key = f"user_log_{date_suffix}"
    if cache_key in dynamic_model_cache:
        return dynamic_model_cache[cache_key]
        
    engine = get_engine()
    user_table_name, log_table_name = get_dynamic_table_names(date_suffix)
    
    if not table_exists(engine, user_table_name) or not table_exists(engine, log_table_name):
        logger.warning(f"Las tablas de usuario/log para el sufijo '{date_suffix}' no existen. Intentando recrearlas...")
        create_dynamic_tables(engine, date_suffix=date_suffix)
        if not table_exists(engine, user_table_name) or not table_exists(engine, log_table_name):
            logger.error(f"No se pudieron crear o encontrar las tablas de usuario/log para el sufijo '{date_suffix}'.")
            return None, None

    DynamicBase = declarative_base()

    class DynamicUser(DynamicBase):
        __tablename__ = user_table_name
        id = Column(Integer, primary_key=True, autoincrement=True)
        username = Column(String(255), nullable=False)
        ip = Column(String(15), nullable=False)
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
