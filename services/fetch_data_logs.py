from sqlalchemy.orm import Session
from typing import List, Dict, Any
from sqlalchemy import inspect, text
import sys
from pathlib import Path

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import User, Log

def get_users_with_logs_optimized(db: Session) -> List[Dict[str, Any]]:
    try:
        users = db.query(User).filter(User.username != "-").all()

        users_data = []
        for user in users:
            logs = db.query(Log).filter(Log.user_id == user.id).all()

            total_requests = sum(log.request_count for log in logs)
            total_data = sum(log.data_transmitted for log in logs)

            user_dict = {
                "user_id": user.id,
                "username": user.username,
                "ip": user.ip,
                "logs": [{
                    "url": log.url,
                    "response": log.response,
                    "request_count": log.request_count,
                    "data_transmitted": log.data_transmitted
                } for log in logs],
                "total_requests": total_requests,
                "total_data": total_data
            }

            users_data.append(user_dict)

        return users_data
    except Exception as e:
        print(f"Error en get_users_with_logs_optimized: {e}")
        raise
    finally:
        db.close()


def get_users_with_logs_by_date(db: Session, date_suffix: str):
    try:
        users_table = f'users_{date_suffix}'
        logs_table = f'logs_{date_suffix}'

        # Corregir aquí (usar get_bind())
        inspector = inspect(db.get_bind())

        if not inspector.has_table(users_table) or not inspector.has_table(logs_table):
            return []

        # Corregir consultas (remover .session)
        users = db.query(User). \
            with_entities(
            User.id,
            User.username,
            User.ip
        ). \
            from_statement(text(f'SELECT * FROM {users_table}')).all()

        users_data = []
        for user in users:
            logs = db.query(Log). \
                with_entities(
                Log.url,
                Log.response,
                Log.request_count,
                Log.data_transmitted
            ). \
                from_statement(text(f'SELECT * FROM {logs_table} WHERE user_id = :user_id')). \
                params(user_id=user.id).all()


            total_requests = sum(log.request_count for log in logs)
            total_data = sum(log.data_transmitted for log in logs)

            users_data.append({
                "user_id": user.id,
                "username": user.username,
                "ip": user.ip,
                "logs": [{
                    "url": log.url,
                    "response": log.response,
                    "request_count": log.request_count,
                    "data_transmitted": log.data_transmitted
                } for log in logs],
                "total_requests": total_requests,
                "total_data": total_data
            })

        return users_data
    except Exception as e:
        print(f"Error en get_users_with_logs_by_date: {e}")
        raise