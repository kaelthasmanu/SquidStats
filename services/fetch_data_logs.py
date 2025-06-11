import re
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

# Patrones de validación para nombres de tabla y fechas
TABLE_NAME_PATTERN = re.compile(r'^[a-z_]{3,20}$')
DATE_SUFFIX_PATTERN = re.compile(r'^\d{8}$')

def validate_table_name(table_name: str) -> bool:
    """Valida que el nombre de tabla sea seguro"""
    return bool(TABLE_NAME_PATTERN.match(table_name))

def validate_date_suffix(date_suffix: str) -> bool:
    """Valida que el sufijo de fecha tenga el formato correcto"""
    return bool(DATE_SUFFIX_PATTERN.match(date_suffix))

def sanitize_table_name(name: str) -> str:
    """Elimina caracteres no seguros en nombres de tablas"""
    return re.sub(r'[^a-z0-9_]', '', name.lower())

def get_dynamic_model(db: Session, table_name: str, date_suffix: str):
    """
    Crea un modelo dinámico para una tabla específica con sufijo de fecha
    
    Args:
        db: Sesión de base de datos
        table_name: Nombre base de la tabla ('user' o 'log')
        date_suffix: Sufijo de fecha en formato YYYYMMDD
    
    Returns:
        Modelo SQLAlchemy para la tabla dinámica o None
    """
    # Validar parámetros
    if not validate_table_name(table_name):
        logger.error(f"Nombre de tabla inválido: {table_name}")
        return None
        
    if not validate_date_suffix(date_suffix):
        logger.error(f"Sufijo de fecha inválido: {date_suffix}")
        return None
    
    full_table_name = f"{table_name}_{date_suffix}"
    
    # Verificar si la tabla existe
    try:
        inspector = inspect(db.get_bind())
        if not inspector.has_table(full_table_name):
            logger.warning(f"Tabla {full_table_name} no encontrada")
            return None
        
        # Crear modelo dinámico usando automap
        Base = automap_base()
        Base.prepare(autoload_with=db.get_bind())
        
        return getattr(Base.classes, full_table_name, None)
    except Exception as e:
        logger.error(f"Error obteniendo modelo dinámico: {str(e)}", exc_info=True)
        return None

def get_users_with_logs_optimized(db: Session, date_suffix: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Obtiene usuarios y sus logs para la fecha actual o una fecha específica
    
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
        
        # Validar sufijo de fecha
        if not validate_date_suffix(date_suffix):
            logger.error(f"Sufijo de fecha inválido: {date_suffix}")
            return []
        
        # Obtener modelos dinámicos
        UserModel = get_dynamic_model(db, "user", date_suffix)
        LogModel = get_dynamic_model(db, "log", date_suffix)
        
        if not UserModel or not LogModel:
            logger.error(f"Tablas dinámicas no disponibles para la fecha {date_suffix}")
            return []
        
        # Consulta optimizada con JOIN
        query = db.query(
            UserModel.id.label("user_id"),
            UserModel.username,
            UserModel.ip,
            LogModel.url,
            LogModel.response,
            LogModel.request_count,
            LogModel.data_transmitted
        ).join(
            LogModel, UserModel.id == LogModel.user_id
        ).filter(
            UserModel.username != "-"
        )
        
        # Agrupar resultados por usuario
        users_map = {}
        for row in query:
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
    # Validar sufijo de fecha
    if not validate_date_suffix(date_suffix):
        logger.error(f"Sufijo de fecha inválido: {date_suffix}")
        return []
    
    return get_users_with_logs_optimized(db, date_suffix)

