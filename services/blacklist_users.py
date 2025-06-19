import sys
from sqlalchemy import inspect, text, func
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import get_session, get_engine
from typing import Dict, Any, List

def find_blacklisted_sites(
        db: Session,
        blacklist: List[str],
        page: int = 1,
        per_page: int = 10
) -> Dict[str, Any]:
    """
    Busca en todas las tablas de logs las URLs que coinciden con una lista negra.
    Esta función ha sido reestructurada para ser segura, corregir el error de sintaxis SQL
    y calcular la paginación de forma precisa.
    """
    if not blacklist:
        return {'results': [], 'pagination': {'total': 0, 'page': 1, 'per_page': per_page, 'total_pages': 0}}

    engine = get_engine()
    inspector = inspect(engine)
    total_results = 0

    try:
        all_tables = inspector.get_table_names()
        # Filtra para obtener solo tablas de logs y las ordena de más reciente a más antigua
        log_tables = sorted(
            [t for t in all_tables if t.startswith('log_') and len(t) == 12],
            reverse=True
        )

        # --- FASE 1: Calcular el total de resultados de forma segura ---
        # Se construye una condición LIKE parametrizada para evitar inyección SQL.
        like_conditions = ' OR '.join([f"l.url LIKE :pattern{i}" for i in range(len(blacklist))])
        params = {f'pattern{i}': f'%{site}%' for i, site in enumerate(blacklist)}
        
        for log_table in log_tables:
            user_table = f'user_{log_table.split("_")[1]}'
            if user_table not in all_tables:
                continue
            
            # Consulta de conteo segura y parametrizada
            count_query_str = f"""
                SELECT COUNT(*) 
                FROM {log_table} l 
                JOIN {user_table} u ON l.user_id = u.id 
                WHERE {like_conditions}
            """
            count_query = text(count_query_str)
            table_total = db.execute(count_query, params).scalar() or 0
            total_results += table_total

        # --- FASE 2: Obtener los resultados para la página solicitada ---
        results = []
        offset = (page - 1) * per_page
        remaining = per_page

        if offset < total_results:
            for log_table in log_tables:
                if remaining <= 0:
                    break
                
                user_table = f'user_{log_table.split("_")[1]}'
                if user_table not in all_tables:
                    continue
                
                try:
                    date_str = log_table.split('_')[1]
                    formatted_date = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
                except (IndexError, ValueError):
                    continue

                # Contar cuántos resultados hay en esta tabla para saber si debemos buscar aquí
                count_query_str = f"SELECT COUNT(*) FROM {log_table} l JOIN {user_table} u ON l.user_id = u.id WHERE {like_conditions}"
                table_count = db.execute(text(count_query_str), params).scalar() or 0

                if offset < table_count:
                    # Si el offset cae dentro de esta tabla, obtenemos los registros necesarios
                    limit_for_this_query = min(remaining, table_count - offset)
                    
                    paged_query_str = f"""
                        SELECT u.username, l.url 
                        FROM {log_table} l 
                        JOIN {user_table} u ON l.user_id = u.id 
                        WHERE {like_conditions} 
                        ORDER BY l.id DESC
                        LIMIT :limit OFFSET :offset
                    """
                    paged_query = text(paged_query_str)
                    paged_params = {**params, 'limit': limit_for_this_query, 'offset': offset}
                    
                    table_results = db.execute(paged_query, paged_params)
                    for row in table_results:
                        results.append({
                            'fecha': formatted_date,
                            'usuario': row.username,
                            'url': row.url
                        })
                    
                    remaining -= limit_for_this_query
                    offset = 0 # El offset para las siguientes tablas será 0
                else:
                    # Si el offset es mayor, lo restamos para la siguiente tabla
                    offset -= table_count
        
    except SQLAlchemyError as e:
        print(f"Error de base de datos: {e}")
        return {'error': str(e)}

    return {
        'results': results,
        'pagination': {
            'total': total_results,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_results + per_page - 1) // per_page if per_page > 0 else 0
        }
    }


def find_blacklisted_sites_by_date(db: Session, blacklist: list, specific_date: datetime.date):
    """
    Busca en una tabla de una fecha específica las URLs que coinciden con la lista negra.
    """
    results = []
    if not blacklist:
        return results

    try:
        date_suffix = specific_date.strftime("%Y%m%d")
        user_table = f'user_{date_suffix}'
        log_table = f'log_{date_suffix}'

        inspector = inspect(db.get_bind())
        if not inspector.has_table(user_table) or not inspector.has_table(log_table):
            return []

        like_conditions = ' OR '.join([f"l.url LIKE :pattern{i}" for i in range(len(blacklist))])
        query = text(f"""
            SELECT u.username, l.url 
            FROM {log_table} l
            JOIN {user_table} u ON l.user_id = u.id
            WHERE {like_conditions}
            ORDER BY l.id DESC
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