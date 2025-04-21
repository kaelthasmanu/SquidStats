from sqlalchemy.orm import Session
from typing import List, Dict, Any
import sys
from pathlib import Path

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import get_session, User, Log

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