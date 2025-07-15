from venv import logger
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Tuple
from collections import defaultdict

SOCIAL_MEDIA_DOMAINS = {
    'YouTube': [
        'youtube.com', 'ytimg.com', 'googlevideo.com', 'yt3.ggpht.com',
        'youtubei.googleapis.com', 'youtube-ui.l.google.com', 'youtube.googleapis.com'
    ],
    'Facebook': [
        'facebook.com', 'fbcdn.net', 'facebook.net', 'fbsbx.com', 'fbpigeon.com',
        'fb.com', 'facebook-hardware.com'
    ],
    'Pinterest': [
        'pinterest.com', 'pinimg.com', 'cdx.cedexis.net', 'pinterest.net',
        'pinterest.pt', 'pinterest.cl', 'pinterest.info'
    ],
    'Instagram': [
        'instagram.com', 'cdninstagram.com', 'z-p42-chat-e2ee-ig.facebook.com',
        'mqtt-ig-p4.facebook.com', 'z-p42-chat-e2ee-ig-fallback.facebook.com',
        'ig.me', 'instagram.am', 'igsonar.com'
    ],
    'Telegram': [
        'telegram.org', 't.me', 'telegram.me', 'tg.dev', 'telesco.pe'
    ],
    'WhatsApp': [
        'whatsapp.net', 'whatsapp.com', 'wa.me', 'wl.co', 'whatsappbrand.com',
        'whatsapp-plus.info', 'whatsapp-plus.me', 'whatsapp-plus.net',
        'whatsapp.cc', 'whatsapp.info', 'whatsapp.org', 'whatsapp.tv'
    ],
    'Twitter/X': [
        'twitter.com', 't.co', 'anuncios-twitter.com', 'twimg.com', 'x.com',
        'pscp.tv', 'twtrdns.net', 'twttr.com', 'periscopio.tv', 'twitpic.com',
        'tweetdeck.com', 'twitter.co', 'twitterinc.com', 'twitteroauth.com',
        'twitterstat.us'
    ]
}

def _get_tables_in_range(inspector, start_date: datetime, end_date: datetime) -> List[Tuple[str, str]]:
    all_db_tables = inspector.get_table_names()
    log_tables_in_range = []
    current_date = start_date
    while current_date <= end_date:
        date_suffix = current_date.strftime("%Y%m%d")
        log_table = f'log_{date_suffix}'
        user_table = f'user_{date_suffix}'
        if log_table in all_db_tables and user_table in all_db_tables:
            log_tables_in_range.append((log_table, user_table))
        current_date += timedelta(days=1)
    return log_tables_in_range

def _execute_union_query(db: Session, tables: List[Tuple[str, str]], where_clause: str, params: Dict, order_by: str) -> List[Any]:
    select_clauses = []
    for log_table, user_table in tables:
        date_str = log_table.split('_')[1]
        select_clauses.append(
            f"SELECT u.username, u.ip, l.url, l.response, l.data_transmitted, l.created_at, '{date_str}' as log_date "
            f"FROM {log_table} l JOIN {user_table} u ON l.user_id = u.id"
        )
    
    full_query_str = f"""
        SELECT username, ip, url, response, data_transmitted, created_at, log_date
        FROM ({ " UNION ALL ".join(select_clauses) }) as all_logs
        WHERE {where_clause}
        ORDER BY {order_by}
    """
    try:
        return db.execute(text(full_query_str), params).fetchall()
    except SQLAlchemyError as e:
        print(f"Error en _execute_union_query: {e}")
        raise

def find_by_keyword(db: Session, start_str: str, end_str: str, keyword: str, username: str = None) -> Dict[str, Any]:
    start_date, end_date = datetime.strptime(start_str, '%Y-%m-%d'), datetime.strptime(end_str, '%Y-%m-%d')
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No hay datos para las fechas seleccionadas."}

    select_clauses = []
    for log_table, user_table in tables:
        date_str = log_table.split('_')[1]
        select_clauses.append(
            f"SELECT u.username, u.ip, l.url, l.data_transmitted, l.created_at, '{date_str}' as log_date "
            f"FROM {log_table} l JOIN {user_table} u ON l.user_id = u.id"
        )

    where_clause = "url LIKE :keyword"
    params = {'keyword': f'%{keyword}%'}
    if username:
        where_clause += " AND username = :username"
        params['username'] = username

    full_query_str = f"""
        SELECT log_date, username, ip, url, COUNT(*) as access_count, SUM(data_transmitted) as total_data, MAX(created_at) as last_seen
        FROM ({ " UNION ALL ".join(select_clauses) }) as all_logs
        WHERE {where_clause}
        GROUP BY log_date, username, ip, url
        ORDER BY username, log_date DESC, access_count DESC
    """
    try:
        results = db.execute(text(full_query_str), params).fetchall()
        return {"results": [dict(row._mapping) for row in results]}
    except SQLAlchemyError as e:
        print(f"Error en find_by_keyword: {e}")
        raise

def find_social_media_activity(db: Session, start_str: str, end_str: str, sites: List[str], username: str = None) -> Dict[str, Any]:
    start_date, end_date = datetime.strptime(start_str, '%Y-%m-%d'), datetime.strptime(end_str, '%Y-%m-%d')
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables: 
        return {"error": "No hay datos para las fechas seleccionadas."}

    domain_list = []
    for site_name in sites:
        if site_name in SOCIAL_MEDIA_DOMAINS:
            domain_list.extend(SOCIAL_MEDIA_DOMAINS[site_name])
    if not domain_list:
        return {"error": "No se especificaron dominios válidos para la búsqueda."}

    like_conditions = []
    params = {}
    param_index = 0
    for domain in domain_list:
        condition_group = (
            f"url LIKE :p{param_index}_sub_slash OR "
            f"url LIKE :p{param_index}_sub_colon OR "
            f"url LIKE :p{param_index}_sub_exact OR "
            f"url LIKE :p{param_index}_proto_slash OR "
            f"url LIKE :p{param_index}_proto_colon OR "
            f"url LIKE :p{param_index}_proto_exact"
        )
        like_conditions.append(f"({condition_group})")
        params[f'p{param_index}_sub_slash'] = f'%.{domain}/%'
        params[f'p{param_index}_sub_colon'] = f'%.{domain}:%'
        params[f'p{param_index}_sub_exact'] = f'%.{domain}'
        params[f'p{param_index}_proto_slash'] = f'%//{domain}/%'
        params[f'p{param_index}_proto_colon'] = f'%//{domain}:%'
        params[f'p{param_index}_proto_exact'] = f'%//{domain}'
        param_index += 1

    where_clause = f"({' OR '.join(like_conditions)})"
    if username:
        where_clause += " AND username = :username"
        params['username'] = username

    select_clauses = []
    for log_table, user_table in tables:
        date_str = log_table.split('_')[1]
        select_clauses.append(
            f"SELECT u.username, u.ip, l.url, l.data_transmitted, l.created_at, '{date_str}' as log_date "
            f"FROM {log_table} l JOIN {user_table} u ON l.user_id = u.id"
        )
    
    full_query_str = f"""
        SELECT log_date, username, ip, url, COUNT(*) as access_count, SUM(data_transmitted) as total_data, MAX(created_at) as last_seen
        FROM ({ " UNION ALL ".join(select_clauses) }) as all_logs
        WHERE {where_clause}
        GROUP BY log_date, username, ip, url
        ORDER BY username, log_date DESC, access_count DESC
    """
    try:
        results = db.execute(text(full_query_str), params).fetchall()
        return {"results": [dict(row._mapping) for row in results]}
    except SQLAlchemyError as e:
        print(f"Error en find_social_media_activity: {e}")
        raise

def find_by_ip(db: Session, start_str: str, end_str: str, ip_address: str) -> Dict[str, Any]:
    start_date, end_date = datetime.strptime(start_str, '%Y-%m-%d'), datetime.strptime(end_str, '%Y-%m-%d')
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables: 
        return {"error": "No hay datos para las fechas seleccionadas."}

    select_clauses = []
    for log_table, user_table in tables:
        date_str = log_table.split('_')[1]
        select_clauses.append(
            f"SELECT u.username, u.ip, l.url, l.data_transmitted, l.created_at, '{date_str}' as log_date "
            f"FROM {log_table} l JOIN {user_table} u ON l.user_id = u.id WHERE u.ip = :ip_address"
        )
    
    params = {'ip_address': ip_address}
    
    full_query_str = f"""
        SELECT log_date, username, ip, url, COUNT(*) as access_count, SUM(data_transmitted) as total_data, MAX(created_at) as last_seen
        FROM ({ " UNION ALL ".join(select_clauses) }) as all_logs
        GROUP BY log_date, username, ip, url
        ORDER BY username, log_date DESC, access_count DESC
    """
    try:
        results = db.execute(text(full_query_str), params).fetchall()
        return {"results": [dict(row._mapping) for row in results]}
    except SQLAlchemyError as e:
        print(f"Error en find_by_ip: {e}")
        raise

def find_by_response_code(db: Session, start_str: str, end_str: str, code: int, username: str = None) -> Dict[str, Any]:
    start_date, end_date = datetime.strptime(start_str, '%Y-%m-%d'), datetime.strptime(end_str, '%Y-%m-%d')
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables: 
        return {"error": "No hay datos para las fechas seleccionadas."}

    select_clauses = []
    for log_table, user_table in tables:
        date_str = log_table.split('_')[1]
        select_clauses.append(
            f"SELECT u.username, u.ip, l.url, l.data_transmitted, l.response, l.created_at, '{date_str}' as log_date "
            f"FROM {log_table} l JOIN {user_table} u ON l.user_id = u.id"
        )
    
    where_clause = "response = :code"
    params = {'code': code}
    if username:
        where_clause += " AND username = :username"
        params['username'] = username
    
    full_query_str = f"""
        SELECT log_date, username, ip, url, response, COUNT(*) as access_count, SUM(data_transmitted) as total_data, MAX(created_at) as last_seen
        FROM ({ " UNION ALL ".join(select_clauses) }) as all_logs
        WHERE {where_clause}
        GROUP BY log_date, username, ip, url, response
        ORDER BY username, log_date DESC, access_count DESC
    """
    try:
        results = db.execute(text(full_query_str), params).fetchall()
        return {"results": [dict(row._mapping) for row in results]}
    except SQLAlchemyError as e:
        print(f"Error en find_by_response_code: {e}")
        raise

# --- INICIO DE LA MODIFICACIÓN ---
def get_daily_activity(db: Session, date_str: str, username: str) -> Dict[str, Any]:
    """Calcula el número de peticiones por hora para un usuario en un día específico."""
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return {"error": "Formato de fecha inválido. Use YYYY-MM-DD."}

    date_suffix = selected_date.strftime("%Y%m%d")
    log_table = f'log_{date_suffix}'
    user_table = f'user_{date_suffix}'
    
    inspector = inspect(db.get_bind())
    if not all(table in inspector.get_table_names() for table in [log_table, user_table]):
        return {"total_requests": 0, "hourly_activity": []}

    params = {'username': username}
    
    # Consulta para agrupar peticiones por hora del día para un usuario
    query = text(f"""
        SELECT
            HOUR(l.created_at) as hour_of_day,
            COUNT(*) as request_count
        FROM {log_table} l
        JOIN {user_table} u ON l.user_id = u.id
        WHERE u.username = :username
        GROUP BY hour_of_day
        ORDER BY hour_of_day ASC
    """)
    
    try:
        results = db.execute(query, params).fetchall()
        
        # Prepara un array de 24 horas con 0 peticiones
        hourly_counts = [0] * 24
        total_requests = 0

        for row in results:
            hour = row.hour_of_day
            count = row.request_count
            if 0 <= hour < 24:
                hourly_counts[hour] = count
                total_requests += count
        
        return {
            "total_requests": total_requests,
            "hourly_activity": hourly_counts
        }
    except SQLAlchemyError as e:
        print(f"Error en get_daily_activity: {e}")
        return {"error": "Ocurrió un error en la base de datos al calcular la actividad diaria."}
# --- FIN DE LA MODIFICACIÓN ---

def get_all_usernames(db: Session) -> List[str]:
    engine = db.get_bind()
    inspector = inspect(engine)
    all_tables = inspector.get_table_names()
    user_tables = [t for t in all_tables if t.startswith('user_') and len(t) == 13]
    if not user_tables:
        return []
    union_query = " UNION ".join([f"SELECT username FROM {table}" for table in user_tables])
    where_clause = "WHERE username IS NOT NULL AND username != '' AND username != '-'"
    full_query = text(f"SELECT DISTINCT username FROM ({union_query}) as all_users {where_clause} ORDER BY username")
    try:
        result = db.execute(full_query).fetchall()
        return [row[0] for row in result]
    except SQLAlchemyError as e:
        print(f"Error al obtener todos los usuarios: {e}")
        return []

def get_user_activity_summary(db: Session, username: str, start_str: str, end_str: str) -> Dict[str, Any]:
    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_str, '%Y-%m-%d')
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No hay datos para las fechas seleccionadas."}

    select_clauses = []
    for log_table, user_table in tables:
        select_clauses.append(
            f"SELECT l.url, l.data_transmitted, l.request_count, l.response FROM {log_table} l JOIN {user_table} u ON l.user_id = u.id WHERE u.username = :username"
        )
    full_query = text(" UNION ALL ".join(select_clauses))
    try:
        results = db.execute(full_query, {'username': username}).fetchall()
        if not results:
            return {'total_requests': 0, 'total_data_gb': 0, 'top_domains': [], 'response_summary': []}

        total_requests = sum(r.request_count for r in results)
        total_data = sum(r.data_transmitted for r in results)
        domain_counts = defaultdict(int)
        response_counts = defaultdict(int)
        for row in results:
            try:
                domain = row.url.split('//')[-1].split('/')[0].split(':')[0]
                domain_counts[domain] += row.request_count
            except Exception as e:
                logger.error(f"Error processing row in get_user_activity_summary: {e}")
                pass
            response_counts[row.response] += row.request_count

        sorted_domains = sorted(domain_counts.items(), key=lambda item: item[1], reverse=True)
        sorted_responses = sorted(response_counts.items(), key=lambda item: item[1], reverse=True)
        return {
            "total_requests": total_requests,
            "total_data_gb": round(total_data / (1024**3), 2),
            "top_domains": [{"domain": d, "count": c} for d, c in sorted_domains[:15]],
            "response_summary": [{"code": code, "count": count} for code, count in sorted_responses],
        }
    except SQLAlchemyError as e:
        return {"error": str(e)}

def get_top_users_by_data(db: Session, start_str: str, end_str: str, limit: int = 10) -> Dict[str, Any]:
    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_str, '%Y-%m-%d')
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No hay datos para las fechas seleccionadas."}

    select_clauses = []
    for log_table, user_table in tables:
        select_clauses.append(
            f"SELECT u.username, l.data_transmitted FROM {log_table} l JOIN {user_table} u ON l.user_id = u.id WHERE u.username != '-'"
        )
    full_query = text(f"""
        SELECT username, SUM(data_transmitted) as total_data
        FROM ({ " UNION ALL ".join(select_clauses) }) as all_logs
        GROUP BY username
        ORDER BY total_data DESC
        LIMIT :limit
    """)
    try:
        results = db.execute(full_query, {'limit': limit}).fetchall()
        top_users_list = [{
            "username": r.username,
            "total_data_gb": float(round((r.total_data or 0) / (1024**3), 2))
        } for r in results]
        return {"top_users": top_users_list}
    except SQLAlchemyError as e:
        return {"error": str(e)}

def find_denied_access(db: Session, start_str: str, end_str: str, username: str = None) -> Dict[str, Any]:
    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_str, '%Y-%m-%d')
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No hay datos para las fechas seleccionadas."}

    where_clause = "response = 403"
    params = {}
    if username:
        where_clause += " AND username = :username"
        params['username'] = username
    results = _execute_union_query(db, tables, where_clause, params, "log_date DESC, username")
    return {"results": [dict(row._mapping) for row in results]}