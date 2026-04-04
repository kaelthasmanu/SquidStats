import os
import re
from datetime import datetime
from types import SimpleNamespace

from loguru import logger
from sqlalchemy import func
from sqlalchemy import inspect as sqlalchemy_inspect

from database.database import get_dynamic_models, get_session
from database.models.models import QuotaEvent, QuotaGroup, QuotaUser
from services.quota.quota_service import (
    _sync_blocked_file_to_docker,
    _sync_quota_squid_rules,
)
from services.system.system_service import reload_squid
from utils.admin import SquidConfigManager


def register_quota_scheduler_tasks(scheduler):
    """Registra tareas programadas relacionadas con cuotas."""

    @scheduler.task(
        "interval", id="check_quota_users", minutes=1, misfire_grace_time=300
    )
    def check_quota_users():
        session = None
        try:
            quota_disabled_flag = os.path.join(os.getcwd(), "quota_disabled")
            quota_enabled = not os.path.exists(quota_disabled_flag)
            _sync_quota_squid_rules(quota_enabled)

            # reinicio mensual 1ero del mes
            today = datetime.now().date()
            reset_marker = "/etc/squid/.quota_last_reset"
            try:
                last_reset = ""
                if os.path.exists(reset_marker):
                    with open(reset_marker, encoding="utf-8") as f:
                        last_reset = f.read().strip()
                if today.day == 1 and last_reset != str(today):
                    session_reset = get_session()
                    try:
                        session_reset.query(QuotaUser).update({QuotaUser.used_mb: 0})
                        session_reset.commit()
                        blocked_path = "/etc/squid/usuarios_bloqueados.txt"
                        try:
                            with open(blocked_path, "w", encoding="utf-8") as f:
                                f.write("")
                            _sync_blocked_file_to_docker(blocked_path)
                        except Exception as e:
                            logger.warning(
                                f"No se pudo limpiar archivo de usuarios bloqueados: {e}"
                            )
                        with open(reset_marker, "w", encoding="utf-8") as f:
                            f.write(str(today))
                        logger.info("Reinicio mensual de cuotas ejecutado")
                    except Exception as e:
                        session_reset.rollback()
                        logger.error(f"Error en reinicio mensual de cuotas: {e}")
                    finally:
                        session_reset.close()
            except Exception as e:
                logger.warning(f"Error verificando reinicio mensual de cuotas: {e}")

            if not quota_enabled:
                # logger.debug(
                #     "check_quota_users: cuota deshabilitada, omitiendo evaluación"
                # )
                return

            session = get_session()
            file_path = "/etc/squid/usuarios_bloqueados.txt"

            # Detectar modo para saber el formato del archivo
            cm = SquidConfigManager()
            auth_configured = cm.is_valid and bool(
                re.search(r"^\s*auth_param\b", cm.config_content or "", re.MULTILINE)
                and re.search(
                    r"^\s*acl\s+auth\b", cm.config_content or "", re.MULTILINE
                )
            )
            use_src = not auth_configured

            blocked_usernames = set()
            if os.path.exists(file_path):
                with open(file_path, encoding="utf-8") as f:
                    for line in f:
                        text = line.strip()
                        if not text:
                            continue
                        if use_src:
                            # Formato: acl usuarios_bloqueados src <IP>
                            m = re.match(
                                r"^acl\s+usuarios_bloqueados\s+src\s+(\S+)", text
                            )
                            if m:
                                blocked_usernames.add(m.group(1))
                        else:
                            # Formato plano: username o "algo - username"
                            if " - " in text:
                                parts = text.split(" - ")
                                blocked_usernames.add(
                                    parts[1].strip()
                                    if len(parts) > 1
                                    else parts[0].strip()
                                )
                            else:
                                blocked_usernames.add(text)

            users = session.query(QuotaUser).all()

            # Cuota global "default": si existe un QuotaUser con username="default"
            # y quota_mb > 0, esa cuota aplica a todos los usuarios que no tengan
            # una cuota propia asignada. La cuota individual tiene prioridad.
            default_user = next((u for u in users if u.username == "default"), None)
            default_quota_mb = (
                default_user.quota_mb
                if default_user and default_user.quota_mb > 0
                else 0
            )
            regular_users = [u for u in users if u.username != "default"]

            quota_usernames = [u.username for u in regular_users]
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
                if not quota_usernames and not default_quota_mb:
                    break
                q = session.query(
                    UserModel.username.label("username"),
                    func.coalesce(func.sum(LogModel.data_transmitted), 0).label(
                        "total_bytes"
                    ),
                ).join(LogModel, UserModel.id == LogModel.user_id)
                if not default_quota_mb:
                    # Sin cuota global: solo consultar usuarios con cuota explícita
                    q = q.filter(UserModel.username.in_(quota_usernames))
                usage_rows = q.group_by(UserModel.username).all()
                for row in usage_rows:
                    usage_by_username[row.username] = usage_by_username.get(
                        row.username, 0
                    ) + (row.total_bytes or 0)

            for user in regular_users:
                new_mb = int(usage_by_username.get(user.username, 0) / 1024 / 1024)
                user.used_mb = new_mb

            group_quotas = {
                g.group_name: g.quota_mb for g in session.query(QuotaGroup).all()
            }
            group_usage = {}
            for user in regular_users:
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
            for user in regular_users:
                # La cuota efectiva es la propia del usuario; si no tiene,
                # se usa la cuota global "default" (si está configurada).
                effective_quota = (
                    user.quota_mb
                    if (user.quota_mb and user.quota_mb > 0)
                    else default_quota_mb
                )
                if (
                    effective_quota > 0
                    and user.used_mb is not None
                    and user.used_mb > effective_quota
                ):
                    exceeded_users.append(user)
                elif user.group_name and user.group_name in exceeded_groups:
                    exceeded_users.append(user)

            # Usuarios del log que no están en QuotaUser pero superan la cuota global
            if default_quota_mb > 0:
                known_usernames = {u.username for u in regular_users}
                for username, total_bytes in usage_by_username.items():
                    if username in known_usernames:
                        continue
                    used_mb_val = int(total_bytes / 1024 / 1024)
                    if used_mb_val > default_quota_mb:
                        exceeded_users.append(
                            SimpleNamespace(
                                username=username,
                                used_mb=used_mb_val,
                                quota_mb=default_quota_mb,
                                group_name=None,
                            )
                        )

            new_blocked = []
            for user in exceeded_users:
                if user.username not in blocked_usernames:
                    new_blocked.append(user)

            if new_blocked:
                print(
                    f"[DEBUG] check_quota_users: {len(new_blocked)} nuevos bloqueos; use_src={use_src}"
                )
                with open(file_path, "a", encoding="utf-8") as f:
                    for user in new_blocked:
                        if use_src:
                            line = f"acl usuarios_bloqueados src {user.username}\n"
                            print(
                                f"[DEBUG] appending to blocked file (src): {line.strip()}"
                            )
                            f.write(line)
                        else:
                            line = f"{user.username}\n"
                            print(
                                f"[DEBUG] appending to blocked file (proxy_auth): {line.strip()}"
                            )
                            f.write(line)
                _sync_blocked_file_to_docker(file_path)

                for user in new_blocked:
                    effective_quota = (
                        user.quota_mb
                        if (user.quota_mb and user.quota_mb > 0)
                        else default_quota_mb
                    )
                    if (
                        effective_quota > 0
                        and user.used_mb is not None
                        and user.used_mb > effective_quota
                    ):
                        event_type = "user_quota_exceeded"
                        detail = f"Cuota de usuario excedida: {user.used_mb}/{effective_quota} MB"
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

            session.commit()
        except Exception:
            logger.exception("Error en check_quota_users")
            if session is not None:
                try:
                    session.rollback()
                except Exception as rollback_exc:
                    logger.warning(
                        "Error rolling back session after quota check failure: {}",
                        rollback_exc,
                    )
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception as close_exc:
                    logger.warning(
                        "Error closing session after quota check: {}",
                        close_exc,
                    )
            # else:
            #     logger.debug("check_quota_users: no session creada, no es necesario cerrar")

    @scheduler.task(
        "interval",
        id="reload_squid_if_quota_enabled",
        hours=12,
        misfire_grace_time=600,
    )
    def reload_squid_if_quota_enabled():
        quota_disabled_flag = os.path.join(os.getcwd(), "quota_disabled")
        quota_enabled = not os.path.exists(quota_disabled_flag)

        if not quota_enabled:
            # logger.debug(
            #     "reload_squid_if_quota_enabled: cuota deshabilitada, omitiendo recarga"
            # )
            return

        logger.info(
            "reload_squid_if_quota_enabled: cuota habilitada, ejecutando recarga de squid"
        )
        success, message, _ = reload_squid()
        if success:
            logger.info("reload_squid_if_quota_enabled: %s", message)
        else:
            logger.warning("reload_squid_if_quota_enabled falló: %s", message)
