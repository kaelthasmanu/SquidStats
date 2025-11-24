from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from venv import logger

from sqlalchemy import func, inspect, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.database import get_dynamic_models
from utils.social_media import SOCIAL_MEDIA_DOMAINS


def _get_tables_in_range(
    inspector, start_date: datetime, end_date: datetime
) -> list[tuple[str, str]]:
    all_db_tables = inspector.get_table_names()
    log_tables_in_range = []
    current_date = start_date
    while current_date <= end_date:
        date_suffix = current_date.strftime("%Y%m%d")
        log_table = f"log_{date_suffix}"
        user_table = f"user_{date_suffix}"
        if log_table in all_db_tables and user_table in all_db_tables:
            log_tables_in_range.append(log_table)
        current_date += timedelta(days=1)
    return log_tables_in_range

def find_by_keyword(
    db: Session, start_str: str, end_str: str, keyword: str, username: str = None
) -> dict[str, Any]:
    start_date, end_date = (
        datetime.strptime(start_str, "%Y-%m-%d"),
        datetime.strptime(end_str, "%Y-%m-%d"),
    )
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    all_results = []

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue

            # Crear query usando ORM
            query = (
                db.query(
                    UserModel.username,
                    UserModel.ip,
                    LogModel.url,
                    LogModel.data_transmitted,
                    LogModel.created_at,
                    func.count(LogModel.id).label("access_count"),
                    func.sum(LogModel.data_transmitted).label("total_data"),
                    func.max(LogModel.created_at).label("last_seen"),
                )
                .join(LogModel, LogModel.user_id == UserModel.id)
                .filter(LogModel.url.like(f"%{keyword}%"))
            )

            if username:
                query = query.filter(UserModel.username == username)

            query = query.group_by(
                UserModel.username,
                UserModel.ip,
                LogModel.url,
                LogModel.data_transmitted,
                LogModel.created_at,
            )

            results = query.all()

            for row in results:
                all_results.append(
                    {
                        "log_date": date_suffix,
                        "username": row.username,
                        "ip": row.ip,
                        "url": row.url,
                        "access_count": row.access_count,
                        "total_data": row.total_data,
                        "last_seen": row.last_seen,
                    }
                )

        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    # Ordenar resultados
    all_results.sort(
        key=lambda x: (x["username"], x["log_date"], x["access_count"]), reverse=True
    )

    return {"results": all_results}

def find_social_media_activity(
    db: Session, start_str: str, end_str: str, sites: list[str], username: str = None
) -> dict[str, Any]:
    start_date, end_date = (
        datetime.strptime(start_str, "%Y-%m-%d"),
        datetime.strptime(end_str, "%Y-%m-%d"),
    )
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    domain_list = []
    for site_name in sites:
        if site_name in SOCIAL_MEDIA_DOMAINS:
            domain_list.extend(SOCIAL_MEDIA_DOMAINS[site_name])
    if not domain_list:
        return {"error": "No valid domains specified for search."}

    all_results = []

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue

            # Crear condiciones OR para cada dominio usando ORM
            domain_conditions = []
            for domain in domain_list:
                domain_conditions.extend(
                    [
                        LogModel.url.like(f"%.{domain}/%"),
                        LogModel.url.like(f"%.{domain}:%"),
                        LogModel.url.like(f"%.{domain}"),
                        LogModel.url.like(f"%//{domain}/%"),
                        LogModel.url.like(f"%//{domain}:%"),
                        LogModel.url.like(f"%//{domain}"),
                    ]
                )

            # Crear query usando ORM
            query = (
                db.query(
                    UserModel.username,
                    UserModel.ip,
                    LogModel.url,
                    LogModel.data_transmitted,
                    LogModel.created_at,
                    func.count(LogModel.id).label("access_count"),
                    func.sum(LogModel.data_transmitted).label("total_data"),
                    func.max(LogModel.created_at).label("last_seen"),
                )
                .join(LogModel, LogModel.user_id == UserModel.id)
                .filter(or_(*domain_conditions))
            )

            if username:
                query = query.filter(UserModel.username == username)

            query = query.group_by(
                UserModel.username,
                UserModel.ip,
                LogModel.url,
                LogModel.data_transmitted,
                LogModel.created_at,
            )

            results = query.all()

            for row in results:
                all_results.append(
                    {
                        "log_date": date_suffix,
                        "username": row.username,
                        "ip": row.ip,
                        "url": row.url,
                        "access_count": row.access_count,
                        "total_data": row.total_data,
                        "last_seen": row.last_seen,
                    }
                )

        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    # Ordenar resultados
    all_results.sort(
        key=lambda x: (x["username"], x["log_date"], x["access_count"]), reverse=True
    )

    return {"results": all_results}

def find_by_ip(
    db: Session, start_str: str, end_str: str, ip_address: str
) -> dict[str, Any]:
    start_date, end_date = (
        datetime.strptime(start_str, "%Y-%m-%d"),
        datetime.strptime(end_str, "%Y-%m-%d"),
    )
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    all_results = []

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue

            # Crear query usando ORM
            query = (
                db.query(
                    UserModel.username,
                    UserModel.ip,
                    LogModel.url,
                    LogModel.data_transmitted,
                    LogModel.created_at,
                    func.count(LogModel.id).label("access_count"),
                    func.sum(LogModel.data_transmitted).label("total_data"),
                    func.max(LogModel.created_at).label("last_seen"),
                )
                .join(LogModel, LogModel.user_id == UserModel.id)
                .filter(UserModel.ip == ip_address)
                .group_by(
                    UserModel.username,
                    UserModel.ip,
                    LogModel.url,
                    LogModel.data_transmitted,
                    LogModel.created_at,
                )
            )

            results = query.all()

            for row in results:
                all_results.append(
                    {
                        "log_date": date_suffix,
                        "username": row.username,
                        "ip": row.ip,
                        "url": row.url,
                        "access_count": row.access_count,
                        "total_data": row.total_data,
                        "last_seen": row.last_seen,
                    }
                )

        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    # Ordenar resultados
    all_results.sort(
        key=lambda x: (x["username"], x["log_date"], x["access_count"]), reverse=True
    )

    return {"results": all_results}

def find_by_response_code(
    db: Session, start_str: str, end_str: str, code: int, username: str = None
) -> dict[str, Any]:
    start_date, end_date = (
        datetime.strptime(start_str, "%Y-%m-%d"),
        datetime.strptime(end_str, "%Y-%m-%d"),
    )
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    all_results = []

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue

            # Crear query usando ORM
            query = (
                db.query(
                    UserModel.username,
                    UserModel.ip,
                    LogModel.url,
                    LogModel.response,
                    LogModel.data_transmitted,
                    LogModel.created_at,
                    func.count(LogModel.id).label("access_count"),
                    func.sum(LogModel.data_transmitted).label("total_data"),
                    func.max(LogModel.created_at).label("last_seen"),
                )
                .join(LogModel, LogModel.user_id == UserModel.id)
                .filter(LogModel.response == code)
            )

            if username:
                query = query.filter(UserModel.username == username)

            query = query.group_by(
                UserModel.username,
                UserModel.ip,
                LogModel.url,
                LogModel.response,
                LogModel.data_transmitted,
                LogModel.created_at,
            )

            results = query.all()

            for row in results:
                all_results.append(
                    {
                        "log_date": date_suffix,
                        "username": row[0],
                        "ip": row[1],
                        "url": row[2],
                        "response": row[3],
                        "access_count": row.access_count,
                        "total_data": row.total_data,
                        "last_seen": row.last_seen,
                    }
                )

        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    # Ordenar resultados
    all_results.sort(
        key=lambda x: (x["username"], x["log_date"], x["access_count"]), reverse=True
    )

    return {"results": all_results}

def get_daily_activity(db: Session, date_str: str, username: str) -> dict[str, Any]:
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    date_suffix = selected_date.strftime("%Y%m%d")

    try:
        UserModel, LogModel = get_dynamic_models(date_suffix)
        if UserModel is None or LogModel is None:
            return {"total_requests": 0, "hourly_activity": [0] * 24}

        # Crear query usando ORM - compatible con SQLite y MySQL
        query = (
            db.query(
                func.cast(
                    func.strftime("%H", LogModel.created_at), text("INTEGER")
                ).label("hour_of_day"),
                func.count(LogModel.id).label("request_count"),
            )
            .join(UserModel, LogModel.user_id == UserModel.id)
            .filter(UserModel.username == username)
            .group_by(
                func.cast(func.strftime("%H", LogModel.created_at), text("INTEGER"))
            )
            .order_by(
                func.cast(func.strftime("%H", LogModel.created_at), text("INTEGER"))
            )
        )

        results = query.all()

        # Prepara un array de 24 horas con 0 peticiones
        hourly_counts = [0] * 24
        total_requests = 0

        for row in results:
            hour = row.hour_of_day
            count = row.request_count
            if hour is not None and 0 <= hour < 24:
                hourly_counts[hour] = count
                total_requests += count

        return {"total_requests": total_requests, "hourly_activity": hourly_counts}

    except SQLAlchemyError as e:
        print(f"Database error in get_daily_activity: {e}")
        return {"error": "A database error occurred while calculating daily activity."}
    except Exception as e:
        print(f"General error in get_daily_activity: {e}")
        return {
            "error": "An unexpected error occurred while calculating daily activity."
        }

def get_all_usernames(db: Session) -> list[str]:
    engine = db.get_bind()
    inspector = inspect(engine)
    all_tables = inspector.get_table_names()
    user_tables = [t for t in all_tables if t.startswith("user_") and len(t) == 13]
    if not user_tables:
        return []

    all_usernames = set()

    for table_name in user_tables:
        date_suffix = table_name.split("_")[1]
        try:
            UserModel, _ = get_dynamic_models(date_suffix)
            if UserModel is None:
                continue

            # Usar ORM para obtener usernames únicos
            usernames = (
                db.query(UserModel.username)
                .filter(
                    UserModel.username.isnot(None),
                    UserModel.username != "",
                    UserModel.username != "-",
                )
                .distinct()
                .all()
            )

            for username_row in usernames:
                all_usernames.add(username_row[0])

        except Exception as e:
            print(f"Error processing table {table_name}: {e}")
            continue

    return sorted(all_usernames)

def get_user_activity_summary(
    db: Session, username: str, start_str: str, end_str: str
) -> dict[str, Any]:
    start_date = datetime.strptime(start_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_str, "%Y-%m-%d")
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    total_requests = 0
    total_data = 0
    domain_counts = defaultdict(int)
    response_counts = defaultdict(int)

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue

            # Usar ORM para obtener datos del usuario
            results = (
                db.query(
                    LogModel.url,
                    LogModel.data_transmitted,
                    LogModel.request_count,
                    LogModel.response,
                )
                .join(UserModel, LogModel.user_id == UserModel.id)
                .filter(UserModel.username == username)
                .all()
            )

            for row in results:
                total_requests += row[2]
                total_data += row[1]

                # Extraer dominio
                try:
                    domain = row[0].split("//")[-1].split("/")[0].split(":")[0]
                    domain_counts[domain] += row[2]
                except Exception as e:
                    logger.error(
                        f"Error processing row in get_user_activity_summary: {e}"
                    )
                    pass

                response_counts[row[3]] += row[2]

        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    if total_requests == 0:
        return {
            "total_requests": 0,
            "total_data_gb": 0,
            "top_domains": [],
            "response_summary": [],
        }

    sorted_domains = sorted(
        domain_counts.items(), key=lambda item: item[1], reverse=True
    )
    sorted_responses = sorted(
        response_counts.items(), key=lambda item: item[1], reverse=True
    )

    return {
        "total_requests": total_requests,
        "total_data_gb": round(total_data / (1024**3), 2),
        "top_domains": [{"domain": d, "count": c} for d, c in sorted_domains[:15]],
        "response_summary": [
            {"code": code, "count": count} for code, count in sorted_responses
        ],
    }

def get_top_users_by_data(
    db: Session, start_str: str, end_str: str, limit: int = 10
) -> dict[str, Any]:
    start_date = datetime.strptime(start_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_str, "%Y-%m-%d")
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    user_data = defaultdict(int)

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue
            results = (
                db.query(
                    UserModel.username,
                    func.sum(LogModel.data_transmitted).label("total_data"),
                )
                .join(LogModel, LogModel.user_id == UserModel.id)
                .filter(UserModel.username != "-")
                .group_by(UserModel.username)
                .all()
            )

            for row in results:
                user_data[row[0]] += row.total_data or 0

        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    # Ordenar y limitar resultados
    sorted_users = sorted(user_data.items(), key=lambda x: x[1], reverse=True)[:limit]

    top_users_list = [
        {"username": username, "total_data_gb": float(round(total_data / (1024**3), 2))}
        for username, total_data in sorted_users
    ]

    return {"top_users": top_users_list}

def get_top_users_by_requests(
    db: Session, start_str: str, end_str: str, limit: int = 10
) -> dict[str, Any]:
    """Aggregate top users by total request_count across the date range."""
    start_date = datetime.strptime(start_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_str, "%Y-%m-%d")
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    user_reqs: defaultdict[str, int] = defaultdict(int)

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue
            results = (
                db.query(
                    UserModel.username,
                    func.sum(LogModel.request_count).label("total_reqs"),
                )
                .join(LogModel, LogModel.user_id == UserModel.id)
                .filter(UserModel.username != "-")
                .group_by(UserModel.username)
                .all()
            )
            for row in results:
                user_reqs[row[0]] += row.total_reqs or 0
        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    sorted_users = sorted(user_reqs.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        "top_users_requests": [
            {"username": username, "total_requests": int(total_reqs)}
            for username, total_reqs in sorted_users
        ]
    }

def get_top_urls_by_data(
    db: Session, start_str: str, end_str: str, limit: int = 15
) -> dict[str, Any]:
    start_date = datetime.strptime(start_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_str, "%Y-%m-%d")
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    url_data = defaultdict(int)

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue
            results = (
                db.query(
                    LogModel.url,
                    func.sum(LogModel.data_transmitted).label("total_data"),
                )
                .group_by(LogModel.url)
                .all()
            )

            for row in results:
                url_data[row[0]] += row.total_data or 0

        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    # Ordenar y limitar resultados
    sorted_urls = sorted(url_data.items(), key=lambda x: x[1], reverse=True)[:limit]

    top_urls_list = [
        {"url": url, "total_data_gb": float(round(total_data / (1024**3), 2))}
        for url, total_data in sorted_urls
    ]

    return {"top_urls": top_urls_list}

def get_top_ips_by_data(
    db: Session, start_str: str, end_str: str, limit: int = 10
) -> dict[str, Any]:
    """Aggregate total data transmitted grouped by IP across the date range."""
    start_date = datetime.strptime(start_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_str, "%Y-%m-%d")
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    ip_data: defaultdict[str, int] = defaultdict(int)

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue
            results = (
                db.query(
                    UserModel.ip,
                    func.sum(LogModel.data_transmitted).label("total_data"),
                )
                .join(LogModel, LogModel.user_id == UserModel.id)
                .group_by(UserModel.ip)
                .all()
            )
            for row in results:
                ip_data[row[0]] += row.total_data or 0
        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    sorted_ips = sorted(ip_data.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        "top_ips": [
            {
                "ip": ip,
                "total_data_gb": float(round(total_data / (1024**3), 2)),
            }
            for ip, total_data in sorted_ips
        ]
    }

def find_denied_access(
    db: Session, start_str: str, end_str: str, username: str = None
) -> dict[str, Any]:
    start_date = datetime.strptime(start_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_str, "%Y-%m-%d")
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No data for the selected dates."}

    all_results = []

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue

            # Crear query usando ORM
            query = (
                db.query(
                    UserModel.username,
                    UserModel.ip,
                    LogModel.url,
                    LogModel.response,
                    LogModel.data_transmitted,
                    LogModel.created_at,
                )
                .join(LogModel, LogModel.user_id == UserModel.id)
                .filter(LogModel.response == 403)
            )

            if username:
                query = query.filter(UserModel.username == username)

            query = query.order_by(LogModel.created_at.desc())

            results = query.all()

            for row in results:
                all_results.append(
                    {
                        "log_date": date_suffix,
                        "username": row[0],
                        "ip": row[1],
                        "url": row[2],
                        "response": row[3],
                        "data_transmitted": row[4],
                        "created_at": row[5],
                    }
                )

        except Exception as e:
            print(f"Error processing table {log_table}: {e}")
            continue

    # Ordenar resultados
    all_results.sort(key=lambda x: (x["log_date"], x["username"]), reverse=True)

    return {"results": all_results}

def find_suspicious_activity(db, threshold=50, hours=1):
    """
    Encuentra IPs con actividad sospechosa (muchos requests en poco tiempo)
    Retorna: lista de tuplas [(ip, count), ...]
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta
    
    try:
        since_time = datetime.now() - timedelta(hours=hours)
        
        query = text("""
            SELECT ip_address, COUNT(*) as request_count
            FROM logs 
            WHERE timestamp >= :since_time
            GROUP BY ip_address
            HAVING request_count > :threshold
            ORDER BY request_count DESC
            LIMIT 10
        """)
        
        result = db.execute(query, {
            'since_time': since_time,
            'threshold': threshold
        })
        
        return [(row[0], row[1]) for row in result]
        
    except Exception as e:
        print(f"Error finding suspicious activity: {e}")
        return []

def get_active_users_count(db, hours=1):
    """
    Cuenta usuarios únicos activos en las últimas N horas
    Retorna: número de usuarios únicos
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta
    
    try:
        since_time = datetime.now() - timedelta(hours=hours)
        
        query = text("""
            SELECT COUNT(DISTINCT username)
            FROM logs
            WHERE timestamp >= :since_time 
            AND username IS NOT NULL 
            AND username != ''
        """)
        
        result = db.execute(query, {'since_time': since_time})
        return result.scalar() or 0
        
    except Exception as e:
        print(f"Error counting active users: {e}")
        return 0

def get_high_usage_users(db, hours=24, limit=5, threshold_mb=500):
    """
    Obtiene usuarios con mayor consumo de datos
    Retorna: lista de tuplas [(username, usage_mb), ...]
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta
    
    try:
        since_time = datetime.now() - timedelta(hours=hours)
        
        query = text("""
            SELECT 
                username,
                SUM(bytes_sent) / (1024 * 1024) as usage_mb
            FROM logs
            WHERE timestamp >= :since_time
            AND username IS NOT NULL 
            AND username != ''
            GROUP BY username
            HAVING usage_mb > :threshold_mb
            ORDER BY usage_mb DESC
            LIMIT :limit
        """)
        
        result = db.execute(query, {
            'since_time': since_time,
            'threshold_mb': threshold_mb,
            'limit': limit
        })
        
        return [(row[0], float(row[1])) for row in result]
        
    except Exception as e:
        print(f"Error getting high usage users: {e}")
        return []

def get_failed_auth_attempts(db, hours=1, threshold=10):
    """
    Obtiene intentos de autenticación fallidos
    Retorna: número de intentos fallidos
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta
    
    try:
        since_time = datetime.now() - timedelta(hours=hours)
        
        query = text("""
            SELECT COUNT(*) as failed_count
            FROM logs
            WHERE timestamp >= :since_time
            AND response_code IN ('407', '401', '403')
        """)
        
        result = db.execute(query, {'since_time': since_time})
        count = result.scalar() or 0
        
        return count
        
    except Exception as e:
        print(f"Error getting failed auth attempts: {e}")
        return 0

def get_denied_requests(db, hours=1, threshold=5):
    """
    Obtiene requests denegados
    Retorna: número de requests denegados
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta
    
    try:
        since_time = datetime.now() - timedelta(hours=hours)
        
        query = text("""
            SELECT COUNT(*) as denied_count
            FROM logs
            WHERE timestamp >= :since_time
            AND response_code = '403'
        """)
        
        result = db.execute(query, {'since_time': since_time})
        count = result.scalar() or 0
        
        return count
        
    except Exception as e:
        print(f"Error getting denied requests: {e}")
        return 0