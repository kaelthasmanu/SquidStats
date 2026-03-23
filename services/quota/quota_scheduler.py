import os
from datetime import datetime

from loguru import logger
from sqlalchemy import func
from sqlalchemy import inspect as sqlalchemy_inspect

from database.database import get_dynamic_models, get_session
from database.models.models import QuotaEvent, QuotaGroup, QuotaUser


def register_quota_scheduler_tasks(scheduler):
    """Registra tareas programadas relacionadas con cuotas."""

    @scheduler.task(
        "interval", id="check_quota_users", minutes=1, misfire_grace_time=300
    )
    def check_quota_users():
        try:
            # quota_disabled_flag = os.path.join(os.getcwd(), "quota_disabled")
            # if os.path.exists(quota_disabled_flag):
            # logger.debug("check_quota_users: cuota deshabilitada, omitiendo evaluación")
            # return

            session = get_session()
            file_path = os.path.join(os.getcwd(), "blockUsersQuota")

            blocked_usernames = set()
            if os.path.exists(file_path):
                with open(file_path, encoding="utf-8") as f:
                    for line in f:
                        username_line = line.strip()
                        if not username_line:
                            continue
                        if " - " in username_line:
                            # compatibilidad con viejos formatos
                            parts = username_line.split(" - ")
                            if len(parts) > 1:
                                blocked_usernames.add(parts[1].strip())
                            else:
                                blocked_usernames.add(parts[0].strip())
                        else:
                            blocked_usernames.add(username_line)

            users = session.query(QuotaUser).all()
            # Actualizar used_mb con la suma real desde tablas de logs dinámicas antes de evaluar excedidos
            quota_usernames = [u.username for u in users]
            usage_by_username = {}

            inspector = sqlalchemy_inspect(session.get_bind())
            all_tables = inspector.get_table_names()
            current_month_prefix = datetime.now().strftime("%Y%m")

            for table_name in all_tables:
                if not table_name.startswith("user_"):
                    continue

                suffix = table_name.split("_", 1)[1]
                if not suffix.startswith(current_month_prefix):
                    continue

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
                        func.coalesce(func.sum(LogModel.data_transmitted), 0).label(
                            "total_bytes"
                        ),
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

            # Group quota checking: sumar uso de usuarios por grupo y comparar contra cuota de grupo.
            group_quotas = {
                g.group_name: g.quota_mb for g in session.query(QuotaGroup).all()
            }
            group_usage = {}
            for user in users:
                if user.group_name:
                    group_usage[user.group_name] = group_usage.get(
                        user.group_name, 0
                    ) + (user.used_mb or 0)

            exceeded_groups = [
                group
                for group, total in group_usage.items()
                if group in group_quotas
                and group_quotas[group] > 0
                and total > group_quotas[group]
            ]

            exceeded_users = []
            for user in users:
                if (
                    user.quota_mb
                    and user.used_mb is not None
                    and user.used_mb > user.quota_mb
                ):
                    exceeded_users.append(user)
                elif user.group_name and user.group_name in exceeded_groups:
                    exceeded_users.append(user)

            new_blocked = []
            for user in exceeded_users:
                if user.username not in blocked_usernames:
                    new_blocked.append(user)

            if new_blocked:
                with open(file_path, "a", encoding="utf-8") as f:
                    for user in new_blocked:
                        f.write(f"{user.username}\n")

                for user in new_blocked:
                    if (
                        user.quota_mb
                        and user.used_mb is not None
                        and user.used_mb > user.quota_mb
                    ):
                        event_type = "user_quota_exceeded"
                        detail = f"Cuota de usuario excedida: {user.used_mb}/{user.quota_mb} MB"
                    else:
                        event_type = "group_quota_exceeded"
                        group_quota_value = group_quotas.get(user.group_name, 0)
                        group_total = group_usage.get(user.group_name, 0)
                        detail = (
                            f"Cuota de grupo '{user.group_name}' excedida: "
                            f"{group_total}/{group_quota_value} MB"
                        )

                    event = QuotaEvent(
                        event_type=event_type,
                        username=user.username,
                        group_name=user.group_name
                        if event_type == "group_quota_exceeded"
                        else None,
                        detail=detail,
                    )
                    session.add(event)

            if new_blocked:
                logger.info(
                    f"check_quota_users: {len(new_blocked)} nuevos usuarios con cuota excedida escritos en {file_path}"
                )
            else:
                logger.debug("check_quota_users: ningún usuario nuevo excedió la cuota")

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
