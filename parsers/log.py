import os
import sys
from pathlib import Path
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import inspect  # Importación crítica añadida
import logging
import time

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import get_session, User, Log, LogMetadata, get_engine

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, engine=None, session=None):
        self.engine = engine if engine is not None else get_engine()
        self.session = session if session is not None else get_session()
        self._create_dynamic_tables()

    def _create_dynamic_tables(self):
        """Crea las tablas dinámicas para el día actual si no existen"""
        try:
            date_suffix = datetime.now().strftime("%Y%m%d")
            user_table_name = f"user_{date_suffix}"
            log_table_name = f"log_{date_suffix}"
            
            # Verificar si las tablas ya existen
            inspector = inspect(self.engine)  # Ahora inspect está definido
            existing_tables = inspector.get_table_names()
            
            if user_table_name not in existing_tables:
                logger.info(f"Creando tabla: {user_table_name}")
                User.__table__.create(self.engine)
            
            if log_table_name not in existing_tables:
                logger.info(f"Creando tabla: {log_table_name}")
                Log.__table__.create(self.engine)
                
            # Crear tabla de metadatos si no existe
            if "log_metadata" not in existing_tables:
                LogMetadata.__table__.create(self.engine)
                
        except SQLAlchemyError as e:
            logger.error(f"Error creando tablas: {str(e)}")
            raise
        except Exception as e:
            logger.critical(f"Error crítico creando tablas: {str(e)}")
            raise

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
                logger.error(f"Rollback debido a error: {exc_val}")
        except SQLAlchemyError as e:
            logger.error(f"Error en commit/rollback: {str(e)}")
        finally:
            self.session.close()

def get_file_inode(filepath):
    try:
        return os.stat(filepath).st_ino
    except FileNotFoundError:
        logger.error(f"Archivo no encontrado: {filepath}")
        raise
    except Exception as e:
        logger.error(f"Error accediendo al archivo: {str(e)}")
        raise

def parse_log_line(line):
    try:
        parts = line.split()
        if len(parts) < 18:
            logger.debug(f"Línea demasiado corta: {line}")
            return None
            
        # Verificar si es una línea que debemos ignorar
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
    except (IndexError, ValueError) as e:
        logger.warning(f"Error parseando línea: {str(e)} - Línea: {line[:50]}...")
        return None
    except Exception as e:
        logger.error(f"Error inesperado parseando línea: {str(e)}")
        return None

def process_logs(log_file):
    logger.info(f"Iniciando procesamiento de logs: {log_file}")
    
    if not os.path.exists(log_file):
        logger.error(f"Archivo de log no encontrado: {log_file}")
        return

    try:
        current_inode = get_file_inode(log_file)
        logger.info(f"Inodo actual del archivo: {current_inode}")

        with DatabaseManager() as session:
            # Obtener o crear metadatos
            metadata = session.query(LogMetadata).first()
            last_position = metadata.last_position if metadata else 0
            
            # Si el inodo cambió (rotación de logs), reiniciar posición
            if metadata and metadata.last_inode != current_inode:
                logger.info(f"Inodo cambiado ({metadata.last_inode} -> {current_inode}). Reiniciando posición.")
                last_position = 0
                metadata.last_inode = current_inode
                metadata.last_position = 0
                session.commit()

            logger.info(f"Leyendo desde posición: {last_position}")
            processed_lines = 0
            batch_size = 100
            batch_count = 0
            start_time = time.time()

            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(last_position)
                
                for line in f:
                    processed_lines += 1
                    log_data = parse_log_line(line)
                    
                    if not log_data:
                        continue
                    
                    try:
                        # Buscar usuario existente
                        user = session.query(User).filter_by(
                            username=log_data['username'],
                            ip=log_data['ip']
                        ).first()
                        
                        # Crear nuevo usuario si no existe
                        if not user:
                            user = User(
                                username=log_data['username'],
                                ip=log_data['ip']
                            )
                            session.add(user)
                            session.flush()  # Obtener ID sin commit
                            logger.debug(f"Nuevo usuario creado: {user.username} ({user.ip})")
                        
                        # Insertar registro de log
                        log_entry = Log(
                            user_id=user.id,
                            url=log_data['url'],
                            response=log_data['response'],
                            request_count=1,
                            data_transmitted=log_data['data_transmitted']
                        )
                        session.add(log_entry)
                        
                        # Commit por lotes para mejor rendimiento
                        batch_count += 1
                        if batch_count >= batch_size:
                            session.commit()
                            batch_count = 0
                            
                    except SQLAlchemyError as e:
                        session.rollback()
                        logger.error(f"Error de base de datos: {str(e)}")
                    except Exception as e:
                        logger.error(f"Error inesperado: {str(e)}")
                
                # Commit final para los registros restantes
                if batch_count > 0:
                    session.commit()
                
                # Actualizar posición
                new_position = f.tell()
                
                # Actualizar o crear metadatos
                if metadata:
                    metadata.last_position = new_position
                    metadata.last_inode = current_inode
                else:
                    metadata = LogMetadata(
                        last_position=new_position,
                        last_inode=current_inode
                    )
                    session.add(metadata)
                
                session.commit()
                
                elapsed = time.time() - start_time
                logger.info(f"Procesamiento completo. Nueva posición: {new_position}")
                logger.info(f"Total líneas procesadas: {processed_lines} en {elapsed:.2f} segundos")
                logger.info(f"Registros/s: {processed_lines/elapsed if elapsed > 0 else 0:.2f}")

    except Exception as e:
        logger.critical(f"Error crítico en process_logs: {str(e)}", exc_info=True)
        raise

# Para ejecución directa de pruebas
if __name__ == "__main__":
    log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    process_logs(log_file)