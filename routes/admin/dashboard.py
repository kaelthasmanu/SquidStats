"""Admin dashboard routes."""

from flask import render_template

from services.auth.auth_service import admin_required

from .helpers import get_config_manager


def register_routes(bp):
    @bp.route("/")
    @admin_required
    def admin_dashboard():
        cm = get_config_manager()
        acls = cm.get_acls()
        delay_pools = cm.get_delay_pools()
        http_access_rules = cm.get_http_access_rules()
        stats = {
            "total_acls": len(acls),
            "total_delay_pools": len(delay_pools),
            "total_http_rules": len(http_access_rules),
        }
        status = cm.get_status()
        return render_template("admin/dashboardAdmin.html", stats=stats, status=status)
