from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, BigInteger, Text, DateTime, inspect
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.ext.declarative import declared_attr
import datetime, os
import logging
import pytz
from sqlalchemy import text

# Configura la zona horaria para Cuba
TIMEZONE = pytz.timezone('America/Havana')

# Base declarativa para modelos ORM
Base = declarative_base()

# Configuración de logging para monitoreo
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_table_suffix():
    """
    Genera el sufijo de tabla basado en la fecha actual con manejo de cambio de día.
    Durante los primeros 5 minutos después de medianoche, usa el día anterior.
    """
    now = datetime.datetime.now(TIMEZONE)
    if now.hour == 0 and now.minute < 5:
        table_date = now - datetime.timedelta(days=1)
        logger.info(f"Ventana de cambio de día. Usando fecha anterior: {table_date.strftime('%Y%m%d')}")
    else:
        table_date = now
    return table_date.strftime("%Y%m%d")

class DailyBase(Base):
    """Clase base abstracta para tablas diarias con nombres dinámicos"""
    __abstract__ = True
    
    @declared_attr
    def __tablename__(cls):
        """Genera nombres de tabla con formato: 'nombreclase_AAAAMMDD'"""
        return f"{cls.__name__.lower()}_{get_table_suffix()}"

class User(DailyBase):
    """Modelo ORM para usuarios (tabla diaria)"""
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)  # Nombre de usuario
    ip = Column(String(15), nullable=False)         # Dirección IP
    created_at = Column(DateTime, default=datetime.datetime.now)  # Fecha de creación
    
    # IMPORTANTE: Eliminamos la relación para evitar conflictos
    # Las consultas usarán joins explícitos en lugar de relaciones automáticas

class Log(DailyBase):
    """Modelo ORM para registros de acceso (tabla diaria)"""
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey(f'user_{get_table_suffix()}.id'))  # FK a usuarios
    url = Column(Text, nullable=False)              # URL accedida
    response = Column(Integer)                      # Código de respuesta HTTP
    request_count = Column(Integer, default=1)      # Contador de solicitudes
    data_transmitted = Column(BigInteger, default=0)  # Bytes transmitidos
    created_at = Column(DateTime, default=datetime.datetime.now)  # Fecha de registro
    
    # IMPORTANTE: Eliminamos la relación para evitar conflictos
    # Las consultas usarán joins explícitos en lugar de relaciones automáticas

class LogMetadata(Base):
    """Tabla permanente para almacenar metadatos del parser"""
    __tablename__ = "log_metadata"
    id = Column(Integer, primary_key=True)
    last_position = Column(BigInteger, default=0)  # Última posición leída en el log
    last_inode = Column(BigInteger, default=0)     # Inode del último archivo procesado

def get_engine():
    """Crea y retorna el motor de base de datos según variables de entorno"""
    db_type = os.getenv("DATABASE_TYPE", "MARIADB")
    conn_str = os.getenv("DATABASE_STRING_CONNECTION")
    
    if not conn_str:
        logger.error("DATABASE_STRING_CONNECTION no está definido")
        raise ValueError("Cadena de conexión a BD no configurada")
    
    # Configuración para SQLite
    if db_type == "SQLITE":
        db_dir = os.path.dirname(os.path.abspath(conn_str))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)  # Crea directorio si no existe
        return create_engine(f"sqlite:///{conn_str}", echo=False)
    
    # Configuración para MariaDB/MySQL
    elif db_type == "MARIADB":
        return create_engine(conn_str, echo=False, pool_pre_ping=True)
    
    logger.error(f"Tipo de base de datos no soportado: {db_type}")
    raise ValueError(f"Tipo de BD no soportado: {db_type}")

def get_session():
    """Crea y retorna una sesión de base de datos con tablas actualizadas"""
    engine = get_engine()
    create_dynamic_tables(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def table_exists(engine, table_name):
    """Verifica si una tabla existe en la base de datos"""
    with engine.connect() as conn:
        return engine.dialect.has_table(conn, table_name)

def create_dynamic_tables(engine):
    """
    Crea las tablas diarias si no existen.
    Se ejecuta automáticamente al obtener una nueva sesión.
    """
    # Crear tabla de metadatos si no existe (tabla permanente)
    if not table_exists(engine, "log_metadata"):
        LogMetadata.__table__.create(engine)
        logger.info("Tabla de metadatos creada")
    
    # Obtener sufijo del día actual para nombres de tablas
    table_suffix = get_table_suffix()
    user_table_name = f"user_{table_suffix}"
    log_table_name = f"log_{table_suffix}"
    
    # Crear tabla de usuarios si no existe
    if not table_exists(engine, user_table_name):
        logger.info(f"Creando tabla: {user_table_name}")
        try:
            # Usamos SQL nativo para mayor control sobre la creación
            create_user_table_sql = text(f"""
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
                    INDEX idx_created_at (created_at),
                    INDEX idx_response (response),
                    FOREIGN KEY (user_id) REFERENCES `{user_table_name}`(id)
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

# Caché global para almacenar modelos dinámicos ya creados
dynamic_model_cache = {}

def get_dynamic_models(date_suffix: str):
    """
    Retorna modelos ORM para tablas diarias específicas con caché.
    Sin relaciones para evitar conflictos - usaremos joins explícitos.
    
    Args:
        date_suffix: Sufijo de fecha en formato AAAAMMDD
        
    Returns:
        Tupla (UserDynamic, LogDynamic) - Modelos ORM para las tablas solicitadas
    """
    # Retornar modelos desde caché si existen
    if date_suffix in dynamic_model_cache:
        return dynamic_model_cache[date_suffix]
    
    # Crear nuevos modelos dinámicos SIN relaciones
    class UserDynamic(Base):
        """Modelo dinámico para tabla de usuarios de una fecha específica"""
        __tablename__ = f'user_{date_suffix}'
        __table_args__ = {'extend_existing': True}
        
        id = Column(Integer, primary_key=True)
        username = Column(String(255), nullable=False)
        ip = Column(String(15), nullable=False)
        created_at = Column(DateTime, default=datetime.datetime.now)
    
    class LogDynamic(Base):
        """Modelo dinámico para tabla de logs de una fecha específica"""
        __tablename__ = f'log_{date_suffix}'
        __table_args__ = {'extend_existing': True}
        
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer, ForeignKey(f'user_{date_suffix}.id'))
        url = Column(Text, nullable=False)
        response = Column(Integer)
        request_count = Column(Integer, default=1)
        data_transmitted = Column(BigInteger, default=0)
        created_at = Column(DateTime, default=datetime.datetime.now)
    
    # Almacenar modelos en caché y retornarlos
    models = (UserDynamic, LogDynamic)
    dynamic_model_cache[date_suffix] = models
    return models