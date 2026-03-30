import threading
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.database import get_dynamic_models, get_engine
from database.models.models import BlacklistDomain

# ---------------------------------------------------------------------------
# Module-level TTL cache
# Stores the fully aggregated result so paginated requests don't recompute.
# ---------------------------------------------------------------------------
_CACHE_TTL = 300  # seconds (5 minutes)
_cache_lock = threading.Lock()
_cache_data: dict | None = None
_cache_time: float = 0.0


def invalidate_blacklist_cache() -> None:
    """Force the next request to recompute aggregations (call after blacklist edits)."""
    global _cache_data, _cache_time
    with _cache_lock:
        _cache_data = None
        _cache_time = 0.0


_BLACKLIST_DOMAIN_THRESHOLD = 50  # if more than this, cap the subquery
_BLACKLIST_DOMAIN_CAP = 25  # number of domains to use when capped


def _blacklist_exists(LogModel, domain_ids: list[int] | None = None):
    """
    Return a correlated EXISTS subquery that is True when any active blacklist
    domain appears as a substring in LogModel.url.

    Runs entirely inside the database engine – avoids passing thousands of LIKE
    parameters from Python and crashing with SQLAlchemy's parameter-limit error.

    When *domain_ids* is provided, only those specific blacklist entries are
    tested — this is the correct way to cap in SQLite, since LIMIT inside a
    correlated EXISTS is silently ignored by SQLite.
    """
    q = (
        select(BlacklistDomain.id)
        .where(
            BlacklistDomain.active == 1,
            LogModel.url.like(func.concat("%", BlacklistDomain.domain, "%")),
        )
        .correlate(LogModel.__table__)
    )
    if domain_ids is not None:
        q = q.where(BlacklistDomain.id.in_(domain_ids))
    return q.exists()


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


def _compute_full_aggregation(
    db: Session,
) -> tuple[dict[str, dict[str, int]], int, bool]:
    """
    Scan all daily log tables and return (user_domain_counts, total_requests, domain_capped).

    Key optimisations vs the naive approach:
    - SQL GROUP BY (username, url) per table  →  far fewer rows transferred to Python.
    - _get_parent_domain() is called only once per distinct (username, url) pair
      instead of once per raw log row.
    """
    engine = get_engine()
    inspector = inspect(engine)
    user_domain_counts: dict[str, dict[str, int]] = {}
    total_requests: int = 0

    all_tables = inspector.get_table_names()
    log_tables = sorted(
        [
            t
            for t in all_tables
            if t.startswith("log_") and len(t) == 12 and t[4:].isdigit()
        ],
        reverse=True,
    )

    # Cap the EXISTS subquery when the blacklist is very large.
    # NOTE: LIMIT inside a correlated EXISTS is silently ignored by SQLite,
    # so we pre-fetch the capped IDs in Python and use id.in_() instead.
    domain_count = (
        db.query(func.count(BlacklistDomain.id))
        .filter(BlacklistDomain.active == 1)
        .scalar()
        or 0
    )
    domain_capped = domain_count > _BLACKLIST_DOMAIN_THRESHOLD
    if domain_capped:
        domain_ids: list[int] | None = [
            row[0]
            for row in (
                db.query(BlacklistDomain.id)
                .filter(BlacklistDomain.active == 1)
                .order_by(BlacklistDomain.id)
                .limit(_BLACKLIST_DOMAIN_CAP)
                .all()
            )
        ]
        logger.debug(
            f"Blacklist has {domain_count} entries — capping EXISTS subquery to {len(domain_ids)} domain IDs"
        )
    else:
        domain_ids = None

    for log_table in log_tables:  # noqa: E501 (loop continues below)
        date_str = log_table[4:]  # "log_YYYYMMDD" → "YYYYMMDD"
        try:
            UserModel, LogModel = get_dynamic_models(date_str)
        except Exception as exc:
            logger.warning(f"Skipping {log_table}: {exc}")
            continue

        blacklist_exists = _blacklist_exists(LogModel, domain_ids=domain_ids)

        # Aggregate at the DB level: one row per distinct (username, url) pair.
        rows = (
            db.query(
                UserModel.username,
                LogModel.url,
                func.sum(LogModel.request_count).label("total"),
            )
            .join(UserModel, LogModel.user_id == UserModel.id)
            .filter(blacklist_exists)
            .group_by(UserModel.username, LogModel.url)
            .all()
        )

        for username, url, total in rows:
            domain = _get_parent_domain(url)
            count = int(total or 1)
            ud = user_domain_counts.setdefault(username, {})
            ud[domain] = ud.get(domain, 0) + count
            total_requests += count

    return user_domain_counts, total_requests, domain_capped


def find_blacklisted_sites(
    db: Session, page: int = 1, per_page: int = 10
) -> dict[str, Any]:
    global _cache_data, _cache_time

    # Early-exit: no active blacklist entries at all.
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

    # --- Cache read ---
    now = time.monotonic()
    with _cache_lock:
        if _cache_data is not None and (now - _cache_time) < _CACHE_TTL:
            sorted_users = _cache_data["sorted_users"]
            total_requests = _cache_data["total_requests"]
            domain_capped = _cache_data["domain_capped"]
        else:
            sorted_users = None

    # --- Cache miss: (re)compute ---
    if sorted_users is None:
        try:
            user_domain_counts, total_requests, domain_capped = (
                _compute_full_aggregation(db)
            )
        except SQLAlchemyError:
            logger.exception("Database error while searching blacklisted sites")
            return {"error": "Error interno del servidor"}

        sorted_users = sorted(
            user_domain_counts.items(),
            key=lambda x: sum(x[1].values()),
            reverse=True,
        )

        with _cache_lock:
            _cache_data = {
                "sorted_users": sorted_users,
                "total_requests": total_requests,
                "domain_capped": domain_capped,
            }
            _cache_time = time.monotonic()

    # --- Paginate in-memory (O(per_page)) ---
    total_users = len(sorted_users)
    start = (page - 1) * per_page
    paginated_users = sorted_users[start : start + per_page]

    results = []
    for username, domain_counts in paginated_users:
        for domain, count in sorted(
            domain_counts.items(), key=lambda x: x[1], reverse=True
        ):
            results.append({"usuario": username, "domain": domain, "count": count})

    return {
        "results": results,
        "domain_capped": domain_capped,
        "domain_cap": _BLACKLIST_DOMAIN_CAP,
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
