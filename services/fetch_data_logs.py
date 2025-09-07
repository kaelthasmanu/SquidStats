import logging
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, inspect
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session

from database.database import get_concat_function, get_dynamic_models, get_session

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Patrones de validación para nombres de tabla y fechas
TABLE_NAME_PATTERN = re.compile(r"^[a-z_]{3,20}$")
DATE_SUFFIX_PATTERN = re.compile(r"^\d{8}$")


def validate_table_name(table_name: str) -> bool:
    return bool(TABLE_NAME_PATTERN.match(table_name))


def validate_date_suffix(date_suffix: str) -> bool:
    return bool(DATE_SUFFIX_PATTERN.match(date_suffix))


def sanitize_table_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower())


def get_dynamic_model(db: Session, table_name: str, date_suffix: str):
    # Validar parámetros
    if not validate_table_name(table_name):
        logger.error(f"Invalid table name: {table_name}")
        return None

    if not validate_date_suffix(date_suffix):
        logger.error(f"Invalid date suffix: {date_suffix}")
        return None

    full_table_name = f"{table_name}_{date_suffix}"

    # Check if the table exists
    try:
        inspector = inspect(db.get_bind())
        if not inspector.has_table(full_table_name):
            logger.warning(f"Table {full_table_name} not found")
            return None

        # Create dynamic model using automap
        Base = automap_base()
        Base.prepare(autoload_with=db.get_bind())

        return getattr(Base.classes, full_table_name, None)
    except Exception as e:
        logger.error(f"Error getting dynamic model: {str(e)}", exc_info=True)
        return None


def get_users_logs(
    db: Session,
    date_suffix: str | None = None,
    page: int = 1,
    per_page: int = 15,
    search: str | None = None,
) -> dict[str, Any]:
    try:
        if not date_suffix:
            date_suffix = datetime.now().strftime("%Y%m%d")
        if not validate_date_suffix(date_suffix):
            logger.error(f"Invalid date suffix: {date_suffix}")
            return {
                "users": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            }

        UserModel = get_dynamic_model(db, "user", date_suffix)
        LogModel = get_dynamic_model(db, "log", date_suffix)

        if not UserModel or not LogModel:
            logger.error(f"Dynamic tables not available for date {date_suffix}")
            return {
                "users": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            }

        # Contar total de usuarios distintos (con filtro opcional de búsqueda)
        base_filter = [UserModel.username != "-"]
        if search:
            search_lc = f"%{search.lower()}%"
            base_filter.append(func.lower(UserModel.username).like(search_lc))
        total = db.query(UserModel).filter(*base_filter).count()

        # Paginación
        offset = (page - 1) * per_page
        users_query = db.query(UserModel).filter(*base_filter).order_by(UserModel.id)
        if per_page:
            users_query = users_query.offset(offset).limit(per_page)
        users = users_query.all()

        users_map = {}
        user_ids = [u.id for u in users]

        # Traer logs solo de los usuarios de la página
        logs_query = (
            db.query(
                UserModel.id.label("user_id"),
                UserModel.username,
                UserModel.ip,
                LogModel.url,
                LogModel.response,
                LogModel.request_count,
                LogModel.data_transmitted,
            )
            .join(LogModel, UserModel.id == LogModel.user_id)
            .filter(UserModel.id.in_(user_ids))
        )

        for row in logs_query:
            user_id = row.user_id
            if user_id not in users_map:
                users_map[user_id] = {
                    "user_id": user_id,
                    "username": row.username,
                    "ip": row.ip,
                    "logs": [],
                    "total_requests": 0,
                    "total_data": 0,
                }
            log_entry = {
                "url": row.url,
                "response": row.response,
                "request_count": row.request_count,
                "data_transmitted": row.data_transmitted,
            }
            users_map[user_id]["logs"].append(log_entry)
            users_map[user_id]["total_requests"] += row.request_count
            users_map[user_id]["total_data"] += row.data_transmitted

        total_pages = (total + per_page - 1) // per_page if per_page else 1
        return {
            "users": list(users_map.values()),
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    except Exception as e:
        logger.error(f"Error in paginated get_users_logs: {str(e)}", exc_info=True)
        return {
            "users": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }
    finally:
        db.close()


def get_users_with_logs_by_date(db: Session, date_suffix: str) -> list[dict[str, Any]]:
    # Validar sufijo de fecha
    if not validate_date_suffix(date_suffix):
        logger.error(f"Invalid date suffix: {date_suffix}")
        return []

    return get_users_logs(db, date_suffix)


def get_metrics_for_date(selected_date: date):
    session = get_session()
    date_suffix = selected_date.strftime("%Y%m%d")
    try:
        User, Log = get_dynamic_models(date_suffix)
    except Exception:
        # Si no existen tablas para esa fecha, devuelve métricas vacías
        return {
            "total_stats": {
                "total_users": 0,
                "total_log_entries": 0,
                "total_data_transmitted": 0,
                "total_requests": 0,
            },
            "top_users_by_activity": [],
            "top_users_by_data_transferred": [],
            "http_response_distribution_chart": {
                "labels": [],
                "data": [],
                "colors": [],
            },
            "top_pages": [],
            "users_per_ip": [],
        }

    # Total stats
    total_users = session.query(func.count(User.id)).scalar() or 0
    total_log_entries = session.query(func.count(Log.id)).scalar() or 0
    total_data_transmitted = (
        session.query(func.coalesce(func.sum(Log.data_transmitted), 0)).scalar() or 0
    )
    total_requests = (
        session.query(func.coalesce(func.sum(Log.request_count), 0)).scalar() or 0
    )

    # Top 20 users by activity
    top_users_by_activity = (
        session.query(User.username, func.sum(Log.request_count).label("total_visits"))
        .join(Log, Log.user_id == User.id)
        .group_by(User.username)
        .order_by(func.sum(Log.request_count).desc())
        .limit(20)
        .all()
    )
    top_users_by_activity = [
        {"username": u.username, "total_visits": u.total_visits}
        for u in top_users_by_activity
    ]

    # Top 20 users by data transferred
    top_users_by_data_transferred = (
        session.query(
            User.username, func.sum(Log.data_transmitted).label("total_data_bytes")
        )
        .join(Log, Log.user_id == User.id)
        .group_by(User.username)
        .order_by(func.sum(Log.data_transmitted).desc())
        .limit(20)
        .all()
    )
    top_users_by_data_transferred = [
        {"username": u.username, "total_data_bytes": u.total_data_bytes}
        for u in top_users_by_data_transferred
    ]

    # HTTP response distribution
    http_codes = (
        session.query(Log.response, func.count(Log.id)).group_by(Log.response).all()
    )
    code_labels = [str(code) for code, _ in http_codes]
    code_data = [count for _, count in http_codes]
    code_colors = [
        "#3B82F6"
        if 200 <= int(code) < 300
        else "#F59E0B"
        if 300 <= int(code) < 400
        else "#EF4444"
        if 400 <= int(code) < 500
        else "#8B5CF6"
        if 500 <= int(code) < 600
        else "#10B981"
        for code in code_labels
    ]

    # Top 20 pages
    top_pages = (
        session.query(
            Log.url,
            func.sum(Log.request_count).label("total_requests"),
            func.count(func.distinct(Log.user_id)).label("unique_visits"),
            func.sum(Log.data_transmitted).label("total_data_bytes"),
        )
        .group_by(Log.url)
        .order_by(func.sum(Log.request_count).desc())
        .limit(20)
        .all()
    )
    top_pages = [
        {
            "url": p.url,
            "total_requests": p.total_requests,
            "unique_visits": p.unique_visits,
            "total_data_bytes": p.total_data_bytes,
        }
        for p in top_pages
    ]

    # IPs compartidas por múltiples usuarios
    users_per_ip = (
        session.query(
            User.ip,
            func.count(User.id).label("user_count"),
            get_concat_function(User.username, ", ").label("usernames"),
        )
        .group_by(User.ip)
        .having(func.count(User.id) > 1)
        .all()
    )
    users_per_ip = [
        {"ip": ip.ip, "user_count": ip.user_count, "usernames": ip.usernames}
        for ip in users_per_ip
    ]

    return {
        "total_stats": {
            "total_users": total_users,
            "total_log_entries": total_log_entries,
            "total_data_transmitted": total_data_transmitted,
            "total_requests": total_requests,
        },
        "top_users_by_activity": top_users_by_activity,
        "top_users_by_data_transferred": top_users_by_data_transferred,
        "http_response_distribution_chart": {
            "labels": code_labels,
            "data": code_data,
            "colors": code_colors,
        },
        "top_pages": top_pages,
        "users_per_ip": users_per_ip,
    }
