"""Admin quota management routes."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import render_template, request
from loguru import logger
from sqlalchemy import func
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.exc import IntegrityError

from database.database import get_dynamic_models, get_session
from database.models.models import QuotaEvent, QuotaGroup, QuotaRule, QuotaUser
from services.auth.auth_service import admin_required
from services.database.admin_helpers import load_env_vars
from services.quota.quota_service import (
    _sync_quota_squid_rules,
    clear_blocked_users_file,
)

from .helpers import flash_and_redirect, get_config_manager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUOTA_DISABLED_FLAG = PROJECT_ROOT / "quota_disabled"


def is_quota_enabled() -> bool:
    """Return True if the quota scheduler/system is enabled."""
    return not os.path.exists(QUOTA_DISABLED_FLAG)


def set_quota_enabled(enabled: bool) -> bool:
    """Persist the quota enabled flag using a file marker. Returns True on success."""
    try:
        if enabled:
            if os.path.exists(QUOTA_DISABLED_FLAG):
                os.remove(QUOTA_DISABLED_FLAG)
        else:
            with open(QUOTA_DISABLED_FLAG, "w", encoding="utf-8") as f:
                f.write("disabled\n")
        return True
    except OSError as exc:
        logger.error("Error al cambiar estado de cuotas: %s", exc)
        return False


def register_routes(bp):
    @bp.route("/quota", methods=["GET"])
    @admin_required
    def manage_quota():
        """Render the quota management UI."""
        env_vars = load_env_vars()
        cm = get_config_manager()
        delay_pools = cm.get_delay_pools()

        target_tab = request.args.get("tab", "overview")

        session = get_session()
        try:
            user_quotas = session.query(QuotaUser).order_by(QuotaUser.username).all()
            group_quotas = (
                session.query(QuotaGroup).order_by(QuotaGroup.group_name).all()
            )
            active_rule = (
                session.query(QuotaRule)
                .filter_by(active=1)
                .order_by(QuotaRule.id.desc())
                .first()
            )
            events = (
                session.query(QuotaEvent)
                .order_by(QuotaEvent.created_at.desc())
                .limit(50)
                .all()
            )

            # Map usage from daily log tables into QuotaUser.used_mb to reflect real data
            quota_usernames = [q.username for q in user_quotas]
            usage_by_username = {}
            inspector = sqlalchemy_inspect(session.get_bind())
            all_tables = inspector.get_table_names()
            current_month_prefix = datetime.now(timezone.utc).strftime("%Y%m")

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

            for quota in user_quotas:
                total_bytes = usage_by_username.get(quota.username, None)
                if total_bytes is not None:
                    quota.used_mb = int(total_bytes / 1024 / 1024)

            users_with_quota = len(user_quotas)
            quota_exceeded_count = sum(
                1 for u in user_quotas if u.quota_mb > 0 and u.used_mb > u.quota_mb
            )

            blocked_users = []
            block_file = "/etc/squid/usuarios_bloqueados.txt"
            if os.path.exists(block_file):
                with open(block_file, encoding="utf-8") as f:
                    for line in f:
                        raw = line.strip()
                        if not raw:
                            continue
                        # Format 1: acl usuarios_bloqueados src <IP>
                        m = re.match(r"^acl\s+usuarios_bloqueados\s+src\s+(\S+)", raw)
                        if m:
                            username = m.group(1)
                            detail = "Bloqueado por IP (src)"
                        else:
                            # Format 2: plain username or "detail - username"
                            parts = [p.strip() for p in raw.split(" - ")]
                            if len(parts) >= 2:
                                username = parts[1]
                                detail = " - ".join(parts[2:]) if len(parts) > 2 else ""
                            else:
                                username = raw
                                detail = ""
                        blocked_users.append(
                            {"username": username, "detail": detail, "raw": raw}
                        )

        finally:
            session.close()

        return render_template(
            "admin/quota.html",
            env_vars=env_vars,
            delay_pools=delay_pools,
            user_quotas=user_quotas,
            group_quotas=group_quotas,
            active_quota_rule=active_rule,
            quota_events=events,
            users_with_quota=users_with_quota,
            quota_exceeded_count=quota_exceeded_count,
            blocked_users=blocked_users,
            active_tab=target_tab,
            quota_enabled=is_quota_enabled(),
        )

    @bp.route("/quota/toggle", methods=["POST"])
    @admin_required
    def toggle_quota():
        current = is_quota_enabled()
        ok = set_quota_enabled(not current)
        if not ok:
            return flash_and_redirect(
                False,
                "Error al cambiar el estado de las cuotas. "
                "Verifica los permisos del directorio de trabajo.",
                "admin.manage_quota",
            )

        if current:
            # Se deshabilitan las cuotas: eliminar bloqueados y sincronizar para quitar
            # las reglas de squid.conf inmediatamente.
            try:
                clear_blocked_users_file()
                _sync_quota_squid_rules(False)
            except Exception as exc:
                logger.warning(
                    "Cuotas deshabilitadas, pero no se pudo limpiar totalmente la configuración: %s",
                    exc,
                )

        message = "Cuotas activadas" if not current else "Cuotas desactivadas"
        return flash_and_redirect(True, message, "admin.manage_quota")

    @bp.route("/quota/user/save", methods=["POST"])
    @admin_required
    def save_quota_user():
        username = request.form.get("username", "").strip()
        group_name = request.form.get("group_name", "").strip() or None
        quota_mb_str = request.form.get("quota_mb", "").strip()

        if not username or not quota_mb_str:
            return flash_and_redirect(
                False, "Usuario y cuota son obligatorios", "admin.manage_quota"
            )

        try:
            quota_mb = int(quota_mb_str)
            if quota_mb < 0:
                raise ValueError("Cuota no puede ser negativa")
        except Exception:
            return flash_and_redirect(
                False, "Cuota debe ser un número entero válido", "admin.manage_quota"
            )

        session = get_session()
        try:
            if group_name:
                group = (
                    session.query(QuotaGroup).filter_by(group_name=group_name).first()
                )
                if not group:
                    return flash_and_redirect(
                        False,
                        f"El grupo '{group_name}' no existe",
                        "admin.manage_quota",
                        tab="user",
                    )

            quota = session.query(QuotaUser).filter_by(username=username).first()
            if quota:
                quota.quota_mb = quota_mb
                quota.group_name = group_name
            else:
                quota = QuotaUser(
                    username=username,
                    group_name=group_name,
                    quota_mb=quota_mb,
                    used_mb=0,
                )
                session.add(quota)

            session.add(
                QuotaEvent(
                    event_type="user_quota_set",
                    username=username,
                    detail=f"Cuota de usuario configurada a {quota_mb} MB",
                )
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            return flash_and_redirect(
                False,
                f"Nombre de usuario '{username}' ya existe. Elija otro nombre.",
                "admin.manage_quota",
            )
        except Exception as e:
            session.rollback()
            return flash_and_redirect(
                False, f"Error guardando cuota de usuario: {e}", "admin.manage_quota"
            )
        finally:
            session.close()

        return flash_and_redirect(
            True,
            f"Cuota guardada para usuario {username}",
            "admin.manage_quota",
            tab="user",
        )

    @bp.route("/quota/group/save", methods=["POST"])
    @admin_required
    def save_quota_group():
        group_name = request.form.get("group_name", "").strip()
        quota_mb_str = request.form.get("quota_mb", "").strip()

        if not group_name or not quota_mb_str:
            return flash_and_redirect(
                False, "Grupo y cuota son obligatorios", "admin.manage_quota"
            )

        try:
            quota_mb = int(quota_mb_str)
            if quota_mb < 0:
                raise ValueError("Cuota no puede ser negativa")
        except Exception:
            return flash_and_redirect(
                False, "Cuota debe ser un número entero válido", "admin.manage_quota"
            )

        session = get_session()
        try:
            quota = session.query(QuotaGroup).filter_by(group_name=group_name).first()
            if quota:
                quota.quota_mb = quota_mb
            else:
                quota = QuotaGroup(group_name=group_name, quota_mb=quota_mb)
                session.add(quota)

            session.add(
                QuotaEvent(
                    event_type="group_quota_set",
                    group_name=group_name,
                    detail=f"Cuota de grupo configurada a {quota_mb} MB",
                )
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            return flash_and_redirect(
                False,
                f"El nombre de grupo '{group_name}' ya existe. Elija otro nombre.",
                "admin.manage_quota",
            )
        except Exception as e:
            session.rollback()
            return flash_and_redirect(
                False, f"Error guardando cuota de grupo: {e}", "admin.manage_quota"
            )
        finally:
            session.close()

        return flash_and_redirect(
            True,
            f"Cuota guardada para grupo {group_name}",
            "admin.manage_quota",
            tab="group",
        )

    @bp.route("/quota/rules/save", methods=["POST"])
    @admin_required
    def save_quota_rules():
        policy = request.form.get("policy", "")
        if policy not in ("block", "throttle", "notify"):
            return flash_and_redirect(
                False, "Política de cuota inválida", "admin.manage_quota"
            )

        session = get_session()
        try:
            # desactivar reglas previas
            session.query(QuotaRule).update({QuotaRule.active: 0})
            quota_rule = session.query(QuotaRule).filter_by(policy=policy).first()
            if quota_rule:
                quota_rule.active = 1
            else:
                quota_rule = QuotaRule(policy=policy, active=1)
                session.add(quota_rule)

            session.add(
                QuotaEvent(
                    event_type="quota_rule_set",
                    detail=f"Regla de cuota establecida en '{policy}'",
                )
            )
            session.commit()
        except Exception as e:
            session.rollback()
            return flash_and_redirect(
                False, f"Error guardando regla de cuota: {e}", "admin.manage_quota"
            )
        finally:
            session.close()

        return flash_and_redirect(
            True,
            f"Regla de cuota '{policy}' guardada",
            "admin.manage_quota",
            tab="rules",
        )

    @bp.route("/quota/user/delete", methods=["POST"])
    @admin_required
    def delete_quota_user():
        username = request.form.get("username", "").strip()

        if not username:
            return flash_and_redirect(
                False, "Usuario no proporcionado", "admin.manage_quota", tab="user"
            )

        session = get_session()
        try:
            quota = session.query(QuotaUser).filter_by(username=username).first()
            if not quota:
                return flash_and_redirect(
                    False,
                    f"Usuario {username} no encontrado",
                    "admin.manage_quota",
                    tab="user",
                )

            session.delete(quota)
            session.add(
                QuotaEvent(
                    event_type="user_quota_deleted",
                    username=username,
                    detail=f"Cuota del usuario {username} eliminada",
                )
            )
            session.commit()
        except Exception as e:
            session.rollback()
            return flash_and_redirect(
                False,
                f"Error eliminando cuota de usuario: {e}",
                "admin.manage_quota",
                tab="user",
            )
        finally:
            session.close()

        return flash_and_redirect(
            True,
            f"Cuota eliminada para usuario {username}",
            "admin.manage_quota",
            tab="user",
        )

    @bp.route("/quota/group/delete", methods=["POST"])
    @admin_required
    def delete_quota_group():
        group_name = request.form.get("group_name", "").strip()

        if not group_name:
            return flash_and_redirect(
                False, "Grupo no proporcionado", "admin.manage_quota", tab="group"
            )

        session = get_session()
        try:
            quota = session.query(QuotaGroup).filter_by(group_name=group_name).first()
            if not quota:
                return flash_and_redirect(
                    False,
                    f"Grupo {group_name} no encontrado",
                    "admin.manage_quota",
                    tab="group",
                )

            session.delete(quota)
            session.add(
                QuotaEvent(
                    event_type="group_quota_deleted",
                    group_name=group_name,
                    detail=f"Cuota del grupo {group_name} eliminada",
                )
            )
            session.commit()
        except Exception as e:
            session.rollback()
            return flash_and_redirect(
                False,
                f"Error eliminando cuota de grupo: {e}",
                "admin.manage_quota",
                tab="group",
            )
        finally:
            session.close()

        return flash_and_redirect(
            True,
            f"Cuota eliminada para grupo {group_name}",
            "admin.manage_quota",
            tab="group",
        )
