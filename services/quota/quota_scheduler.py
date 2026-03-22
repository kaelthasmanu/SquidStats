import os
from datetime import datetime
from loguru import logger

from database.database import get_session
from database.models.models import QuotaEvent, QuotaUser


def register_quota_scheduler_tasks(scheduler):
    """Registra tareas programadas relacionadas con cuotas."""

    @scheduler.task("interval", id="check_quota_users", minutes=5, misfire_grace_time=300)
    def check_quota_users():
        try:
            session = get_session()
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            file_path = os.path.join(os.getcwd(), "blockUsersQuota")
            exceeded = []

            users = session.query(QuotaUser).all()
            for user in users:
                if user.quota_mb and user.used_mb is not None and user.used_mb > user.quota_mb:
                    exceeded.append(user)

            if exceeded:
                with open(file_path, "a", encoding="utf-8") as f:
                    for user in exceeded:
                        line = (
                            f"{now} - {user.username} - quota: {user.quota_mb}MB - used: {user.used_mb}MB\n"
                        )
                        f.write(line)

                for user in exceeded:
                    event = QuotaEvent(
                        event_type="user_quota_exceeded",
                        username=user.username,
                        detail=f"Cuota excedida: {user.used_mb}/{user.quota_mb} MB",
                    )
                    session.add(event)
                session.commit()

                logger.info(
                    f"check_quota_users: {len(exceeded)} usuarios con cuota excedida escritos en {file_path}"
                )
            else:
                logger.debug("check_quota_users: ningún usuario excedió la cuota")

        except Exception as e:
            logger.error(f"Error en check_quota_users: {e}")
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            try:
                session.close()
            except Exception:
                pass
