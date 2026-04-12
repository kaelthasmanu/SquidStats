"""Admin delay pools management routes."""

from flask import render_template, request

from services.auth.auth_service import AuthService, admin_required
from services.squid.delay_pools_service import (
    add_delay_pool as service_add_delay_pool,
)
from services.squid.delay_pools_service import (
    delete_delay_pool as service_delete_delay_pool,
)
from services.squid.delay_pools_service import (
    edit_delay_pool as service_edit_delay_pool,
)

from .helpers import flash_and_redirect, get_config_manager


def register_routes(bp):
    @bp.route("/delay-pools")
    @admin_required
    def manage_delay_pools():
        cm = get_config_manager()
        delay_pools = cm.get_delay_pools()
        authenticated = AuthService.is_authenticated()
        return render_template(
            "admin/delay_pools.html",
            delay_pools=delay_pools,
            authenticated=authenticated,
        )

    @bp.route("/delay-pools/delete", methods=["POST"])
    @admin_required
    def delete_delay_pool():
        """Delete all directives related to a specific delay pool."""
        cm = get_config_manager()
        pool_number = request.form.get("pool_number")

        success, message = service_delete_delay_pool(pool_number, cm)
        return flash_and_redirect(success, message, "admin.manage_delay_pools")

    @bp.route("/delay-pools/edit", methods=["POST"])
    @admin_required
    def edit_delay_pool():
        """Edit all directives related to a specific delay pool."""
        cm = get_config_manager()
        pool_number = request.form.get("pool_number")
        pool_class = request.form.get("pool_class")
        parameters = request.form.get("parameters")
        access_actions = request.form.getlist("access_action[]")
        access_acls = request.form.getlist("access_acl[]")

        success, message = service_edit_delay_pool(
            pool_number, pool_class, parameters, access_actions, access_acls, cm
        )
        return flash_and_redirect(success, message, "admin.manage_delay_pools")

    @bp.route("/delay-pools/add", methods=["POST"])
    @admin_required
    def add_delay_pool():
        """Add a new delay pool with all its directives."""
        cm = get_config_manager()
        pool_number = request.form.get("pool_number")
        pool_class = request.form.get("pool_class")
        parameters = request.form.get("parameters")
        access_actions = request.form.getlist("access_action[]")
        access_acls = request.form.getlist("access_acl[]")

        success, message = service_add_delay_pool(
            pool_number, pool_class, parameters, access_actions, access_acls, cm
        )
        return flash_and_redirect(success, message, "admin.manage_delay_pools")
