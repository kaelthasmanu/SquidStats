from datetime import datetime
from typing import Any

from sqlalchemy import func, inspect, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.database import get_dynamic_models, get_engine


def find_blacklisted_sites(
    db: Session, blacklist: list, page: int = 1, per_page: int = 10
) -> dict[str, Any]:
    engine = get_engine()
    inspector = inspect(engine)
    results = []
    total_results = 0

    try:
        all_tables = inspector.get_table_names()
        # Cambiar logs_ por log_ y ajustar longitud
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

            # Obtener los modelos ORM dinámicos para esta fecha
            try:
                UserModel, LogModel = get_dynamic_models(date_str)
            except Exception as e:
                print(f"Error obteniendo modelos dinámicos para {date_str}: {e}")
                continue

            # Crear condiciones OR para la blacklist usando ORM
            blacklist_conditions = [
                LogModel.url.like(f"%{site}%") for site in blacklist
            ]

            if not count_only:
                # Contar total usando ORM con join explícito
                table_total = (
                    db.query(func.count(LogModel.id))
                    .join(UserModel, LogModel.user_id == UserModel.id)
                    .filter(or_(*blacklist_conditions))
                    .scalar()
                )

                total_results += table_total

                if offset >= table_total:
                    offset -= table_total
                    continue

                # Consulta principal usando ORM con join explícito
                query_results = (
                    db.query(UserModel.username, LogModel.url)
                    .join(UserModel, LogModel.user_id == UserModel.id)
                    .filter(or_(*blacklist_conditions))
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

        # Si es count_only, calcular el total usando ORM
        if count_only:
            total_results = 0
            for log_table in log_tables:
                try:
                    date_str = log_table.split("_")[1]
                    UserModel, LogModel = get_dynamic_models(date_str)
                except Exception as e:
                    print(f"Error obteniendo modelos dinámicos para {date_str}: {e}")
                    continue

                blacklist_conditions = [
                    LogModel.url.like(f"%{site}%") for site in blacklist
                ]

                table_count = (
                    db.query(func.count(LogModel.id))
                    .join(UserModel, LogModel.user_id == UserModel.id)
                    .filter(or_(*blacklist_conditions))
                    .scalar()
                )

                total_results += table_count

    except SQLAlchemyError as e:
        print(f"Error de base de datos: {e}")
        return {"error": str(e)}

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
    db: Session, blacklist: list, specific_date: datetime.date
):
    results = []

    try:
        date_suffix = specific_date.strftime("%Y%m%d")
        user_table = f"user_{date_suffix}"
        log_table = f"log_{date_suffix}"

        # Verificar que las tablas existen
        inspector = inspect(db.get_bind())
        if not inspector.has_table(user_table) or not inspector.has_table(log_table):
            return []

        # Obtener modelos dinámicos
        try:
            UserModel, LogModel = get_dynamic_models(date_suffix)
        except Exception:
            return []

        # Crear condiciones OR para la blacklist usando ORM
        blacklist_conditions = [LogModel.url.like(f"%{site}%") for site in blacklist]

        # Consulta usando ORM con join explícito
        query_results = (
            db.query(UserModel.username, LogModel.url)
            .join(UserModel, LogModel.user_id == UserModel.id)
            .filter(or_(*blacklist_conditions))
            .all()
        )

        formatted_date = specific_date.strftime("%Y-%m-%d")
        for row in query_results:
            results.append(
                {"fecha": formatted_date, "usuario": row.username, "url": row.url}
            )

    except SQLAlchemyError as e:
        print(f"Error de base de datos: {e}")

    return results
