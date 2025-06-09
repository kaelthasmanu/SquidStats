from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, BigInteger, Text, DateTime, inspect
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.declarative import declared_attr
import datetime, os, logging, pytz
from sqlalchemy import text

# Configura la zona horaria para Cuba
TIMEZONE = pytz.timezone('America/Havana')

# Base declarativa
Base = declarative_base()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Devuelve sufijo de fecha actual (o del día anterior si estamos entre 00:00 y 00:05)
def get_table_suffix():
    now = datetime.datetime.now(TIMEZONE)
    if now.hour == 0 and now.minute < 5:
        table_date = now - datetime.timedelta(days=1)
        logger.info(f"Ventana de cambio de día. Usando fecha anterior: {table_date.strftime('%Y%m%d')}")
    else:
        table_date = now
    return table_date.strftime("%Y%m%d")

class DailyBase(Base):
    __abstract__ = True

    @declared_attr
    def __tablename__(cls):
        return f"{cls.__name__.lower()}_{get_table_suffix()}"

class User(DailyBase):
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    ip = Column(String(15), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now)

class Log(DailyBase):
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)  # SQLite no soporta FKs automáticas con tablas dinámicas
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
    db_type = os.getenv("DATABASE_TYPE", "MARIADB")
    conn_str = os.getenv("DATABASE_STRING_CONNECTION")

    if not conn_str:
        logger.error("DATABASE_STRING_CONNECTION no está definido")
        raise ValueError("Cadena de conexión a BD no configurada")

    if db_type.upper() == "SQLITE":
        db_dir = os.path.dirname(os.path.abspath(conn_str))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        return create_engine(f"sqlite:///{conn_str}", echo=False, connect_args={"check_same_thread": False})
    
    elif db_type.upper() == "MARIADB":
        return create_engine(conn_str, echo=False, pool_pre_ping=True)
    
    logger.error(f"Tipo de base de datos no soportado: {db_type}")
    raise ValueError(f"Tipo de BD no soportado: {db_type}")

def get_session():
    engine = get_engine()
    create_dynamic_tables(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def table_exists(engine, table_name):
    with engine.connect() as conn:
        return engine.dialect.has_table(conn, table_name)

def create_dynamic_tables(engine):
    if not table_exists(engine, "log_metadata"):
        LogMetadata.__table__.create(engine)
        logger.info("Tabla de metadatos creada")

    table_suffix = get_table_suffix()
    user_table_name = f"user_{table_suffix}"
    log_table_name = f"log_{table_suffix}"
    db_type = os.getenv("DATABASE_TYPE", "MARIADB").upper()

    if not table_exists(engine, user_table_name):
        logger.info(f"Creando tabla: {user_table_name}")
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
            logger.error(f"Error creando tabla {user_table_name}: {str(e)}")

    if not table_exists(engine, log_table_name):
        logger.info(f"Creando tabla: {log_table_name}")
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
            logger.error(f"Error creando tabla {log_table_name}: {str(e)}")

# Caché de modelos
dynamic_model_cache = {}

def get_dynamic_models(date_suffix: str):
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

    models = (UserDynamic, LogDynamic)
    dynamic_model_cache[date_suffix] = models
    return models
