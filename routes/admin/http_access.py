"""Admin http_access rules management routes."""

from flask import flash, redirect, render_template, request, url_for

from services.auth.auth_service import admin_required
from services.squid.http_access_service import (
    add_http_access as service_add_http_access,
)
from services.squid.http_access_service import (
    delete_http_access as service_delete_http_access,
)
from services.squid.http_access_service import (
    edit_http_access as service_edit_http_access,
)
from services.squid.http_access_service import (
    move_http_access as service_move_http_access,
)

from .helpers import flash_and_redirect, get_config_manager, get_int_form_field


def register_routes(bp):
    @bp.route("/http-access")
    @admin_required
    def manage_http_access():
        cm = get_config_manager()
        rules = cm.get_http_access_rules()
        return render_template("admin/http_access.html", rules=rules)

    @bp.route("/http-access/delete", methods=["POST"])
    @admin_required
    def delete_http_access():
        cm = get_config_manager()
        rule_index = get_int_form_field("index")
        if rule_index is None:
            flash("Índice de regla inválido", "error")
            return redirect(url_for("admin.manage_http_access"))

        success, message = service_delete_http_access(rule_index, cm)
        return flash_and_redirect(success, message, "admin.manage_http_access")

    @bp.route("/http-access/edit", methods=["POST"])
    @admin_required
    def edit_http_access():
        """Edit an http_access rule with support for multiple ACLs and description."""
        cm = get_config_manager()
        rule_index = get_int_form_field("index")
        if rule_index is None:
            flash("Índice de regla inválido", "error")
            return redirect(url_for("admin.manage_http_access"))

        action = request.form.get("action")
        acls = request.form.getlist("acls[]")
        description = request.form.get("description", "").strip()

        success, message = service_edit_http_access(
            rule_index, action, acls, description, cm
        )
        return flash_and_redirect(success, message, "admin.manage_http_access")

    @bp.route("/http-access/add", methods=["POST"])
    @admin_required
    def add_http_access():
        """Add a new http_access rule."""
        cm = get_config_manager()
        action = request.form.get("action")
        acls = request.form.getlist("acls[]")
        description = request.form.get("description", "").strip()

        success, message = service_add_http_access(action, acls, description, cm)
        return flash_and_redirect(success, message, "admin.manage_http_access")

    @bp.route("/http-access/move", methods=["POST"])
    @admin_required
    def move_http_access():
        """Move an http_access rule up or down."""
        cm = get_config_manager()
        rule_index = get_int_form_field("index")
        if rule_index is None:
            flash("Índice de regla inválido", "error")
            return redirect(url_for("admin.manage_http_access"))

        direction = request.form.get("direction")
        success, message = service_move_http_access(rule_index, direction, cm)
        return flash_and_redirect(success, message, "admin.manage_http_access")
