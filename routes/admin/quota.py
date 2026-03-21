"""Admin quota management routes."""

from flask import redirect, render_template, request, url_for
from services.auth.auth_service import admin_required
from services.database.admin_helpers import load_env_vars
from .helpers import get_config_manager, flash_and_redirect


def register_routes(bp):
    @bp.route("/quota", methods=["GET"])
    @admin_required
    def manage_quota():
        """Render the quota management UI."""
        env_vars = load_env_vars()
        cm = get_config_manager()

        # Use delay_pools as a starting point for user quota management, since
        # Squid quota is usually implemented via delay pools.
        delay_pools = cm.get_delay_pools()

        return render_template("admin/quota.html", env_vars=env_vars, delay_pools=delay_pools)

    @bp.route("/quota/user/save", methods=["POST"])
    @admin_required
    def save_quota_user():
        username = request.form.get("username", "").strip()
        quota_mb = request.form.get("quota_mb", "").strip()

        if not username or not quota_mb:
            return flash_and_redirect(False, "Usuario y cuota son obligatorios", "admin.manage_quota")

        # TODO: Implement persistence logic for user quotas.
        return flash_and_redirect(True, f"Cuota guardada para usuario {username}", "admin.manage_quota")

    @bp.route("/quota/group/save", methods=["POST"])
    @admin_required
    def save_quota_group():
        group_name = request.form.get("group_name", "").strip()
        quota_mb = request.form.get("quota_mb", "").strip()

        if not group_name or not quota_mb:
            return flash_and_redirect(False, "Grupo y cuota son obligatorios", "admin.manage_quota")

        # TODO: Implement persistence logic for group quotas.
        return flash_and_redirect(True, f"Cuota guardada para grupo {group_name}", "admin.manage_quota")

    @bp.route("/quota/rules/save", methods=["POST"])
    @admin_required
    def save_quota_rules():
        policy = request.form.get("policy", "")
        if policy not in ("block", "throttle", "notify"):
            return flash_and_redirect(False, "Política de cuota inválida", "admin.manage_quota")

        # TODO: Implement quota rule persistence.
        return flash_and_redirect(True, f"Regla de cuota '{policy}' guardada", "admin.manage_quota")
