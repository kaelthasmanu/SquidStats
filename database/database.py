from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, BigInteger, Text, DateTime, inspect
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.declarative import declared_attr
import datetime, os
import logging

Base = declarative_base()

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DailyBase(Base):
    """Clase base abstracta para tablas diarias"""
    __abstract__ = True
    
    @declared_attr
    def __tablename__(cls):
        """Genera nombres de tabla dinámicos con sufijo de fecha"""
        date_suffix = datetime.date.today().strftime("%Y%m%d")
        return f"{cls.__name__.lower()}_{date_suffix}"

class User(DailyBase):
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    ip = Column(String(15), nullable=False)
    # NOTA: Las relaciones no funcionan bien con tablas dinámicas

class Log(DailyBase):
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    url = Column(Text, nullable=False)
    response = Column(Integer)
    request_count = Column(Integer, default=1)
    data_transmitted = Column(BigInteger, default=0)

class LogMetadata(Base):
    __tablename__ = "log_metadata"
    id = Column(Integer, primary_key=True)
    last_position = Column(BigInteger, default=0)
    last_inode = Column(BigInteger, default=0)

def get_engine():
    """Crea y retorna el motor de base de datos"""
    db_type = os.getenv("DATABASE_TYPE", "MARIADB")
    conn_str = os.getenv("DATABASE_STRING_CONNECTION")
    
    if not conn_str:
        logger.error("DATABASE_STRING_CONNECTION no está definido")
        raise ValueError("Cadena de conexión a BD no configurada")
    
    if db_type == "SQLITE":
        db_dir = os.path.dirname(os.path.abspath(conn_str))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        return create_engine(f"sqlite:///{conn_str}", echo=False)
    
    elif db_type == "MARIADB":
        return create_engine(conn_str, echo=False, pool_pre_ping=True)
    
    logger.error(f"Tipo de base de datos no soportado: {db_type}")
    raise ValueError(f"Tipo de BD no soportado: {db_type}")

def get_session():
    """Crea y retorna una sesión de base de datos"""
    engine = get_engine()
    create_dynamic_tables(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def create_dynamic_tables(engine):
    """Crea las tablas dinámicas si no existen"""
    # Crear tablas base primero
    Base.metadata.create_all(engine, tables=[LogMetadata.__table__])
    
    # Crear tablas dinámicas para el día actual
    date_suffix = datetime.date.today().strftime("%Y%m%d")
    user_table_name = f"user_{date_suffix}"
    log_table_name = f"log_{date_suffix}"
    
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    # Crear tabla de usuarios si no existe
    if user_table_name not in existing_tables:
        logger.info(f"Creando tabla: {user_table_name}")
        User.__table__.create(engine)
    
    # Crear tabla de logs si no existe
    if log_table_name not in existing_tables:
        logger.info(f"Creando tabla: {log_table_name}")
        Log.__table__.create(engine)