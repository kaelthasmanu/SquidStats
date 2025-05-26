import datetime
from sqlalchemy import create_engine, func, desc, Column, Integer, String
from sqlalchemy.orm import sessionmaker, Session
import sys
from pathlib import Path
from datetime import datetime

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import get_session, User, Log, Base, LogMetadata

def get_important_metrics(db: Session):
    results = {}

    top_users_by_activity = db.query(
        User.username,
        func.count(Log.id).label('total_visits')
    ).join(Log).group_by(User.username).order_by(desc('total_visits')).limit(20).all()

    results['top_users_by_activity'] = [
        {'username': user[0], 'total_visits': user[1]}
        for user in top_users_by_activity
    ]

    top_users_by_data = db.query(
        User.username,
        func.sum(Log.data_transmitted).label('total_data')
    ).join(Log).group_by(User.username).order_by(desc('total_data')).limit(20).all()

    results['top_users_by_data_transferred'] = [
        {'username': user[0], 'total_data_bytes': user[1]}
        for user in top_users_by_data
    ]

    top_pages = db.query(
        Log.url,
        func.sum(Log.request_count).label('total_requests'),
        func.count(Log.id).label('unique_visits'),
        func.sum(Log.data_transmitted).label('total_data')
    ).group_by(Log.url).order_by(desc('total_requests')).limit(20).all()

    results['top_pages'] = [
        {
            'url': page[0],
            'total_requests': page[1],
            'unique_visits': page[2],
            'total_data_bytes': page[3]
        }
        for page in top_pages
    ]

    top_pages_data = db.query(
        Log.url,
        func.sum(Log.data_transmitted).label('total_data')
    ).group_by(Log.url).order_by(desc('total_data')).limit(20).all()

    results['top_pages_by_data'] = [
        {'url': page[0], 'total_data_bytes': page[1]}
        for page in top_pages_data
    ]

    response_distribution = db.query(
        Log.response,
        func.count(Log.id).label('count')
    ).group_by(Log.response).order_by(desc('count')).all()

    results['http_response_distribution'] = [
        {'response_code': resp[0], 'count': resp[1]}
        for resp in response_distribution
    ]

    users_per_ip = db.query(
        User.ip,
        func.count(User.id).label('user_count'),
        func.group_concat(User.username).label('usernames')
    ).group_by(User.ip).order_by(desc('user_count')).filter(User.ip != None).all()

    results['users_per_ip'] = [
        {'ip': ip[0], 'user_count': ip[1], 'usernames': ip[2]}
        for ip in users_per_ip if ip[1] > 1
    ]

    total_stats = {
        'total_users': db.query(func.count(User.id)).scalar(),
        'total_log_entries': db.query(func.count(Log.id)).scalar(),
        'total_data_transmitted': db.query(func.sum(Log.data_transmitted)).scalar() or 0,
        'total_requests': db.query(func.sum(Log.request_count)).scalar() or 0
    }

    results['total_stats'] = total_stats

    db.close()
    return results


def get_metrics_by_date_range(start_date: str, end_date: str, db_session=None):
    try:
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        raise ValueError("Las fechas deben estar en formato YYYYMMDD")

    if end_dt < start_dt:
        raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio")

    should_close = False
    if db_session is None:
        db = get_session()
        should_close = True
    else:
        db = db_session

    results = {}

    current_dt = start_dt
    all_log_tables = []
    all_user_tables = []

    while current_dt <= end_dt:
        date_str = current_dt.strftime("%Y%m%d")
        all_log_tables.append(f"logs_{date_str}")
        all_user_tables.append(f"users_{date_str}")
        current_dt = current_dt + datetime.timedelta(days=1)


    try:
        queries = []
        for user_table in all_user_tables:
            if has_table(db, user_table):
                user_cls = get_table_class(user_table, Base)
                log_cls = get_table_class(f"logs_{user_table.split('_')[1]}", Base)

                query = db.query(
                    user_cls.username,
                    func.count(log_cls.id).label('total_visits')
                ).join(log_cls).group_by(user_cls.username)
                queries.append(query)

        if queries:
            union_query = queries[0]
            for q in queries[1:]:
                union_query = union_query.union(q)

            top_users_by_activity = union_query.order_by(desc('total_visits')).limit(20).all()

            results['top_users_by_activity'] = [
                {'username': user[0], 'total_visits': user[1]}
                for user in top_users_by_activity
            ]

        queries = []
        for user_table in all_user_tables:
            if has_table(db, user_table):
                user_cls = get_table_class(user_table, Base)
                log_cls = get_table_class(f"logs_{user_table.split('_')[1]}", Base)

                query = db.query(
                    user_cls.username,
                    func.sum(log_cls.data_transmitted).label('total_data')
                ).join(log_cls).group_by(user_cls.username)
                queries.append(query)

        if queries:
            union_query = queries[0]
            for q in queries[1:]:
                union_query = union_query.union(q)

            top_users_by_data = union_query.order_by(desc('total_data')).limit(20).all()

            results['top_users_by_data_transferred'] = [
                {'username': user[0], 'total_data_bytes': user[1]}
                for user in top_users_by_data
            ]

        queries = []
        for log_table in all_log_tables:
            if has_table(db, log_table):
                log_cls = get_table_class(log_table, Base)

                query = db.query(
                    log_cls.url,
                    func.sum(log_cls.request_count).label('total_requests'),
                    func.count(log_cls.id).label('unique_visits'),
                    func.sum(log_cls.data_transmitted).label('total_data')
                ).group_by(log_cls.url)
                queries.append(query)

        if queries:
            union_query = queries[0]
            for q in queries[1:]:
                union_query = union_query.union_all(q)

            subq = union_query.subquery()

            top_pages = db.query(
                subq.c.url,
                func.sum(subq.c.total_requests).label('total_requests'),
                func.sum(subq.c.unique_visits).label('unique_visits'),
                func.sum(subq.c.total_data).label('total_data')
            ).group_by(subq.c.url).order_by(desc('total_requests')).limit(20).all()

            results['top_pages'] = [
                {
                    'url': page[0],
                    'total_requests': page[1],
                    'unique_visits': page[2],
                    'total_data_bytes': page[3]
                }
                for page in top_pages
            ]


        if queries:
            subq = union_query.subquery()

            top_pages_data = db.query(
                subq.c.url,
                func.sum(subq.c.total_data).label('total_data')
            ).group_by(subq.c.url).order_by(desc('total_data')).limit(20).all()

            results['top_pages_by_data'] = [
                {'url': page[0], 'total_data_bytes': page[1]}
                for page in top_pages_data
            ]

        queries = []
        for log_table in all_log_tables:
            if has_table(db, log_table):
                log_cls = get_table_class(log_table, Base)

                query = db.query(
                    log_cls.response,
                    func.count(log_cls.id).label('count')
                ).group_by(log_cls.response)
                queries.append(query)

        if queries:
            union_query = queries[0]
            for q in queries[1:]:
                union_query = union_query.union_all(q)

            subq = union_query.subquery()

            response_distribution = db.query(
                subq.c.response,
                func.sum(subq.c.count).label('count')
            ).group_by(subq.c.response).order_by(desc('count')).all()

            results['http_response_distribution'] = [
                {'response_code': resp[0], 'count': resp[1]}
                for resp in response_distribution
            ]

        queries = []
        for user_table in all_user_tables:
            if has_table(db, user_table):
                user_cls = get_table_class(user_table, Base)

                query = db.query(
                    user_cls.ip,
                    func.count(user_cls.id).label('user_count'),
                    func.group_concat(user_cls.username).label('usernames')
                ).group_by(user_cls.ip).filter(user_cls.ip != None)
                queries.append(query)

        if queries:
            union_query = queries[0]
            for q in queries[1:]:
                union_query = union_query.union_all(q)

            subq = union_query.subquery()

            users_per_ip = db.query(
                subq.c.ip,
                func.sum(subq.c.user_count).label('user_count'),
                func.group_concat(subq.c.usernames).label('usernames')
            ).group_by(subq.c.ip).order_by(desc('user_count')).all()

            results['users_per_ip'] = [
                {'ip': ip[0], 'user_count': ip[1], 'usernames': ip[2]}
                for ip in users_per_ip if ip[1] > 1
            ]

        total_stats = {
            'total_users': 0,
            'total_log_entries': 0,
            'total_data_transmitted': 0,
            'total_requests': 0
        }

        queries = []
        for user_table in all_user_tables:
            if has_table(db, user_table):
                user_cls = get_table_class(user_table, Base)
                queries.append(db.query(func.count(user_cls.id)))

        if queries:
            total_users = sum(q.scalar() or 0 for q in queries)
            total_stats['total_users'] = total_users

        queries_log_entries = []
        queries_data = []
        queries_requests = []

        for log_table in all_log_tables:
            if has_table(db, log_table):
                log_cls = get_table_class(log_table, Base)
                queries_log_entries.append(db.query(func.count(log_cls.id)))
                queries_data.append(db.query(func.sum(log_cls.data_transmitted)))
                queries_requests.append(db.query(func.sum(log_cls.request_count)))

        if queries_log_entries:
            total_stats['total_log_entries'] = sum(q.scalar() or 0 for q in queries_log_entries)
            total_stats['total_data_transmitted'] = sum(q.scalar() or 0 for q in queries_data)
            total_stats['total_requests'] = sum(q.scalar() or 0 for q in queries_requests)

        results['total_stats'] = total_stats

    finally:
        if should_close:
            db.close()

    return results


def has_table(db: Session, table_name: str) -> bool:
    return db.execute(
        f"SELECT 1 FROM information_schema.tables WHERE table_name = '{table_name}'"
    ).scalar() is not None


def get_table_class(table_name: str, base) -> type:
    class_dict = {'__tablename__': table_name}

    if table_name.startswith('users_'):
        class_dict.update({
            'id': Column(Integer, primary_key=True),
            'username': Column(String),
            'ip': Column(String),
        })
    elif table_name.startswith('logs_'):
        class_dict.update({
            'id': Column(Integer, primary_key=True),
            'user_id': Column(Integer),
            'url': Column(String),
            'response': Column(Integer),
            'data_transmitted': Column(Integer),
            'request_count': Column(Integer),
        })

    return type(table_name, (base,), class_dict)

# Obtener métricas para un rango específico
#metrics = get_metrics_by_date_range("20230101", "20230131")
#print(metrics)