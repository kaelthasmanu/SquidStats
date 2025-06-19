import sys
import re
from pathlib import Path
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
import logging
import time
import os

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import (
    get_session,
    LogMetadata,
    get_engine,
    table_exists,
    get_dynamic_table_names,
    get_dynamic_models,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("log_processor.log")],
)
logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, engine=None, session=None):
        self.engine = engine if engine else get_engine()
        self.session = session if session else get_session()

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
                logger.error(f"Rollback por error: {exc_val}")
        except SQLAlchemyError as e:
            logger.error(f"Error durante commit/rollback: {e}")
            self.session.rollback()
        finally:
            self.session.close()


def get_file_inode(filepath):
    try:
        return os.stat(filepath).st_ino
    except FileNotFoundError:
        logger.error(f"Archivo no encontrado: {filepath}")
        raise
    except Exception as e:
        logger.error(f"Error accediendo archivo: {e}")
        raise

def parse_log_line(line):
    if '|' in line and line.count('|') > 10:
        return parse_log_line_pipe_format(line)
    return parse_log_line_space_format(line)

def parse_log_line_pipe_format(line):
    parts = line.strip().split('|')
    if len(parts) < 14:
        return None
    try:
        username = parts[3]
        method = parts[5]
        if username == '-' or "TCP_DENIED" in parts[13] or method not in ("GET", "CONNECT", "POST"):
            return None
        return {
            'ip': parts[1], 'username': username, 'url': parts[6],
            'response': int(parts[8]), 'data_transmitted': int(parts[9])
        }
    except (ValueError, IndexError) as e:
        logger.warning(f"Error parseando línea pipe: {line.strip()} - {e}")
        return None

def parse_log_line_space_format(line):
    try:
        parts = line.split()
        if len(parts) < 10 or parts[7] == '-' or "TCP_DENIED" in line:
            return None
        return {
            'ip': parts[2], 'username': parts[7], 'url': parts[6],
            'response': int(parts[8]), 'data_transmitted': int(parts[4])
        }
    except (IndexError, ValueError) as e:
        logger.warning(f"Error parseando línea space: {line.strip()} - {e}")
        return None


def process_logs(log_file):
    if not os.path.exists(log_file):
        logger.error(f"Archivo de log no encontrado: {log_file}")
        return

    engine = get_engine()
    user_table_name, log_table_name = get_dynamic_table_names()
    if not table_exists(engine, user_table_name) or not table_exists(engine, log_table_name):
        logger.warning("Tablas del día no encontradas, serán creadas por el gestor de sesión.")

    try:
        current_inode = get_file_inode(log_file)
        file_size = os.path.getsize(log_file)

        with DatabaseManager(engine=engine) as session:
            date_suffix = datetime.now().strftime("%Y%m%d")
            User, Log = get_dynamic_models(date_suffix)
            if not User or not Log:
                logger.error(f"No se pudieron cargar los modelos para la fecha {date_suffix}. Abortando.")
                return

            metadata = session.query(LogMetadata).first()
            last_position = 0
            if metadata:
                last_position = metadata.last_position
                if metadata.last_inode != current_inode:
                    logger.info(f"Rotación de log detectada. Reiniciando posición.")
                    last_position = 0
                elif file_size < last_position:
                    logger.warning(f"Archivo de log truncado. Reiniciando posición.")
                    last_position = 0
            
            logger.info(f"Procesando '{log_file}' desde la posición {last_position}.")

            user_cache = {}
            logs_to_insert = []
            
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                f.seek(last_position)
                current_position = last_position
                
                for line in f:
                    current_position += len(line.encode("utf-8"))
                    log_data = parse_log_line(line)
                    if not log_data:
                        continue

                    user_key = (log_data["username"], log_data["ip"])
                    user_id = user_cache.get(user_key)

                    if not user_id:
                        existing_user = session.query(User).filter_by(
                            username=log_data["username"], ip=log_data["ip"]
                        ).first()

                        if existing_user:
                            user_id = existing_user.id
                        else:
                            new_user = User(username=log_data["username"], ip=log_data["ip"])
                            session.add(new_user)
                            session.flush()
                            user_id = new_user.id
                        
                        user_cache[user_key] = user_id
                    
                    logs_to_insert.append({
                        "user_id": user_id,
                        "url": log_data["url"],
                        "response": log_data["response"],
                        "request_count": 1,
                        "data_transmitted": log_data["data_transmitted"],
                        "created_at": datetime.now(),
                    })

                    if len(logs_to_insert) >= 500:
                        session.bulk_insert_mappings(Log, logs_to_insert)
                        logs_to_insert.clear()
            
            if logs_to_insert:
                session.bulk_insert_mappings(Log, logs_to_insert)

            if not metadata:
                metadata = LogMetadata()
                session.add(metadata)
            
            metadata.last_position = current_position
            metadata.last_inode = current_inode
            session.commit()
            logger.info(f"Procesamiento finalizado. Nueva posición: {current_position}")

    except Exception as e:
        logger.critical(f"Error crítico en el procesamiento de logs: {e}", exc_info=True)