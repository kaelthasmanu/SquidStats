"""Admin system API routes (restart, reload, tables, clean data)."""

import re

from flask import jsonify, render_template, request
from loguru import logger

from services.auth.auth_service import admin_required, api_auth_required
from services.database.db_admin_service import (
    delete_table_data as service_delete_table_data,
)
from services.database.db_info_service import (
    get_tables_info as service_get_tables_info,
)
from services.squid.ssl_bump_service import get_ssl_bump_status
from services.system.system_service import (
    reload_squid as service_reload_squid,
)
from services.system.system_service import (
    restart_squid as service_restart_squid,
)

from .helpers import get_config_manager, json_error, json_success


def register_routes(bp):
    # ------------------------------------------------------------------
    # Squid control
    # ------------------------------------------------------------------

    @bp.route("/api/restart-squid", methods=["POST"])
    @api_auth_required
    def restart_squid():
        success, message, details = service_restart_squid()
        if success:
            return json_success(message)
        return json_error(message, 500, details=details)

    @bp.route("/api/reload-squid", methods=["POST"])
    @api_auth_required
    def reload_squid():
        success, message, details = service_reload_squid()
        if success:
            return json_success(message)
        return json_error(message, 500, details=details)

    # ------------------------------------------------------------------
    # SSL Bump detection
    # ------------------------------------------------------------------

    @bp.route("/api/ssl-bump-status", methods=["GET"])
    @api_auth_required
    def ssl_bump_status():
        cm = get_config_manager()
        data = get_ssl_bump_status(cm)
        print("SSL Bump status:", data)  # Debug log
        return jsonify(data), 200

    # ------------------------------------------------------------------
    # Database management
    # ------------------------------------------------------------------

    @bp.route("/api/get-tables", methods=["GET"])
    @api_auth_required
    def get_tables():
        resp, code = service_get_tables_info()
        return jsonify(resp), code

    @bp.route("/clean-data")
    @admin_required
    def clean_data():
        """View for cleaning database tables."""
        return render_template("admin/clean_data.html")

    @bp.route("/api/delete-table-data", methods=["POST"])
    @api_auth_required
    def delete_table_data():
        """API endpoint to delete all data from a table."""
        try:
            data = request.get_json()
            table_name = data.get("table_name")

            if not table_name:
                return json_error("Nombre de tabla no proporcionado")

            if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
                return json_error("Nombre de tabla inválido")

            if table_name in ("admin_users", "alembic_version"):
                return json_error("No se puede eliminar estas tablas críticas")

            resp, code = service_delete_table_data(table_name)
            return jsonify(resp), code

        except Exception as e:
            logger.exception("Error deleting data from table")
            return json_error("Error interno del servidor", 500, details=str(e))
