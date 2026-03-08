from datetime import datetime
from typing import Any

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


def find_blacklisted_sites(
    db: Session, page: int = 1, per_page: int = 10
) -> dict[str, Any]:
    engine = get_engine()
    inspector = inspect(engine)
    results = []
    total_results = 0

    # Early-exit if the blacklist table has no active entries.
    if not db.query(BlacklistDomain).filter(BlacklistDomain.active == 1).limit(1).first():
        return {
            "results": [],
            "pagination": {
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            },
        }

    try:
        all_tables = inspector.get_table_names()
        log_tables = sorted(
            [t for t in all_tables if t.startswith("log_") and len(t) == 12],
            reverse=True,
        )

        offset = (page - 1) * per_page
        remaining = per_page
        count_only = offset >= 1000

        for log_table in log_tables:
            try:
                date_str = log_table.split("_")[1]
                log_date = datetime.strptime(date_str, "%Y%m%d").date()
                formatted_date = log_date.strftime("%Y-%m-%d")
            except (IndexError, ValueError):
                continue

            user_table = f"user_{date_str}"
            if user_table not in all_tables:
                continue

            try:
                UserModel, LogModel = get_dynamic_models(date_str)
            except Exception as e:
                logger.warning(f"Error getting dynamic models for {date_str}: {e}")
                continue

            blacklist_exists = _blacklist_exists(LogModel)

            if not count_only:
                table_total = (
                    db.query(func.count(LogModel.id))
                    .join(UserModel, LogModel.user_id == UserModel.id)
                    .filter(blacklist_exists)
                    .scalar()
                )

                total_results += table_total

                if offset >= table_total:
                    offset -= table_total
                    continue

                query_results = (
                    db.query(UserModel.username, LogModel.url)
                    .join(UserModel, LogModel.user_id == UserModel.id)
                    .filter(blacklist_exists)
                    .offset(offset)
                    .limit(remaining)
                    .all()
                )

                offset = 0

                for row in query_results:
                    results.append(
                        {
                            "fecha": formatted_date,
                            "usuario": row.username,
                            "url": row.url,
                        }
                    )
                    remaining -= 1
                    if remaining == 0:
                        break

            if remaining == 0:
                break

        if count_only:
            total_results = 0
            for log_table in log_tables:
                try:
                    date_str = log_table.split("_")[1]
                    UserModel, LogModel = get_dynamic_models(date_str)
                except Exception as e:
                    logger.warning(f"Error getting dynamic models for {date_str}: {e}")
                    continue

                blacklist_exists = _blacklist_exists(LogModel)

                table_count = (
                    db.query(func.count(LogModel.id))
                    .join(UserModel, LogModel.user_id == UserModel.id)
                    .filter(blacklist_exists)
                    .scalar()
                )

                total_results += table_count

    except SQLAlchemyError:
        logger.exception("Database error while searching blacklisted sites")
        return {"error": "Error interno del servidor"}

    return {
        "results": results,
        "pagination": {
            "total": total_results,
            "page": page,
            "per_page": per_page,
            "total_pages": (total_results + per_page - 1) // per_page,
        },
    }


def find_blacklisted_sites_by_date(
    db: Session, specific_date: datetime.date
):
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
