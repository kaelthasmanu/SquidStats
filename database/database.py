from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, BigInteger
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import datetime, os

Base = declarative_base()

def get_table_names():
    today = datetime.date.today().strftime("%Y%m%d")
    return f"users_{today}", f"logs_{today}", "log_metadata"

class LogMetadata(Base):
    __tablename__ = "log_metadata"
    id = Column(Integer, primary_key=True)
    last_position = Column(BigInteger, default=0)
    last_inode = Column(BigInteger, default=0)

class User(Base):
    __tablename__ = get_table_names()[0]
    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    username = Column(String, unique=True, nullable=False)
    ip = Column(String(255), nullable=False)
    logs = relationship("Log", back_populates="user")

class Log(Base):
    __tablename__ = get_table_names()[1]
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey(f"{get_table_names()[0]}.id"))
    url = Column(String(2048), nullable=False)
    response = Column(Integer)
    request_count = Column(Integer, default=1)
    data_transmitted = Column(BigInteger, default=0)
    user = relationship("User", back_populates="logs")

def get_engine():
    db_path = os.getenv("DATABASE_STRING_CONNECTION")
    if (os.getenv("DATABASE_TYPE") == "SQLITE"):
        db_dir = os.path.dirname(os.path.abspath(db_path))

        try:
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
        except OSError as e:
            print("Error creando directorio para la base de datos", e)
            return

        return create_engine(f"sqlite:///{db_path}logs.db", echo=False)
    if (os.getenv("DATABASE_TYPE") == "MARIADB"):
        return create_engine(f"{db_path}", echo=False)

def get_session():
    engine = get_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()
