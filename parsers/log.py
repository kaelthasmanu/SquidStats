import os
import sys
from pathlib import Path
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
import logging
import time

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

# IMPORTANTE: Importar Base además de modelos y engine
from database.database import Base, get_session, User, Log, LogMetadata, get_engine

# Configuración básica de logging para seguimiento
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, engine=None, session=None):
        self.engine = engine if engine else get_engine()
        self.session = session if session else get_session()
        self._create_tables_if_not_exist()

    def _create_tables_if_not_exist(self):
        """Crea todas las tablas definidas en Base si no existen (checkfirst=True)"""
        try:
            logger.info("Creando tablas si no existen con Base.metadata.create_all(checkfirst=True)")
            Base.metadata.create_all(self.engine, checkfirst=True)  # PATCH: crea todas las tablas si no existen
        except SQLAlchemyError as e:
            logger.error(f"Error creando tablas: {e}")
            raise
        except Exception as e:
            logger.critical(f"Error crítico creando tablas: {e}")
            raise

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
        finally:
            self.session.close()

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
    """Parsea una línea de log y extrae campos útiles, ignora líneas inválidas o TCP_DENIED"""
    try:
        parts = line.split()
        if len(parts) < 18:
            return None
        # Filtrar líneas TCP_DENIED
        if "TCP_DENIED" in parts[17]:
            return None
        
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
            'data_transmitted': int(data) if data.isdigit() else 0
        }
    except Exception:
        # Línea inválida o mal formada
        return None

def process_logs(log_file):
    logger.info(f"Procesando logs: {log_file}")

    if not os.path.exists(log_file):
        logger.error(f"No existe archivo: {log_file}")
        return

    try:
        current_inode = get_file_inode(log_file)
        logger.info(f"Inodo actual: {current_inode}")

        with DatabaseManager() as session:
            # Obtener o crear metadatos
            metadata = session.query(LogMetadata).first()
            last_position = metadata.last_position if metadata else 0
            
            # Detectar rotación de logs por cambio de inode
            if metadata and metadata.last_inode != current_inode:
                logger.info(f"Inodo cambió ({metadata.last_inode} -> {current_inode}), reiniciando posición")
                last_position = 0
                metadata.last_inode = current_inode
                metadata.last_position = 0
                session.commit()

            logger.info(f"Leyendo desde posición: {last_position}")

            # Cache local para usuarios para evitar múltiples queries
            user_cache = {}

            # Listas para inserción masiva
            logs_to_insert = []
            new_users_to_insert = []

            batch_size = 500  # tamaño del lote para commit
            processed_lines = 0
            inserted_logs = 0
            inserted_users = 0

            start_time = time.time()

            def commit_batch():
                """Función para insertar usuarios y logs en batch y hacer commit"""
                nonlocal inserted_logs, inserted_users

                if new_users_to_insert:
                    session.bulk_save_objects(new_users_to_insert)
                    session.flush()  # Asignar IDs a usuarios nuevos
                    inserted_users += len(new_users_to_insert)

                    # Actualizar cache con IDs asignados tras flush
                    for usr in new_users_to_insert:
                        user_cache[(usr.username, usr.ip)] = usr.id
                    new_users_to_insert.clear()

                if logs_to_insert:
                    session.bulk_insert_mappings(Log, logs_to_insert)
                    inserted_logs += len(logs_to_insert)
                    logs_to_insert.clear()

                session.commit()
                session.expire_all()  # Limpia caché para evitar uso excesivo de memoria
                logger.info(f"Commit batch: {inserted_users} usuarios nuevos, {inserted_logs} logs insertados")

            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(last_position)  # saltar a la última posición guardada

                for line in f:
                    processed_lines += 1
                    log_data = parse_log_line(line)
                    if not log_data:
                        continue

                    key = (log_data['username'], log_data['ip'])
                    user_id = user_cache.get(key)

                    if user_id is None:
                        # Intentar obtener usuario existente en BD
                        user = session.query(User).filter_by(username=log_data['username'], ip=log_data['ip']).first()
                        if user:
                            user_id = user.id
                            user_cache[key] = user_id
                        else:
                            # Preparar nuevo usuario para inserción masiva
                            new_user = User(username=log_data['username'], ip=log_data['ip'])
                            new_users_to_insert.append(new_user)
                            # No asignar user_id aún porque falta flush
                            user_cache[key] = None
                            user_id = None

                    # Si el usuario es nuevo y aún no tiene ID asignado (pendiente flush)
                    if user_id is None:
                        # Flush para asignar IDs a los usuarios nuevos antes de insertar logs
                        commit_batch()
                        # Después del commit_batch, la cache debe estar actualizada
                        user_id = user_cache.get(key)

                    # Añadir log para inserción masiva
                    logs_to_insert.append({
                        'user_id': user_id,
                        'url': log_data['url'],
                        'response': log_data['response'],
                        'request_count': 1,
                        'data_transmitted': log_data['data_transmitted']
                    })

                    # Commit por lotes para no saturar memoria y DB
                    if len(logs_to_insert) >= batch_size:
                        commit_batch()

                # Commit final para registros restantes
                commit_batch()

                # Actualizar posición de lectura para continuar en siguiente ejecución
                new_position = f.tell()

                # Actualizar metadatos con nueva posición y inode
                if metadata:
                    metadata.last_position = new_position
                    metadata.last_inode = current_inode
                else:
                    metadata = LogMetadata(last_position=new_position, last_inode=current_inode)
                    session.add(metadata)

                session.commit()

                elapsed = time.time() - start_time
                logger.info(f"Procesamiento finalizado. Líneas procesadas: {processed_lines}")
                logger.info(f"Logs insertados: {inserted_logs}, usuarios nuevos: {inserted_users}")
                logger.info(f"Tiempo transcurrido: {elapsed:.2f} segundos")
                logger.info(f"Velocidad: {processed_lines/elapsed if elapsed > 0 else 0:.2f} líneas/segundo")

    except Exception as e:
        logger.critical(f"Error crítico en process_logs: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    process_logs(log_file)
