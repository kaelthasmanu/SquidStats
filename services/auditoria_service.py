from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from venv import logger

from sqlalchemy import func, inspect, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.database import get_dynamic_models

SOCIAL_MEDIA_DOMAINS = {
    "YouTube": [
        "youtube.com",
        "ytimg.com",
        "googlevideo.com",
        "yt3.ggpht.com",
        "youtubei.googleapis.com",
        "youtube-ui.l.google.com",
        "youtube.googleapis.com",
    ],
    "Facebook": [
        "facebook.com",
        "fbcdn.net",
        "facebook.net",
        "fbsbx.com",
        "fbpigeon.com",
        "fb.com",
        "facebook-hardware.com",
    ],
    "Pinterest": [
        "pinterest.com",
        "pinimg.com",
        "cdx.cedexis.net",
        "pinterest.net",
        "pinterest.pt",
        "pinterest.cl",
        "pinterest.info",
    ],
    "Instagram": [
        "instagram.com",
        "cdninstagram.com",
        "z-p42-chat-e2ee-ig.facebook.com",
        "mqtt-ig-p4.facebook.com",
        "z-p42-chat-e2ee-ig-fallback.facebook.com",
        "ig.me",
        "instagram.am",
        "igsonar.com",
    ],
    "Telegram": ["telegram.org", "t.me", "telegram.me", "tg.dev", "telesco.pe"],
    "WhatsApp": [
        "whatsapp.net",
        "whatsapp.com",
        "wa.me",
        "wl.co",
        "whatsappbrand.com",
        "whatsapp-plus.info",
        "whatsapp-plus.me",
        "whatsapp-plus.net",
        "whatsapp.cc",
        "whatsapp.info",
        "whatsapp.org",
        "whatsapp.tv",
    ],
    "Twitter/X": [
        "twitter.com",
        "t.co",
        "anuncios-twitter.com",
        "twimg.com",
        "x.com",
        "pscp.tv",
        "twtrdns.net",
        "twttr.com",
        "periscopio.tv",
        "twitpic.com",
        "tweetdeck.com",
        "twitter.co",
        "twitterinc.com",
        "twitteroauth.com",
        "twitterstat.us",
    ],
}


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
            log_tables_in_range.append((log_table))
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
        return {"error": "No hay datos para las fechas seleccionadas."}

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
            print(f"Error procesando tabla {log_table}: {e}")
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
        return {"error": "No hay datos para las fechas seleccionadas."}

    domain_list = []
    for site_name in sites:
        if site_name in SOCIAL_MEDIA_DOMAINS:
            domain_list.extend(SOCIAL_MEDIA_DOMAINS[site_name])
    if not domain_list:
        return {"error": "No se especificaron dominios válidos para la búsqueda."}

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
            print(f"Error procesando tabla {log_table}: {e}")
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
        return {"error": "No hay datos para las fechas seleccionadas."}

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
            print(f"Error procesando tabla {log_table}: {e}")
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
        return {"error": "No hay datos para las fechas seleccionadas."}

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
            print(f"Error procesando tabla {log_table}: {e}")
            continue

    # Ordenar resultados
    all_results.sort(
        key=lambda x: (x["username"], x["log_date"], x["access_count"]), reverse=True
    )

    return {"results": all_results}


def get_daily_activity(db: Session, date_str: str, username: str) -> dict[str, Any]:
    """Calcula el número de peticiones por hora para un usuario en un día específico usando ORM."""
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {"error": "Formato de fecha inválido. Use YYYY-MM-DD."}

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
        print(f"Error en get_daily_activity: {e}")
        return {
            "error": "Ocurrió un error en la base de datos al calcular la actividad diaria."
        }
    except Exception as e:
        print(f"Error general en get_daily_activity: {e}")
        return {"error": "Ocurrió un error inesperado al calcular la actividad diaria."}


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
            print(f"Error procesando tabla {table_name}: {e}")
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
        return {"error": "No hay datos para las fechas seleccionadas."}

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
            print(f"Error procesando tabla {log_table}: {e}")
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
        return {"error": "No hay datos para las fechas seleccionadas."}

    user_data = defaultdict(int)

    for log_table in tables:
        date_suffix = log_table.split("_")[1]
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
            if UserModel is None or LogModel is None:
                continue

            # Usar ORM para obtener datos por usuario
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
            print(f"Error procesando tabla {log_table}: {e}")
            continue

    # Ordenar y limitar resultados
    sorted_users = sorted(user_data.items(), key=lambda x: x[1], reverse=True)[:limit]

    top_users_list = [
        {"username": username, "total_data_gb": float(round(total_data / (1024**3), 2))}
        for username, total_data in sorted_users
    ]

    return {"top_users": top_users_list}


def find_denied_access(
    db: Session, start_str: str, end_str: str, username: str = None
) -> dict[str, Any]:
    start_date = datetime.strptime(start_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_str, "%Y-%m-%d")
    inspector = inspect(db.get_bind())
    tables = _get_tables_in_range(inspector, start_date, end_date)
    if not tables:
        return {"error": "No hay datos para las fechas seleccionadas."}

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
            print(f"Error procesando tabla {log_table}: {e}")
            continue

    # Ordenar resultados
    all_results.sort(key=lambda x: (x["log_date"], x["username"]), reverse=True)

    return {"results": all_results}
