"""Admin database overview, health checks and log import API."""

import os
import tempfile

from flask import jsonify, render_template, request
from flask_babel import gettext as _
from loguru import logger

from parsers.log import import_logs as import_log_file
from services.auth.auth_service import (
    admin_required,
    api_admin_required,
    api_auth_required,
)
from services.database import backup_service
from services.database.db_info_service import get_db_health, run_integrity_check

from .helpers import json_error, json_success


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

    @bp.route("/api/import-logs", methods=["POST"])
    @api_admin_required
    def import_logs():
        """Import an uploaded Squid access log into its daily tables."""
        uploaded_file = request.files.get("file")
        if not uploaded_file or not uploaded_file.filename:
            return json_error(_("Selecciona un archivo de logs para importar"))

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="squidstats-log-import-",
                suffix=".log",
                delete=False,
            ) as temporary_file:
                temporary_path = temporary_file.name
                uploaded_file.save(temporary_file)

            summary = import_log_file(temporary_path)
            return json_success(
                _("Importación completada correctamente"),
                extra={"summary": summary},
            )
        except FileNotFoundError:
            return json_error(_("No se pudo leer el archivo de logs"), 400)
        except ValueError:
            return json_error(_("El archivo no contiene logs de Squid válidos"), 400)
        except Exception:
            logger.exception("Error importing uploaded log file")
            return json_error(_("No se pudo importar el archivo de logs"), 500)
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
