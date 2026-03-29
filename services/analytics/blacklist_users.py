from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.database import get_dynamic_models, get_engine
from database.models.models import BlacklistDomain


def _blacklist_exists(LogModel):
    """
    Return a correlated EXISTS subquery that is True when any active blacklist
    domain appears as a substring in LogModel.url.

    Runs entirely inside the database engine – avoids passing thousands of LIKE
    parameters from Python and crashing with SQLAlchemy's parameter-limit error.
    """
    return (
        select(BlacklistDomain.id)
        .where(
            BlacklistDomain.active == 1,
            LogModel.url.like(func.concat("%", BlacklistDomain.domain, "%")),
        )
        .correlate(LogModel.__table__)
        .exists()
    )


def _get_parent_domain(url: str) -> str:
    if not url:
        return "unknown"

    u = url.strip().lower()

    # Normalize safe URL forms.
    if not (u.startswith("http://") or u.startswith("https://")):
        maybe = f"http://{u}"
        parsed = urlparse(maybe)
    else:
        parsed = urlparse(u)

    host = parsed.netloc or parsed.path
    host = host.split("/")[0].split(":")[0].strip()
    if host.startswith("www."):
        host = host[4:]

    # Map common services to root domain.
    if "facebook.com" in host or "fb.com" in host:
        return "facebook.com"
    if "instagram.com" in host:
        return "instagram.com"
    if "youtube.com" in host or "ytimg.com" in host:
        return "youtube.com"
    if "twitter.com" in host or "x.com" in host:
        return "twitter.com"
    if "tiktok.com" in host:
        return "tiktok.com"
    if "whatsapp.com" in host:
        return "whatsapp.com"
    if "netflix.com" in host:
        return "netflix.com"

    parts = [p for p in host.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host or "unknown"


def find_blacklisted_sites(
    db: Session, page: int = 1, per_page: int = 10
) -> dict[str, Any]:
    engine = get_engine()
    inspector = inspect(engine)
    # user -> domain -> count
    user_domain_counts: dict[str, dict[str, int]] = {}
    total_requests = 0

    # Early-exit if the blacklist table has no active entries.
    if (
        not db.query(BlacklistDomain)
        .filter(BlacklistDomain.active == 1)
        .limit(1)
        .first()
    ):
        return {
            "results": [],
            "pagination": {
                "total": 0,
                "total_requests": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            },
        }

    try:
        all_tables = inspector.get_table_names()
        log_tables = sorted(
            [
                t
                for t in all_tables
                if t.startswith("log_") and len(t) == 12 and t[4:].isdigit()
            ],
            reverse=True,
        )

        for log_table in log_tables:
            try:
                date_str = log_table.split("_")[1]
                UserModel, LogModel = get_dynamic_models(date_str)
            except Exception as e:
                logger.warning(f"Error getting dynamic models for {date_str}: {e}")
                continue

            blacklist_exists = _blacklist_exists(LogModel)

            query_results = (
                db.query(UserModel.username, LogModel.url, LogModel.request_count)
                .join(UserModel, LogModel.user_id == UserModel.id)
                .filter(blacklist_exists)
                .all()
            )

            for username, url, request_count in query_results:
                domain = _get_parent_domain(url)
                count = request_count or 1
                user_domain_counts.setdefault(username, {})
                user_domain_counts[username][domain] = (
                    user_domain_counts[username].get(domain, 0) + count
                )
                total_requests += count

        # Sort users by total attempts descending
        sorted_users = sorted(
            user_domain_counts.items(),
            key=lambda x: sum(x[1].values()),
            reverse=True,
        )

        total_users = len(sorted_users)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_users = sorted_users[start:end]

        results = []
        for username, domain_counts in paginated_users:
            sorted_domains = sorted(
                domain_counts.items(), key=lambda x: x[1], reverse=True
            )
            for domain, count in sorted_domains:
                results.append({"usuario": username, "domain": domain, "count": count})

    except SQLAlchemyError:
        logger.exception("Database error while searching blacklisted sites")
        return {"error": "Error interno del servidor"}

    return {
        "results": results,
        "pagination": {
            "total": total_users,
            "total_requests": total_requests,
            "page": page,
            "per_page": per_page,
            "total_pages": (total_users + per_page - 1) // per_page,
        },
    }


def find_blacklisted_sites_by_date(db: Session, specific_date: datetime.date):
    results = []

    try:
        date_suffix = specific_date.strftime("%Y%m%d")
        user_table = f"user_{date_suffix}"
        log_table = f"log_{date_suffix}"

        inspector = inspect(db.get_bind())
        if not inspector.has_table(user_table) or not inspector.has_table(log_table):
            return []

        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
        except Exception:
            return []

        blacklist_exists = _blacklist_exists(LogModel)

        query_results = (
            db.query(UserModel.username, LogModel.url)
            .join(UserModel, LogModel.user_id == UserModel.id)
            .filter(blacklist_exists)
            .all()
        )

        formatted_date = specific_date.strftime("%Y-%m-%d")
        for row in query_results:
            results.append(
                {"fecha": formatted_date, "usuario": row.username, "url": row.url}
            )

    except SQLAlchemyError as e:
        logger.error(f"Database error: {e}")

    return results
