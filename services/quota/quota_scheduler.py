import os
from datetime import datetime

from sqlalchemy import func, inspect as sqlalchemy_inspect
from loguru import logger

from database.database import get_dynamic_models, get_session
from database.models.models import QuotaEvent, QuotaUser


def register_quota_scheduler_tasks(scheduler):
    """Registra tareas programadas relacionadas con cuotas."""

    @scheduler.task(
        "interval", id="check_quota_users", minutes=5, misfire_grace_time=300
    )
    def check_quota_users():
        try:
            session = get_session()
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            file_path = os.path.join(os.getcwd(), "blockUsersQuota")
            exceeded = []

            users = session.query(QuotaUser).all()
            # Actualizar used_mb con la suma real desde tablas de logs dinámicas antes de evaluar excedidos
            quota_usernames = [u.username for u in users]
            usage_by_username = {}

            inspector = sqlalchemy_inspect(session.get_bind())
            all_tables = inspector.get_table_names()

            for table_name in all_tables:
                if not table_name.startswith("user_"):
                    continue

                suffix = table_name.split("_", 1)[1]
                log_table_name = f"log_{suffix}"
                if log_table_name not in all_tables:
                    continue

                UserModel, LogModel = get_dynamic_models(suffix)
                if not UserModel or not LogModel:
                    continue

                if not quota_usernames:
                    break

                usage_rows = (
                    session.query(
                        UserModel.username.label("username"),
                        func.coalesce(func.sum(LogModel.data_transmitted), 0).label("total_bytes"),
                    )
                    .join(LogModel, UserModel.id == LogModel.user_id)
                    .filter(UserModel.username.in_(quota_usernames))
                    .group_by(UserModel.username)
                    .all()
                )

                for row in usage_rows:
                    usage_by_username[row.username] = usage_by_username.get(
                        row.username, 0
                    ) + (row.total_bytes or 0)

            for user in users:
                new_mb = int(usage_by_username.get(user.username, 0) / 1024 / 1024)
                user.used_mb = new_mb

            exceeded = []
            for user in users:
                if user.quota_mb and user.used_mb is not None and user.used_mb > user.quota_mb:
                    exceeded.append(user)

            if exceeded:
                with open(file_path, "a", encoding="utf-8") as f:
                    for user in exceeded:
                        line = f"{now} - {user.username} - quota: {user.quota_mb}MB - used: {user.used_mb}MB\n"
                        f.write(line)

                for user in exceeded:
                    event = QuotaEvent(
                        event_type="user_quota_exceeded",
                        username=user.username,
                        detail=f"Cuota excedida: {user.used_mb}/{user.quota_mb} MB",
                    )
                    session.add(event)

                logger.info(
                    f"check_quota_users: {len(exceeded)} usuarios con cuota excedida escritos en {file_path}"
                )
            else:
                logger.debug("check_quota_users: ningún usuario excedió la cuota")

            # Guardar actualizaciones de used_mb y eventos si hay.
            session.commit()

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
