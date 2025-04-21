from sqlalchemy import create_engine, func, desc
from sqlalchemy.orm import sessionmaker, Session
import sys
from pathlib import Path

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