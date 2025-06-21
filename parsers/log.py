import sys
import re
from pathlib import Path
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
import logging
import time
import os

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import Base, get_session, User, Log, LogMetadata, get_engine, table_exists, get_dynamic_table_names, get_dynamic_models, DeniedLog

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('log_processor.log')
    ]
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, engine=None, session=None):
        self.engine = engine if engine else get_engine()
        self.session = session if session else get_session()

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Maneja commit/rollback y cierre de sesión automático"""
        try:
            if exc_type is None:
                self.session.commit()
                logger.info("Commit exitoso")
            else:
                self.session.rollback()
                logger.error(f"Rollback por error: {exc_val}")
        except SQLAlchemyError as e:
            logger.error(f"Error durante commit/rollback: {e}")
            self.session.rollback()
        finally:
            self.session.close()

def get_table_names():
    """Obtiene nombres de tablas con fecha actual"""
    today = datetime.now().strftime("%Y%m%d")
    return f"user_{today}", f"log_{today}", "log_metadata"

def get_file_inode(filepath):
    """Obtiene el inode del archivo para detectar rotaciones"""
    try:
        return os.stat(filepath).st_ino
    except FileNotFoundError:
        logger.error(f"Archivo no encontrado: {filepath}")
        raise
    except Exception as e:
        logger.error(f"Error accediendo archivo: {e}")
        raise

def parse_log_line(line):
    if '|' in line:
        return parse_log_line_pipe_format(line)
    else:
        return parse_log_line_space_format(line)

def parse_log_line_pipe_format(line):
    parts = line.strip().split('|')
    if len(parts) < 14:
        logger.warning(f"Línea ignorada (formato incompleto): {line.strip()}")
        return None
    try:
        timestamp_str = parts[0]
        client_ip = parts[1]
        if parts[3] == '-':
            return None  # Ignorar líneas con username "-"
        username = parts[3]
        method = parts[5]
        url = parts[6]
        status_code = int(parts[8])
        bytes_sent = int(parts[9])
        squid_status = parts[13]
        is_denied = "TCP_DENIED" in squid_status
        return {
            'ip': client_ip,
            'username': username,
            'url': url,
            'response': status_code,
            'data_transmitted': bytes_sent,
            'method': method,
            'status': squid_status,
            'is_denied': is_denied
        }
    except Exception as e:
        logger.error(f"Error parseando línea con formato pipe: {line.strip()} - {e}")
        return None

def parse_log_line_space_format(line):
    """
    Parsea línea con formato delimitado por espacios (formato estándar de Squid)
    """
    try:
        parts = line.split(" ")
        if len(parts) < 11:
            logger.warning(f"Línea ignorada (formato incompleto): {line.strip()}")
            return None
        if parts[3] == "-":
            return None
        method = parts[5] if len(parts) > 5 else ""
        squid_status = parts[6] if len(parts) > 6 else ""
        is_denied = "TCP_DENIED" in line
        ip = parts[1]
        username = parts[3]
        url = parts[7]
        response = parts[9]
        data = parts[10]
        return {
            'ip': ip,
            'username': username,
            'url': url,
            'response': int(response) if response.isdigit() else 0,
            'data_transmitted': int(data) if data.isdigit() else 0,
            'method': method,
            'status': squid_status,
            'is_denied': is_denied
        }
    except (IndexError, ValueError) as e:
        logger.error(f"Error parseando línea con formato espacios: {line.strip()} - {e}")
        return None

def detect_log_format(log_file, sample_lines=10):
    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            pipe_count = 0
            space_count = 0
            
            for i, line in enumerate(f):
                if i >= sample_lines:
                    break
                    
                if '|' in line and line.count('|') > 5:  # Formato pipe típicamente tiene muchos |
                    pipe_count += 1
                elif len(line.split()) > 10:  # Formato space típicamente tiene muchos campos
                    space_count += 1
            
            format_detected = 'pipe' if pipe_count > space_count else 'space'
            logger.info(f"Formato detectado: {format_detected} (pipe: {pipe_count}, space: {space_count})")
            return format_detected
            
    except Exception as e:
        logger.warning(f"Error detectando formato, usando detección por línea: {e}")
        return 'auto'  # Fallback a detección automática por línea

def process_logs(log_file):
    log_format = detect_log_format(log_file)
    if not os.path.exists(log_file):
        logger.error(f"Archivo no encontrado: {log_file}")
        return
    engine = get_engine()
    user_table, log_table = get_dynamic_table_names()
    if not (table_exists(engine, user_table) and table_exists(engine, log_table)):
        logger.warning(f"Tablas dinámicas para la fecha actual no existen: {user_table}, {log_table}. Se crearán las tablas y se procesará el log.")
        try:
            Base.metadata.create_all(engine, checkfirst=True)
            logger.info("Tablas creadas exitosamente.")
        except Exception as e:
            logger.error(f"Error al crear las tablas dinámicas: {e}")
            return
    try:
        current_inode = get_file_inode(log_file)
        file_size = os.path.getsize(log_file)
        date_suffix = datetime.now().strftime("%Y%m%d")
        DynamicUser, DynamicLog = get_dynamic_models(date_suffix)
        with DatabaseManager() as session:
            metadata = session.query(LogMetadata).first()
            last_position = metadata.last_position if metadata else 0
            if metadata:
                if metadata.last_inode != current_inode:
                    logger.info(f"Rotación detectada (inodo: {metadata.last_inode} -> {current_inode})")
                    last_position = 0
                elif file_size < last_position:
                    logger.warning(f"Archivo truncado (tamaño: {file_size} < posición: {last_position})")
                    last_position = 0
            logger.info(f"Leyendo desde posición: {last_position}")
            BATCH_SIZE = 500
            MAX_RETRIES = 3
            user_cache = {}
            logs_to_insert = []
            new_users_to_insert = []
            denied_to_insert = []
            processed_lines = 0
            inserted_logs = 0
            inserted_users = 0
            inserted_denied = 0
            start_time = time.time()
            def commit_batch():
                nonlocal inserted_logs, inserted_users, inserted_denied
                retry_count = 0
                user_table, log_table = get_dynamic_table_names()
                logger.info(f"Guardando usuarios en la tabla: {user_table}, logs en la tabla: {log_table}, denied en denied_logs")
                while retry_count < MAX_RETRIES:
                    try:
                        if new_users_to_insert:
                            session.bulk_save_objects(new_users_to_insert)
                            session.flush()
                            for user in new_users_to_insert:
                                user_cache[(user.username, user.ip)] = user.id
                            inserted_users += len(new_users_to_insert)
                            new_users_to_insert.clear()
                        if logs_to_insert:
                            session.bulk_insert_mappings(DynamicLog, logs_to_insert)
                            inserted_logs += len(logs_to_insert)
                            logs_to_insert.clear()
                        if denied_to_insert:
                            session.bulk_save_objects(denied_to_insert)
                            inserted_denied += len(denied_to_insert)
                            denied_to_insert.clear()
                        session.commit()
                        logger.debug(f"Batch commit: {inserted_users} usuarios, {inserted_logs} logs, {inserted_denied} denied")
                        return True
                    except IntegrityError as e:
                        logger.warning(f"Error de integridad (reintento {retry_count+1}): {e}")
                        session.rollback()
                        retry_count += 1
                        if new_users_to_insert:
                            for user in new_users_to_insert:
                                key = (user.username, user.ip)
                                if key in user_cache:
                                    del user_cache[key]
                    except SQLAlchemyError as e:
                        logger.error(f"Error de base de datos: {e}")
                        session.rollback()
                        break
                return False
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(last_position)
                current_position = last_position
                for line in f:
                    processed_lines += 1
                    current_position += len(line.encode('utf-8'))
                    log_data = parse_log_line(line)
                    if not log_data:
                        continue
                    if log_data.get('is_denied'):
                        denied_entry = DeniedLog(
                            username=log_data['username'],
                            ip=log_data['ip'],
                            url=log_data['url'],
                            method=log_data.get('method', ''),
                            status=log_data.get('status', ''),
                            response=log_data.get('response'),
                            data_transmitted=log_data.get('data_transmitted', 0),
                            created_at=datetime.now()
                        )
                        logger.info(f"Enviando a denied_logs: {denied_entry.__dict__}")
                        denied_to_insert.append(denied_entry)
                        if len(denied_to_insert) >= BATCH_SIZE:
                            if commit_batch():
                                logger.info(f"Batch denied_logs insertado exitosamente. Registros: {BATCH_SIZE}")
                            else:
                                logger.error("Error en commit batch denied. Continuando con siguiente lote")
                        continue
                    # Identificador único usuario-ip
                    user_key = (log_data['username'], log_data['ip'])
                    
                    # Buscar en caché o preparar para inserción
                    if user_key in user_cache:
                        user_id = user_cache[user_key]
                    else:
                        # Buscar en base de datos usando modelo dinámico
                        existing_user = session.query(DynamicUser).filter_by(
                            username=log_data['username'],
                            ip=log_data['ip']
                        ).first()
                        if existing_user:
                            user_id = existing_user.id
                            user_cache[user_key] = user_id
                        else:
                            # Preparar nuevo usuario con modelo dinámico
                            new_user = DynamicUser(
                                username=log_data['username'],
                                ip=log_data['ip']
                            )
                            new_users_to_insert.append(new_user)
                            user_cache[user_key] = None  # Marcador temporal
                            user_id = None

                    # Si el usuario es nuevo y no tiene ID aún
                    if user_id is None:
                        if not commit_batch():
                            logger.error("Error crítico en commit batch. Abortando lote")
                            continue

                        # 🔁 FIX: reconsultar desde la base de datos usando modelo dinámico
                        existing_user = session.query(DynamicUser).filter_by(
                            username=log_data['username'],
                            ip=log_data['ip']
                        ).first()

                        if existing_user:
                            user_id = existing_user.id
                            user_cache[user_key] = user_id
                        else:
                            logger.error(f"Usuario no creado: {user_key}. Saltando línea")
                            continue

                    # Preparar log para inserción
                    logs_to_insert.append({
                        'user_id': user_id,
                        'url': log_data['url'],
                        'response': log_data['response'],
                        'request_count': 1,
                        'data_transmitted': log_data['data_transmitted'],
                        'timestamp': datetime.now()
                    })

                    # Comitar por lotes
                    if len(logs_to_insert) >= BATCH_SIZE:
                        if not commit_batch():
                            logger.error("Error en commit batch. Continuando con siguiente lote")
            
            # Comitar último lote
            if new_users_to_insert or logs_to_insert or denied_to_insert:
                if commit_batch():
                    if denied_to_insert:
                        logger.info(f"Batch denied_logs insertado exitosamente. Registros: {len(denied_to_insert)}")
                # ...existing code...
                # Actualizar metadatos de posición
                if not metadata:
                    metadata = LogMetadata()
                    session.add(metadata)
                
                metadata.last_position = current_position
                metadata.last_inode = current_inode
                metadata.last_processed = datetime.now()
                session.commit()

                # Estadísticas finales
                elapsed = time.time() - start_time
                logger.info(f"Procesamiento completado. Líneas: {processed_lines}")
                logger.info(f"Logs insertados: {inserted_logs}, Usuarios nuevos: {inserted_users}, Denied: {inserted_denied}")
                logger.info(f"Tiempo: {elapsed:.2f}s, Velocidad: {processed_lines/elapsed:.2f} lps")

    except Exception as e:
        logger.critical(f"Error crítico en process_logs: {e}", exc_info=True)
        raise

