"""Admin quota management routes."""

from flask import render_template, request

from database.database import get_session
from database.models.models import QuotaEvent, QuotaGroup, QuotaRule, QuotaUser
from services.auth.auth_service import admin_required
from services.database.admin_helpers import load_env_vars

from .helpers import flash_and_redirect, get_config_manager


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

            users_with_quota = len(user_quotas)
            quota_exceeded_count = sum(
                1 for u in user_quotas if u.quota_mb > 0 and u.used_mb > u.quota_mb
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
            active_tab=target_tab,
        )

    @bp.route("/quota/user/save", methods=["POST"])
    @admin_required
    def save_quota_user():
        username = request.form.get("username", "").strip()
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
            quota = session.query(QuotaUser).filter_by(username=username).first()
            if quota:
                quota.quota_mb = quota_mb
            else:
                quota = QuotaUser(username=username, quota_mb=quota_mb, used_mb=0)
                session.add(quota)

            session.add(
                QuotaEvent(
                    event_type="user_quota_set",
                    username=username,
                    detail=f"Cuota de usuario configurada a {quota_mb} MB",
                )
            )
            session.commit()
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
