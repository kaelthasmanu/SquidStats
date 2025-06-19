import re
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from sqlalchemy import func
import sys
from pathlib import Path
from datetime import datetime, date
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

# Se importa el gestor de modelos unificado de database.py
from database.database import get_session, get_dynamic_models

DATE_SUFFIX_PATTERN = re.compile(r'^\d{8}$')

def validate_date_suffix(date_suffix: str) -> bool:
    """Valida que el sufijo de fecha tenga el formato correcto"""
    return bool(DATE_SUFFIX_PATTERN.match(date_suffix))

def get_users_logs(db: Session, date_suffix: Optional[str] = None, page: int = 1, per_page: int = 15) -> Dict[str, Any]:
    """
    Obtiene usuarios y sus logs para la fecha actual o una fecha específica de forma paginada.
    """       
    try:
        if not date_suffix:
            date_suffix = datetime.now().strftime("%Y%m%d")
        
        if not validate_date_suffix(date_suffix):
            logger.error(f"Sufijo de fecha inválido: {date_suffix}")
            return {"users": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0}
        
        # Se usa el gestor de modelos unificado para obtener las clases de tabla correctas
        UserModel, LogModel = get_dynamic_models(date_suffix)
        
        if not UserModel or not LogModel:
            logger.warning(f"Tablas dinámicas no disponibles para la fecha {date_suffix}")
            return {"users": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0}
        
        # Contar total de usuarios distintos para la paginación
        total = db.query(UserModel).filter(UserModel.username != "-").count()
        total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
        
        offset = (page - 1) * per_page
        
        # 1. Obtener solo la página de usuarios que se va a mostrar
        users = db.query(UserModel).filter(UserModel.username != "-").order_by(UserModel.username).offset(offset).limit(per_page).all()
        user_ids = [u.id for u in users]

        # Crear un mapa para ensamblar los datos
        users_map = {u.id: {
            "user_id": u.id, "username": u.username, "ip": u.ip, 
            "logs": [], "total_requests": 0, "total_data": 0
        } for u in users}

        # Si no hay usuarios en esta página, devolver resultado vacío
        if not user_ids:
            return {"users": [], "total": total, "page": page, "per_page": per_page, "total_pages": total_pages}

        # 2. Obtener todos los logs que pertenecen a los usuarios de esta página en una sola consulta
        logs_query = db.query(LogModel).filter(LogModel.user_id.in_(user_ids)).all()

        # 3. Procesar los logs en memoria y asignarlos a cada usuario
        for log in logs_query:
            if log.user_id in users_map:
                log_entry = {
                    "url": log.url,
                    "response": log.response,
                    "request_count": log.request_count,
                    "data_transmitted": log.data_transmitted
                }
                users_map[log.user_id]["logs"].append(log_entry)
                users_map[log.user_id]["total_requests"] += log.request_count
                users_map[log.user_id]["total_data"] += log.data_transmitted
        
        return {
            "users": list(users_map.values()),
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages
        }
    except Exception as e:
        logger.error(f"Error en get_users_logs paginado: {str(e)}", exc_info=True)
        return {"users": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0}
    finally:
        if db:
            db.close()

def get_users_with_logs_by_date(db: Session, date_suffix: str) -> List[Dict[str, Any]]:
    """
    Obtiene usuarios y sus logs para una fecha específica (wrapper para la función paginada)
    """
    # Validar sufijo de fecha
    if not validate_date_suffix(date_suffix):
        logger.error(f"Sufijo de fecha inválido: {date_suffix}")
        return []
    
    # Llama a la función principal sin paginación (o con paginación por defecto muy alta si es necesario)
    return get_users_logs(db, date_suffix, page=1, per_page=10000)["users"]

def get_metrics_for_date(selected_date: date):
    session = get_session()
    date_suffix = selected_date.strftime("%Y%m%d")
    try:
        User, Log = get_dynamic_models(date_suffix)
        if not User or not Log:
             raise ValueError("Modelos no encontrados")
    except Exception:
        # Si no existen tablas para esa fecha, devuelve métricas vacías
        return {
            "total_stats": { "total_users": 0, "total_log_entries": 0, "total_data_transmitted": 0, "total_requests": 0, },
            "top_users_by_activity": [], "top_users_by_data_transferred": [],
            "http_response_distribution_chart": { "labels": [], "data": [], "colors": [] },
            "top_pages": [], "users_per_ip": []
        }

    # Total stats
    total_users = session.query(func.count(User.id)).scalar() or 0
    total_log_entries = session.query(func.count(Log.id)).scalar() or 0
    total_data_transmitted = session.query(func.coalesce(func.sum(Log.data_transmitted), 0)).scalar() or 0
    total_requests = session.query(func.coalesce(func.sum(Log.request_count), 0)).scalar() or 0

    # Top 20 users by activity
    top_users_by_activity = (
        session.query(User.username, func.sum(Log.request_count).label("total_visits"))
        .join(Log, Log.user_id == User.id).group_by(User.username)
        .order_by(func.sum(Log.request_count).desc()).limit(20).all()
    )
    top_users_by_activity = [{"username": u.username, "total_visits": u.total_visits} for u in top_users_by_activity]

    # Top 20 users by data transferred
    top_users_by_data_transferred = (
        session.query(User.username, func.sum(Log.data_transmitted).label("total_data_bytes"))
        .join(Log, Log.user_id == User.id).group_by(User.username)
        .order_by(func.sum(Log.data_transmitted).desc()).limit(20).all()
    )
    top_users_by_data_transferred = [{"username": u.username, "total_data_bytes": u.total_data_bytes} for u in top_users_by_data_transferred]

    # HTTP response distribution
    http_codes = session.query(Log.response, func.count(Log.id)).group_by(Log.response).all()
    code_labels = [str(code) for code, _ in http_codes]
    code_data = [count for _, count in http_codes]
    code_colors = [
        "#3B82F6" if 200 <= int(code) < 300 else "#F59E0B" if 300 <= int(code) < 400 else
        "#EF4444" if 400 <= int(code) < 500 else "#8B5CF6" if 500 <= int(code) < 600 else "#10B981"
        for code in code_labels ]

    # Top 20 pages
    top_pages = (
        session.query(Log.url, func.sum(Log.request_count).label("total_requests"),
            func.count(func.distinct(Log.user_id)).label("unique_visits"),
            func.sum(Log.data_transmitted).label("total_data_bytes")
        ).group_by(Log.url).order_by(func.sum(Log.request_count).desc()).limit(20).all()
    )
    top_pages = [ { "url": p.url, "total_requests": p.total_requests, "unique_visits": p.unique_visits, "total_data_bytes": p.total_data_bytes } for p in top_pages ]

    # IPs compartidas por múltiples usuarios
    users_per_ip = (
        session.query(User.ip, func.count(User.id).label("user_count"),
            func.group_concat(User.username, ', ').label("usernames")
        ).group_by(User.ip).having(func.count(User.id) > 1).all()
    )
    users_per_ip = [ { "ip": ip.ip, "user_count": ip.user_count, "usernames": ip.usernames } for ip in users_per_ip ]

    session.close()

    return {
        "total_stats": { "total_users": total_users, "total_log_entries": total_log_entries, "total_data_transmitted": total_data_transmitted, "total_requests": total_requests, },
        "top_users_by_activity": top_users_by_activity,
        "top_users_by_data_transferred": top_users_by_data_transferred,
        "http_response_distribution_chart": { "labels": code_labels, "data": code_data, "colors": code_colors },
        "top_pages": top_pages, "users_per_ip": users_per_ip }