"""Admin ACL management routes."""

from flask import flash, redirect, render_template, request, url_for

from services.auth.auth_service import admin_required
from services.squid.acls_service import (
    add_acl as service_add_acl,
)
from services.squid.acls_service import (
    delete_acl as service_delete_acl,
)
from services.squid.acls_service import (
    edit_acl as service_edit_acl,
)

from .helpers import flash_and_redirect, get_config_manager, get_int_form_field


def register_routes(bp):
    @bp.route("/acls")
    @admin_required
    def manage_acls():
        """Display ACLs management interface with categorization and metadata."""
        cm = get_config_manager()
        acls = cm.get_acls()
        return render_template("admin/acls_new.html", acls=acls)

    @bp.route("/acls/add", methods=["POST"])
    @admin_required
    def add_acl():
        """Add a new ACL with options, multiple values, and comment."""
        cm = get_config_manager()
        name = request.form.get("name")
        acl_type = request.form.get("type")
        values = request.form.getlist("values[]")
        options = request.form.getlist("options[]")
        comment = request.form.get("comment", "").strip()

        success, message = service_add_acl(name, acl_type, values, options, comment, cm)
        return flash_and_redirect(success, message, "admin.manage_acls")

    @bp.route("/acls/edit", methods=["POST"])
    @admin_required
    def edit_acl():
        """Edit an existing ACL using line number for precise targeting."""
        cm = get_config_manager()
        acl_index = get_int_form_field("id")
        if acl_index is None:
            flash("ID de ACL inválido", "error")
            return redirect(url_for("admin.manage_acls"))

        new_name = request.form.get("name")
        acl_type = request.form.get("type")
        values = request.form.getlist("values[]")
        options = request.form.getlist("options[]")
        comment = request.form.get("comment", "").strip()

        success, message = service_edit_acl(
            acl_index, new_name, acl_type, values, options, comment, cm
        )
        return flash_and_redirect(success, message, "admin.manage_acls")

    @bp.route("/acls/delete", methods=["POST"])
    @admin_required
    def delete_acl():
        """Delete an ACL using its ID (index) and line number."""
        cm = get_config_manager()
        acl_index = get_int_form_field("id")
        if acl_index is None:
            flash("ID de ACL inválido", "error")
            return redirect(url_for("admin.manage_acls"))

        success, message = service_delete_acl(acl_index, cm)
        return flash_and_redirect(success, message, "admin.manage_acls")
