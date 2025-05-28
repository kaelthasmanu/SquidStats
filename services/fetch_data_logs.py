from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from sqlalchemy import inspect, text, create_engine
from sqlalchemy.ext.automap import automap_base
import sys
from pathlib import Path
from datetime import datetime, date
import logging

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import get_session, get_engine

def get_dynamic_model(db: Session, table_name: str, date_suffix: str):
    """
    Crea un modelo dinámico para una tabla específica con sufijo de fecha
    
    Args:
        db: Sesión de base de datos
        table_name: Nombre base de la tabla ('user' o 'log')
        date_suffix: Sufijo de fecha en formato YYYYMMDD
    
    Returns:
        Modelo SQLAlchemy para la tabla dinámica
    """
    full_table_name = f"{table_name}_{date_suffix}"
    
    # Verificar si la tabla existe
    inspector = inspect(db.get_bind())
    if not inspector.has_table(full_table_name):
        logger.warning(f"Tabla {full_table_name} no encontrada")
        return None
    
    # Crear modelo dinámico usando automap
    engine = db.get_bind()
    Base = automap_base()
    Base.prepare(autoload_with=engine)
    
    try:
        return Base.classes[full_table_name]
    except KeyError:
        logger.error(f"Tabla {full_table_name} no mapeada por automap")
        return None

def get_users_with_logs_optimized(db: Session) -> List[Dict[str, Any]]:
    """
    Obtiene usuarios y sus logs para la fecha actual
    
    Args:
        db: Sesión de base de datos
    
    Returns:
        Lista de diccionarios con datos de usuarios y logs
    """
    try:
        # Obtener modelos para el día actual
        date_suffix = datetime.now().strftime("%Y%m%d")
        UserModel = get_dynamic_model(db, "user", date_suffix)
        LogModel = get_dynamic_model(db, "log", date_suffix)
        
        if not UserModel or not LogModel:
            logger.error("Tablas dinámicas no disponibles para la fecha actual")
            return []
        
        # Consulta de usuarios
        users = db.query(UserModel).filter(UserModel.username != "-").all()
        
        users_data = []
        for user in users:
            # Consulta de logs para el usuario
            logs = db.query(LogModel).filter(LogModel.user_id == user.id).all()
            
            total_requests = sum(log.request_count for log in logs)
            total_data = sum(log.data_transmitted for log in logs)
            
            user_dict = {
                "user_id": user.id,
                "username": user.username,
                "ip": user.ip,
                "logs": [{
                    "url": log.url,
                    "response": log.response,
                    "request_count": log.request_count,
                    "data_transmitted": log.data_transmitted
                } for log in logs],
                "total_requests": total_requests,
                "total_data": total_data
            }
            
            users_data.append(user_dict)
        
        return users_data
    except Exception as e:
        logger.error(f"Error en get_users_with_logs_optimized: {str(e)}", exc_info=True)
        return []
    finally:
        db.close()

def get_users_with_logs_by_date(db: Session, date_suffix: str) -> List[Dict[str, Any]]:
    """
    Obtiene usuarios y sus logs para una fecha específica
    
    Args:
        db: Sesión de base de datos
        date_suffix: Sufijo de fecha en formato YYYYMMDD
    
    Returns:
        Lista de diccionarios con datos de usuarios y logs
    """
    try:
        # Obtener modelos para la fecha solicitada
        UserModel = get_dynamic_model(db, "user", date_suffix)
        LogModel = get_dynamic_model(db, "log", date_suffix)
        
        if not UserModel or not LogModel:
            logger.warning(f"No se encontraron tablas para la fecha {date_suffix}")
            return []
        
        # Consulta de usuarios
        users = db.query(UserModel).filter(UserModel.username != "-").all()
        
        users_data = []
        for user in users:
            # Consulta de logs para el usuario
            logs = db.query(LogModel).filter(LogModel.user_id == user.id).all()
            
            total_requests = sum(log.request_count for log in logs)
            total_data = sum(log.data_transmitted for log in logs)
            
            user_dict = {
                "user_id": user.id,
                "username": user.username,
                "ip": user.ip,
                "logs": [{
                    "url": log.url,
                    "response": log.response,
                    "request_count": log.request_count,
                    "data_transmitted": log.data_transmitted
                } for log in logs],
                "total_requests": total_requests,
                "total_data": total_data
            }
            
            users_data.append(user_dict)
        
        return users_data
    except Exception as e:
        logger.error(f"Error en get_users_with_logs_by_date: {str(e)}", exc_info=True)
        return []
    finally:
        db.close()

# Función alternativa más eficiente para grandes volúmenes de datos
def get_users_with_logs_optimized_v2(db: Session, date_suffix: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Versión optimizada que usa una sola consulta SQL con JOIN
    
    Args:
        db: Sesión de base de datos
        date_suffix: Sufijo de fecha en formato YYYYMMDD (opcional)
    
    Returns:
        Lista de diccionarios con datos de usuarios y logs
    """
    try:
        # Determinar sufijo de fecha
        if not date_suffix:
            date_suffix = datetime.now().strftime("%Y%m%d")
        
        # Construir nombres de tablas
        user_table = f"user_{date_suffix}"
        log_table = f"log_{date_suffix}"
        
        # Verificar existencia de tablas
        inspector = inspect(db.get_bind())
        if not inspector.has_table(user_table) or not inspector.has_table(log_table):
            logger.warning(f"Tablas no encontradas para {date_suffix}")
            return []
        
        # Consulta SQL optimizada con JOIN
        sql = text(f"""
            SELECT 
                u.id AS user_id,
                u.username,
                u.ip,
                l.url,
                l.response,
                l.request_count,
                l.data_transmitted
            FROM {user_table} u
            LEFT JOIN {log_table} l ON u.id = l.user_id
            WHERE u.username != '-'
        """)
        
        result = db.execute(sql)
        rows = result.fetchall()
        
        # Agrupar resultados por usuario
        users_map = {}
        for row in rows:
            user_id = row.user_id
            
            if user_id not in users_map:
                users_map[user_id] = {
                    "user_id": user_id,
                    "username": row.username,
                    "ip": row.ip,
                    "logs": [],
                    "total_requests": 0,
                    "total_data": 0
                }
            
            # Solo agregar log si hay datos
            if row.url:
                log_entry = {
                    "url": row.url,
                    "response": row.response,
                    "request_count": row.request_count,
                    "data_transmitted": row.data_transmitted
                }
                users_map[user_id]["logs"].append(log_entry)
                users_map[user_id]["total_requests"] += row.request_count
                users_map[user_id]["total_data"] += row.data_transmitted
        
        return list(users_map.values())
    except Exception as e:
        logger.error(f"Error en get_users_with_logs_optimized_v2: {str(e)}", exc_info=True)
        return []
    finally:
        db.close()