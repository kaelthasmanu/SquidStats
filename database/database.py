from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, BigInteger, Text, DateTime, inspect
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.declarative import declared_attr
import datetime, os
import logging
import pytz  # Importar pytz para manejo de zona horaria
from sqlalchemy import text  # Importación necesaria para ejecutar SQL

# Configura la zona horaria adecuada
TIMEZONE = pytz.timezone('America/Havana')  # Ajusta según tu ubicación

Base = declarative_base()

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_table_suffix():
    """Obtiene el sufijo de tabla con manejo de cambio de día"""
    now = datetime.datetime.now(TIMEZONE)
    
    # Durante los primeros 5 minutos después de medianoche, usar el día anterior
    if now.hour == 0 and now.minute < 5:
        table_date = now - datetime.timedelta(days=1)
        logger.info(f"Ventana de cambio de día. Usando fecha anterior: {table_date.strftime('%Y%m%d')}")
    else:
        table_date = now
        
    return table_date.strftime("%Y%m%d")

class DailyBase(Base):
    """Clase base abstracta para tablas diarias"""
    __abstract__ = True
    
    @declared_attr
    def __tablename__(cls):
        """Genera nombres de tabla dinámicos con sufijo de fecha"""
        return f"{cls.__name__.lower()}_{get_table_suffix()}"

class User(DailyBase):
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    ip = Column(String(15), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now)

class Log(DailyBase):
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    url = Column(Text, nullable=False)
    response = Column(Integer)
    request_count = Column(Integer, default=1)
    data_transmitted = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)

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

def table_exists(engine, table_name):
    """Verifica si una tabla existe"""
    with engine.connect() as conn:
        return engine.dialect.has_table(conn, table_name)

def create_dynamic_tables(engine):
    """Crea las tablas dinámicas si no existen"""
    # Crear tablas base primero
    if not table_exists(engine, "log_metadata"):
        LogMetadata.__table__.create(engine)
        logger.info("Tabla de metadatos creada")
    
    # Obtener el sufijo para las tablas del día
    table_suffix = get_table_suffix()
    user_table_name = f"user_{table_suffix}"
    log_table_name = f"log_{table_suffix}"
    
    # Crear tabla de usuarios si no existe
    if not table_exists(engine, user_table_name):
        logger.info(f"Creando tabla: {user_table_name}")
        try:
            # Usar text() para crear un objeto ejecutable
            create_user_table_sql = text(f"""
                CREATE TABLE IF NOT EXISTS `{user_table_name}` (
                    id INTEGER NOT NULL AUTO_INCREMENT,
                    username VARCHAR(255) NOT NULL,
                    ip VARCHAR(15) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id)
                )
            """)
            with engine.connect() as conn:
                conn.execute(create_user_table_sql)
                conn.commit()
            logger.info(f"Tabla {user_table_name} creada exitosamente")
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Error creando tabla {user_table_name}: {str(e)}")
            else:
                logger.warning(f"Tabla {user_table_name} ya existe")
    
    # Crear tabla de logs si no existe
    if not table_exists(engine, log_table_name):
        logger.info(f"Creando tabla: {log_table_name}")
        try:
            create_log_table_sql = text(f"""
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
                    INDEX idx_created_at (created_at)
                )
            """)
            with engine.connect() as conn:
                conn.execute(create_log_table_sql)
                conn.commit()
            logger.info(f"Tabla {log_table_name} creada exitosamente")
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Error creando tabla {log_table_name}: {str(e)}")
            else:
                logger.warning(f"Tabla {log_table_name} ya existe")