import datetime
from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import Column, Integer, String, desc, extract, func, inspect
from sqlalchemy.orm import Session, relationship

from database.database import get_concat_function, get_dynamic_models
from database.models.models import DeniedLog


def _extract_domain_from_url(url: str | None) -> str | None:
    """Return a normalized hostname for an absolute or scheme-less URL."""
    try:
        if not url or url == "-":
            return None

        candidate = url if "://" in url or url.startswith("//") else f"//{url}"
        hostname = urlparse(candidate, scheme="http").hostname
        if not hostname:
            return None

        # www is normally an alias of the same destination and would otherwise
        # split its activity across two rows in the report.
        return hostname.lower().rstrip(".").removeprefix("www.")
    except (TypeError, ValueError):
        return None


def _extract_country_from_url(url: str) -> str:
    try:
        hostname = _extract_domain_from_url(url) or ""
        labels = hostname.lower().split(".")
        if len(labels) < 2:
            return "Otros"

        if labels[-1] == "uk" and labels[-2] in {
            "co",
            "me",
            "org",
            "net",
            "sch",
            "gov",
            "ac",
            "ltd",
            "plc",
            "police",
            "mod",
        }:
            return "UK"

        tld = labels[-1]
        if len(tld) == 2:
            return tld.upper()

        return "Global"
    except Exception:
        return "Otros"


def get_important_metrics(
    db: Session,
    UserModel,
    LogModel,
    report_date: datetime.date | None = None,
):
    """Build the daily activity, quality, and destination metrics for reports."""
    results = {}

    try:
        request_count = func.coalesce(LogModel.request_count, 0)

        # 1. Usuarios más activos (por número de visitas)
        top_users_by_activity = (
            db.query(
                UserModel.username,
                func.coalesce(func.sum(request_count), 0).label("total_visits"),
            )
            .join(LogModel, UserModel.id == LogModel.user_id)
            .group_by(UserModel.username)
            .order_by(desc("total_visits"))
            .limit(20)
            .all()
        )

        results["top_users_by_activity"] = [
            {"username": user[0], "total_visits": user[1]}
            for user in top_users_by_activity
        ]

        # 2. Usuarios que más datos transfirieron
        top_users_by_data = (
            db.query(
                UserModel.username,
                func.coalesce(func.sum(LogModel.data_transmitted), 0).label(
                    "total_data"
                ),
            )
            .join(LogModel, UserModel.id == LogModel.user_id)
            .group_by(UserModel.username)
            .order_by(desc("total_data"))
            .limit(20)
            .all()
        )

        results["top_users_by_data_transferred"] = [
            {"username": user[0], "total_data_bytes": user[1]}
            for user in top_users_by_data
        ]

        # 3. Páginas más visitadas
        top_pages = (
            db.query(
                LogModel.url,
                func.coalesce(func.sum(request_count), 0).label("total_requests"),
                func.count(func.distinct(LogModel.user_id)).label("unique_visits"),
                func.coalesce(func.sum(LogModel.data_transmitted), 0).label(
                    "total_data"
                ),
            )
            .group_by(LogModel.url)
            .order_by(desc("total_requests"))
            .limit(20)
            .all()
        )

        results["top_pages"] = [
            {
                "url": page[0],
                "total_requests": page[1],
                "unique_visits": page[2],
                "total_data_bytes": page[3],
            }
            for page in top_pages
        ]

        # 4. Páginas por volumen de datos
        top_pages_data = (
            db.query(
                LogModel.url,
                func.coalesce(func.sum(LogModel.data_transmitted), 0).label(
                    "total_data"
                ),
            )
            .group_by(LogModel.url)
            .order_by(desc("total_data"))
            .limit(20)
            .all()
        )

        results["top_pages_by_data"] = [
            {"url": page[0], "total_data_bytes": page[1]} for page in top_pages_data
        ]

        # 5. Destinos agrupados por dominio y TLD (no geolocalización real).
        country_counts = Counter()
        domain_totals = {}
        destinations_by_requests = (
            db.query(
                LogModel.url,
                func.coalesce(func.sum(request_count), 0).label("total_requests"),
                func.coalesce(func.sum(LogModel.data_transmitted), 0).label(
                    "total_data"
                ),
            )
            .group_by(LogModel.url)
            .order_by(desc("total_requests"))
            .all()
        )
        for url, total_requests, total_data in destinations_by_requests:
            request_total = int(total_requests or 0)
            data_total = int(total_data or 0)
            country = _extract_country_from_url(url)
            country_counts[country] += request_total

            domain = _extract_domain_from_url(url)
            if domain:
                stats = domain_totals.setdefault(
                    domain, {"total_requests": 0, "total_data_bytes": 0}
                )
                stats["total_requests"] += request_total
                stats["total_data_bytes"] += data_total

        results["top_countries_by_visits"] = [
            {"country": country, "total_requests": count}
            for country, count in country_counts.most_common(10)
        ]
        results["top_domains"] = [
            {
                "domain": domain,
                "total_requests": stats["total_requests"],
                "total_data_bytes": stats["total_data_bytes"],
            }
            for domain, stats in sorted(
                domain_totals.items(),
                key=lambda item: (-item[1]["total_requests"], item[0]),
            )[:20]
        ]

        # 6. Distribución de códigos HTTP
        response_distribution = (
            db.query(
                LogModel.response,
                func.coalesce(func.sum(request_count), 0).label("count"),
            )
            .group_by(LogModel.response)
            .order_by(desc("count"))
            .all()
        )

        results["http_response_distribution"] = [
            {"response_code": resp[0], "count": resp[1]}
            for resp in response_distribution
        ]

        # 7. Actividad por hora, con las 24 horas presentes incluso sin tráfico.
        hour_expression = extract("hour", LogModel.created_at)
        hourly_rows = (
            db.query(
                hour_expression.label("hour"),
                func.coalesce(func.sum(request_count), 0).label("requests"),
                func.coalesce(func.sum(LogModel.data_transmitted), 0).label(
                    "data_bytes"
                ),
            )
            .group_by(hour_expression)
            .order_by(hour_expression)
            .all()
        )
        hourly_totals = {}
        for hour, requests, data_bytes in hourly_rows:
            if hour is None:
                continue
            hour_number = int(hour)
            if 0 <= hour_number <= 23:
                hourly_totals[hour_number] = {
                    "requests": int(requests or 0),
                    "data_bytes": int(data_bytes or 0),
                }

        results["hourly_activity"] = [
            {
                "hour": hour,
                "requests": hourly_totals.get(hour, {}).get("requests", 0),
                "data_bytes": hourly_totals.get(hour, {}).get("data_bytes", 0),
            }
            for hour in range(24)
        ]

        # 8. Usuarios por IP
        users_per_ip = (
            db.query(
                UserModel.ip,
                func.count(UserModel.id).label("user_count"),
                get_concat_function(UserModel.username).label("usernames"),
            )
            .group_by(UserModel.ip)
            .order_by(desc("user_count"))
            .filter(UserModel.ip is not None)
            .all()
        )

        results["users_per_ip"] = [
            {"ip": ip[0], "user_count": ip[1], "usernames": ip[2]}
            for ip in users_per_ip
            if ip[1] > 1
        ]

        # 9. Estadísticas globales y de calidad HTTP.
        total_requests = (
            db.query(func.coalesce(func.sum(request_count), 0)).scalar() or 0
        )
        total_data_transmitted = (
            db.query(func.coalesce(func.sum(LogModel.data_transmitted), 0)).scalar()
            or 0
        )
        total_stats = {
            "total_users": db.query(
                func.count(func.distinct(UserModel.username))
            ).scalar()
            or 0,
            "total_log_entries": db.query(func.count(LogModel.id)).scalar() or 0,
            "total_data_transmitted": total_data_transmitted,
            "total_requests": total_requests,
        }

        results["total_stats"] = total_stats

        response_families = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        for response_code, count in response_distribution:
            try:
                family = f"{int(response_code) // 100}xx"
            except (TypeError, ValueError):
                continue
            if family in response_families:
                response_families[family] += int(count or 0)

        success_requests = response_families["2xx"]
        redirect_requests = response_families["3xx"]
        client_error_requests = response_families["4xx"]
        server_error_requests = response_families["5xx"]
        error_requests = client_error_requests + server_error_requests
        results["http_response_families"] = response_families
        results["success_requests"] = success_requests
        results["redirect_requests"] = redirect_requests
        results["client_error_requests"] = client_error_requests
        results["server_error_requests"] = server_error_requests
        results["error_requests"] = error_requests
        results["successful_request_rate"] = (
            success_requests * 100 / total_requests if total_requests else 0
        )
        results["error_request_rate"] = (
            error_requests * 100 / total_requests if total_requests else 0
        )
        results["average_data_per_request"] = (
            total_data_transmitted / total_requests if total_requests else 0
        )
        results["unique_domains"] = len(domain_totals)

        peak_candidates = [
            item for item in results["hourly_activity"] if item["requests"]
        ]
        results["peak_hour"] = (
            max(
                peak_candidates,
                key=lambda item: (
                    item["requests"],
                    item["data_bytes"],
                    -item["hour"],
                ),
            )
            if peak_candidates
            else {"hour": 0, "requests": 0, "data_bytes": 0}
        )

        results["blocked_requests"] = 0
        results["blocked_users"] = 0
        results["blocked_ips"] = 0
        results["blocked_request_rate"] = 0
        if report_date:
            day_start = datetime.datetime.combine(report_date, datetime.time.min)
            day_end = day_start + datetime.timedelta(days=1)
            try:
                blocked_requests, blocked_users, blocked_ips = (
                    db.query(
                        func.count(DeniedLog.id),
                        func.count(func.distinct(DeniedLog.username)),
                        func.count(func.distinct(DeniedLog.ip)),
                    )
                    .filter(
                        DeniedLog.created_at >= day_start,
                        DeniedLog.created_at < day_end,
                    )
                    .one()
                )
                results["blocked_requests"] = int(blocked_requests or 0)
                results["blocked_users"] = int(blocked_users or 0)
                results["blocked_ips"] = int(blocked_ips or 0)
                total_attempts = total_requests + results["blocked_requests"]
                results["blocked_request_rate"] = (
                    results["blocked_requests"] * 100 / total_attempts
                    if total_attempts
                    else 0
                )
            except Exception:
                # A report remains useful even if an older database is missing
                # the optional denied-log table.
                logger.exception("Unable to load blocked-request metrics")

        return results

    except Exception:
        # Log error but return empty structure

        logger.exception("Error in get_important_metrics")
        return {}


def get_metrics_by_date_range(start_date: str, end_date: str, db: Session):
    try:
        # Convert string to datetime objects
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        raise ValueError("Dates must be in YYYYMMDD format")

    if end_dt < start_dt:
        raise ValueError("End date cannot be earlier than start date")

    # Preparar contenedores para resultados consolidados
    consolidated_results = {
        "top_users_by_activity": {},
        "top_users_by_data_transferred": {},
        "top_pages": {},
        "top_pages_by_data": {},
        "http_response_distribution": {},
        "users_per_ip": {},
        "total_stats": {
            "total_users": 0,
            "total_log_entries": 0,
            "total_data_transmitted": 0,
            "total_requests": 0,
        },
    }

    # Iterar por cada día en el rango
    current_dt = start_dt
    while current_dt <= end_dt:
        date_suffix = current_dt.strftime("%Y%m%d")
        try:
            # Obtener modelos dinámicos para esta fecha
            UserModel, LogModel = get_dynamic_models(date_suffix)

            # Verificar existencia de tablas
            if not has_table(db, UserModel.__tablename__) or not has_table(
                db, LogModel.__tablename__
            ):
                print(f"Tables not found for {date_suffix}, skipping...")
                current_dt += timedelta(days=1)
                continue

            # Obtener métricas para esta fecha
            daily_metrics = get_important_metrics(db, UserModel, LogModel)

            # Consolidar estadísticas totales
            if "total_stats" in daily_metrics:
                stats = daily_metrics["total_stats"]
                consolidated_results["total_stats"]["total_users"] += stats.get(
                    "total_users", 0
                )
                consolidated_results["total_stats"]["total_log_entries"] += stats.get(
                    "total_log_entries", 0
                )
                consolidated_results["total_stats"]["total_data_transmitted"] += (
                    stats.get("total_data_transmitted", 0)
                )
                consolidated_results["total_stats"]["total_requests"] += stats.get(
                    "total_requests", 0
                )

            # Lógica de consolidación para otras métricas iría aquí
            # ...

            current_dt += timedelta(days=1)
        except Exception:
            logger.exception(f"Error processing date {date_suffix}")
            current_dt += timedelta(days=1)

    return consolidated_results


def has_table(db: Session, table_name: str) -> bool:
    try:
        # Usar el inspector para verificar existencia de tabla
        inspector = inspect(db.get_bind())
        return inspector.has_table(table_name)
    except Exception:
        logger.exception(f"Error checking table {table_name}")
        return False


def get_table_class(table_name: str, base) -> type:
    class_dict = {"__tablename__": table_name}

    # Modelo para tablas de usuarios
    if table_name.startswith("users_"):
        class_dict.update(
            {
                "id": Column(Integer, primary_key=True),
                "username": Column(String),
                "ip": Column(String),
                # Relación con logs para joins automáticos
                "logs": relationship(
                    "LogDynamic",
                    back_populates="user",
                    lazy="dynamic",  # Optimiza carga de relaciones
                ),
            }
        )
    # Modelo para tablas de logs
    elif table_name.startswith("logs_"):
        class_dict.update(
            {
                "id": Column(Integer, primary_key=True),
                "user_id": Column(Integer),
                "url": Column(String),
                "response": Column(Integer),
                "data_transmitted": Column(Integer),
                "request_count": Column(Integer),
                # Relación con usuario para joins automáticos
                "user": relationship(
                    "UserDynamic",
                    back_populates="logs",
                    lazy="joined",  # Carga inmediata para optimización
                ),
            }
        )

    return type(table_name, (base,), class_dict)
