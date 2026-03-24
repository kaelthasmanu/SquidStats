import os
import re
from datetime import datetime

from loguru import logger
from sqlalchemy import func
from sqlalchemy import inspect as sqlalchemy_inspect

from database.database import get_dynamic_models, get_session
from database.models.models import QuotaEvent, QuotaGroup, QuotaUser
from services.squid.squid_config_splitter import SquidConfigSplitter
from services.system.system_service import reload_squid
from utils.admin import SquidConfigManager


def _commit_modular_config(cm: SquidConfigManager, filename: str, lines: list[str]):
    content = "\n".join(line for line in lines if line.strip() != "")
    return cm.save_modular_config(filename, content)


def _sync_quota_squid_rules(enabled: bool):
    """Sync `usuarios_bloqueados` ACL/http_access in Squid config."""
    cm = SquidConfigManager()
    if not cm.is_valid:
        logger.warning(
            "SquidConfigManager no válido: no se puede sincronizar reglas de cuota"
        )
        return

    blocked_path = "/etc/squid/usuarios_bloqueados.txt"
    try:
        if not os.path.exists(blocked_path):
            open(blocked_path, "a", encoding="utf-8").close()
            os.chmod(blocked_path, 0o777)
            logger.info("Creado archivo de usuarios bloqueados: %s", blocked_path)
        else:
            os.chmod(blocked_path, 0o777)
    except Exception as e:
        logger.error(
            "No se pudo crear/ajustar permisos de %s: %s", blocked_path, e
        )

    def _normalize_line(line: str) -> str:
        return line.strip().split("#")[0].strip()

    def _is_acl_line(line: str) -> bool:
        text = _normalize_line(line)
        return text.startswith("acl usuarios_bloqueados")

    def _is_http_line(line: str) -> bool:
        text = _normalize_line(line)
        return text.startswith("http_access deny usuarios_bloqueados")

    def _build_acl_line(use_src: bool) -> str:
        if use_src:
            return f"acl usuarios_bloqueados src \"{blocked_path}\""
        return f"acl usuarios_bloqueados proxy_auth -i \"{blocked_path}\""

    auth_configured = bool(
        re.search(r"^\s*auth_param\b", cm.config_content, re.MULTILINE)
        and re.search(r"^\s*acl\s+auth\b", cm.config_content, re.MULTILINE)
    )

    use_src = not auth_configured
    acl_line = _build_acl_line(use_src)
    http_line = "http_access deny usuarios_bloqueados"

    def _apply_changes(acl_line: str, http_line: str) -> bool:
        previous_main_content = cm.config_content or ""
        previous_acls_content = ""
        previous_http_content = ""
        config_changed = False

        try:
            if cm.is_modular:
                previous_acls_content = cm.read_modular_config("100_acls.conf") or ""
                previous_http_content = cm.read_modular_config("120_http_access.conf") or ""

                acls_content = previous_acls_content
                acl_lines = [line for line in acls_content.split("\n") if line.strip() != ""]
                original_acl_lines = acl_lines.copy()

                if enabled:
                    if not any(_is_acl_line(line) for line in acl_lines):
                        inserted = False
                        for i, line in enumerate(acl_lines):
                            if line.strip().startswith("acl "):
                                acl_lines.insert(i, acl_line)
                                inserted = True
                                break
                        if not inserted:
                            acl_lines.append(acl_line)
                else:
                    acl_lines = [line for line in acl_lines if not _is_acl_line(line)]

                if acl_lines != original_acl_lines:
                    config_changed = True

                if not _commit_modular_config(cm, "100_acls.conf", acl_lines):
                    raise RuntimeError("No se pudieron guardar 100_acls.conf")

                http_content = previous_http_content
                http_lines = [line for line in http_content.split("\n") if line.strip() != ""]
                original_http_lines = http_lines.copy()

                if enabled:
                    if not any(_is_http_line(line) for line in http_lines):
                        inserted = False
                        for i, line in enumerate(http_lines):
                            if line.strip().startswith("http_access "):
                                http_lines.insert(i, http_line)
                                inserted = True
                                break
                        if not inserted:
                            http_lines.append(http_line)
                else:
                    http_lines = [line for line in http_lines if not _is_http_line(line)]

                if http_lines != original_http_lines:
                    config_changed = True

                if not _commit_modular_config(cm, "120_http_access.conf", http_lines):
                    raise RuntimeError("No se pudieron guardar 120_http_access.conf")

            else:
                lines = cm.config_content.split("\n") if cm.config_content else []
                original_lines = lines.copy()

                if enabled:
                    if not any(_is_acl_line(line) for line in lines):
                        inserted = False
                        for i, line in enumerate(lines):
                            if line.strip().startswith("acl "):
                                lines.insert(i, acl_line)
                                inserted = True
                                break
                        if not inserted:
                            lines.append(acl_line)

                    if not any(_is_http_line(line) for line in lines):
                        inserted = False
                        for i, line in enumerate(lines):
                            if line.strip().startswith("http_access "):
                                lines.insert(i, http_line)
                                inserted = True
                                break
                        if not inserted:
                            lines.append(http_line)
                else:
                    lines = [line for line in lines if not (_is_acl_line(line) or _is_http_line(line))]

                if lines != original_lines:
                    config_changed = True

                if not cm.save_config("\n".join(lines)):
                    raise RuntimeError("No se pudo guardar squid.conf")

            if not config_changed:
                logger.debug(
                    "No hay cambios en la configuración de Squid, se omite validación y recarga"
                )
                return True

            splitter = SquidConfigSplitter(
                input_file=cm.config_path,
                output_dir=cm.config_dir,
            )
            validation = splitter._validate_squid_config()

            if not validation.get("success"):
                logger.error(
                    "Validación de Squid falló al sincronizar reglas de cuota: %s",
                    validation.get("error_message") or validation.get("output"),
                )
                # rollback
                if cm.is_modular:
                    cm.save_modular_config("100_acls.conf", previous_acls_content)
                    cm.save_modular_config("120_http_access.conf", previous_http_content)
                cm.save_config(previous_main_content)
                return False

            reload_success, reload_msg, _ = reload_squid()
            if not reload_success:
                logger.warning(
                    "Squid no se pudo recargar después de actualizar reglas de cuota: %s",
                    reload_msg,
                )
            else:
                logger.info("Squid recargado correctamente")

            return True

        except Exception as e:
            logger.error("Error aplicando reglas de cuota: %s", e)
            if cm.is_modular:
                cm.save_modular_config("100_acls.conf", previous_acls_content)
                cm.save_modular_config("120_http_access.conf", previous_http_content)
            cm.save_config(previous_main_content)
            return False

    # Primer intento
    ok = _apply_changes(acl_line, http_line)

    # Si falla y no es src, fallback a src (evita vida de proxy_auth mal configurada)
    if not ok and not use_src:
        logger.warning("Fallo con proxy_auth, reiniciando con ACL src para compatibilidad")
        acl_line = _build_acl_line(True)
        ok = _apply_changes(acl_line, http_line)

    if ok:
        logger.info("Reglas de cuota sincronizadas exitosamente con ACL %s", "src" if use_src else "proxy_auth")
    else:
        logger.error("No se pudo sincronizar las reglas de cuota después de reintentos")


def register_quota_scheduler_tasks(scheduler):
    """Registra tareas programadas relacionadas con cuotas."""

    @scheduler.task(
        "interval", id="check_quota_users", minutes=1, misfire_grace_time=300
    )
    def check_quota_users():
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
                logger.debug(
                    "check_quota_users: cuota deshabilitada, omitiendo evaluación"
                )
                return

            session = get_session()
            file_path = "/etc/squid/usuarios_bloqueados.txt"

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
