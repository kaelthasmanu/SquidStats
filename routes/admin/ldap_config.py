"""Admin LDAP / Active Directory configuration route."""

from flask import render_template

from services.auth.auth_service import admin_required


def register_routes(bp):
    @bp.route("/ldap-config")
    @admin_required
    def ldap_config():
        return render_template("admin/ldap_config.html")
