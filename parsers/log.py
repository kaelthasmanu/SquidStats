import os
import sys
import re
from pathlib import Path
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
import logging
import time

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

# Importación de componentes de la base de datos
from database.database import Base, get_session, User, Log, LogMetadata, get_engine

# Configuración avanzada de logging
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
        self._create_tables_if_not_exist()

    def _create_tables_if_not_exist(self):
        """Crea tablas si no existen usando metadatos de SQLAlchemy"""
        try:
            logger.info("Verificando/creando tablas con Base.metadata.create_all")
            Base.metadata.create_all(self.engine, checkfirst=True)
        except SQLAlchemyError as e:
            logger.error(f"Error creando tablas: {e}")
            raise
        except Exception as e:
            logger.critical(f"Error crítico creando tablas: {e}")
            raise

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
    """
    Parsea líneas de log de Squid usando regex para manejar espacios en URLs.
    Formato esperado: timestamp elapsed host/ip code bytes method URL ...
    """
    # Expresión regular mejorada para manejar espacios en URLs
    pattern = r'(\d+\.\d+)\s+(\d+)\s+(\S+)\s+(?:\S+\s+){2}(\S+)\s+(\d{3})\s+(\d+)\s+(\S+)\s+(\S+://[^\s]+)'
    match = re.match(pattern, line)
    
    if not match:
        return None
        
    # Extraer componentes
    timestamp, elapsed, ip, username, status, size, method, url = match.groups()
    
    # Filtrar TCP_DENIED y métodos no GET
    if "TCP_DENIED" in status or method != "GET":
        return None
    
    return {
        'ip': ip,
        'username': username,
        'url': url,
        'response': int(status),
        'data_transmitted': int(size)
    }

def process_logs(log_file):
    """Procesa el archivo de logs y almacena datos en la base de datos"""
    logger.info(f"Iniciando procesamiento de: {log_file}")

    if not os.path.exists(log_file):
        logger.error(f"Archivo no encontrado: {log_file}")
        return

    try:
        current_inode = get_file_inode(log_file)
        file_size = os.path.getsize(log_file)
        logger.info(f"Tamaño: {file_size} bytes, Inodo: {current_inode}")

        with DatabaseManager() as session:
            # Obtener o crear metadatos
            metadata = session.query(LogMetadata).first()
            last_position = metadata.last_position if metadata else 0
            
            # Detectar rotación o truncamiento
            if metadata:
                if metadata.last_inode != current_inode:
                    logger.info(f"Rotación detectada (inodo: {metadata.last_inode} -> {current_inode})")
                    last_position = 0
                elif file_size < last_position:
                    logger.warning(f"Archivo truncado (tamaño: {file_size} < posición: {last_position})")
                    last_position = 0

            logger.info(f"Leyendo desde posición: {last_position}")

            # Configuración de procesamiento por lotes
            BATCH_SIZE = 500
            MAX_RETRIES = 3
            user_cache = {}
            logs_to_insert = []
            new_users_to_insert = []
            processed_lines = 0
            inserted_logs = 0
            inserted_users = 0
            start_time = time.time()

            def commit_batch():
                """Inserta usuarios y logs en lotes con manejo de errores"""
                nonlocal inserted_logs, inserted_users
                retry_count = 0
                
                while retry_count < MAX_RETRIES:
                    try:
                        # Insertar nuevos usuarios
                        if new_users_to_insert:
                            session.bulk_save_objects(new_users_to_insert)
                            session.flush()  # Asigna IDs
                            
                            # Actualizar caché con nuevos IDs
                            for user in new_users_to_insert:
                                user_cache[(user.username, user.ip)] = user.id
                            
                            inserted_users += len(new_users_to_insert)
                            new_users_to_insert.clear()

                        # Insertar logs
                        if logs_to_insert:
                            session.bulk_insert_mappings(Log, logs_to_insert)
                            inserted_logs += len(logs_to_insert)
                            logs_to_insert.clear()

                        session.commit()
                        logger.debug(f"Batch commit: {inserted_users} usuarios, {inserted_logs} logs")
                        return True
                    
                    except IntegrityError as e:
                        # Manejar usuarios duplicados (insertados concurrentemente)
                        logger.warning(f"Error de integridad (reintento {retry_count+1}): {e}")
                        session.rollback()
                        retry_count += 1
                        
                        # Limpiar caché y reintentar
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
                    
                    # Parsear línea
                    log_data = parse_log_line(line)
                    if not log_data:
                        continue
                    
                    # Identificador único usuario-ip
                    user_key = (log_data['username'], log_data['ip'])
                    
                    # Buscar en caché o preparar para inserción
                    if user_key in user_cache:
                        user_id = user_cache[user_key]
                    else:
                        # Buscar en base de datos
                        existing_user = session.query(User).filter_by(
                            username=log_data['username'], 
                            ip=log_data['ip']
                        ).first()
                        
                        if existing_user:
                            user_id = existing_user.id
                            user_cache[user_key] = user_id
                        else:
                            # Preparar nuevo usuario
                            new_user = User(
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
                        
                        # Obtener ID después del flush
                        user_id = user_cache.get(user_key)
                        if user_id is None:
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
                if new_users_to_insert or logs_to_insert:
                    commit_batch()

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
                logger.info(f"Logs insertados: {inserted_logs}, Usuarios nuevos: {inserted_users}")
                logger.info(f"Tiempo: {elapsed:.2f}s, Velocidad: {processed_lines/elapsed:.2f} lps")

    except Exception as e:
        logger.critical(f"Error crítico en process_logs: {e}", exc_info=True)
        raise

    