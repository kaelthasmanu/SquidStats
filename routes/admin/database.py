"""Admin database overview – health panel, integrity check API."""

from flask import jsonify, render_template

from services.auth.auth_service import admin_required, api_auth_required
from services.database import backup_service
from services.database.db_info_service import get_db_health, run_integrity_check


def register_routes(bp):
    @bp.route("/database")
    @admin_required
    def database_view():
        cfg = backup_service.load_config()
        return render_template("admin/database.html", current_config=cfg)

    @bp.route("/api/db-health", methods=["GET"])
    @api_auth_required
    def db_health():
        resp, code = get_db_health()
        return jsonify(resp), code

    @bp.route("/api/db-integrity", methods=["POST"])
    @api_auth_required
    def db_integrity():
        resp, code = run_integrity_check()
        return jsonify(resp), code
