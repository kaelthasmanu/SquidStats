"""Admin log viewing routes."""

from flask import current_app, render_template, request

from config import Config
from services.auth.auth_service import admin_required
from services.system.logs_service import read_logs as service_read_logs


def register_routes(bp):
    @bp.route("/view-logs")
    @admin_required
    def view_logs():
        max_lines = request.args.get("lines", 250, type=int)
        max_lines = min(max(max_lines, 10), 1000)

        log_files = [Config.SQUID_LOG, Config.SQUID_CACHE_LOG, Config.APP_LOG]
        logs = service_read_logs(log_files, max_lines, debug=bool(current_app.debug))
        return render_template("admin/logs.html", logs=logs, max_lines=max_lines)
