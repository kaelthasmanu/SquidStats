import sys
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import get_session, User, Log, Base, LogMetadata, get_engine

from typing import Dict, Any


def find_blacklisted_sites(
        db: Session,
        blacklist: list,
        page: int = 1,
        per_page: int = 10
) -> Dict[str, Any]:
    engine = get_engine()
    inspector = inspect(engine)
    results = []
    total_results = 0

    try:
        all_tables = inspector.get_table_names()
        logs_tables = sorted(
            [t for t in all_tables if t.startswith('logs_') and len(t) == 13],
            reverse=True
        )

        offset = (page - 1) * per_page
        remaining = per_page
        count_only = offset >= 1000

        for log_table in logs_tables:
            try:
                date_str = log_table.split('_')[1]
                log_date = datetime.strptime(date_str, "%Y%m%d").date()
                formatted_date = log_date.strftime("%Y-%m-%d")
            except (IndexError, ValueError):
                continue

            user_table = f'users_{date_str}'
            if user_table not in all_tables:
                continue

            like_conditions = ' OR '.join([f"l.url LIKE :pattern{i}" for i in range(len(blacklist))])
            base_query = f"""
                SELECT u.username, l.url 
                FROM {log_table} l
                JOIN {user_table} u ON l.user_id = u.id
                WHERE {like_conditions}
            """

            if not count_only:
                count_query = text(f"SELECT COUNT(*) as total FROM ({base_query})")
                count_params = {f'pattern{i}': f'%{site}%' for i, site in enumerate(blacklist)}
                table_total = db.execute(count_query, count_params).scalar()
                total_results += table_total

                if offset >= table_total:
                    offset -= table_total
                    continue

                query = text(f"{base_query} LIMIT :limit OFFSET :offset")
                params = {
                    **{f'pattern{i}': f'%{site}%' for i, site in enumerate(blacklist)},
                    'limit': remaining,
                    'offset': offset
                }

                result = db.execute(query, params)
                offset = 0

                for row in result:
                    results.append({
                        'fecha': formatted_date,
                        'usuario': row.username,
                        'url': row.url
                    })
                    remaining -= 1
                    if remaining == 0:
                        break

            if remaining == 0:
                break

        if count_only:
            total_query = " + ".join([
                f"(SELECT COUNT(*) FROM {log_table} l JOIN {log_table.replace('logs_', 'users_')} u "
                f"ON l.user_id = u.id WHERE {' OR '.join([f'l.url LIKE \'%{s}%\' ' for s in blacklist])})"
                for log_table in logs_tables
            ])
            total_results = db.execute(text(f"SELECT ({total_query})")).scalar()

    except SQLAlchemyError as e:
        print(f"Error de base de datos: {e}")
        return {'error': str(e)}

    return {
        'results': results,
        'pagination': {
            'total': total_results,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_results + per_page - 1) // per_page
        }
    }


def find_blacklisted_sites_by_date(db: Session, blacklist: list, specific_date: datetime.date):
    results = []

    try:
        date_suffix = specific_date.strftime("%Y%m%d")
        users_table = f'users_{date_suffix}'
        logs_table = f'logs_{date_suffix}'

        inspector = inspect(db.get_bind())
        if not inspector.has_table(users_table) or not inspector.has_table(logs_table):
            return []

        like_conditions = ' OR '.join([f"l.url LIKE :pattern{i}" for i in range(len(blacklist))])
        query = text(f"""
            SELECT u.username, l.url 
            FROM {logs_table} l
            JOIN {users_table} u ON l.user_id = u.id
            WHERE {like_conditions}
        """)

        params = {f'pattern{i}': f'%{site}%' for i, site in enumerate(blacklist)}

        result = db.execute(query, params)

        formatted_date = specific_date.strftime("%Y-%m-%d")
        for row in result:
            results.append({
                'fecha': formatted_date,
                'usuario': row.username,
                'url': row.url
            })

    except SQLAlchemyError as e:
        print(f"Error de base de datos: {e}")

    return results