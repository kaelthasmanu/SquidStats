"""Admin backup management routes."""

from flask import jsonify, render_template, request, send_file

from services.auth.auth_service import admin_required
from services.database import backup_service


def register_routes(bp):
    @bp.route("/backup")
    @admin_required
    def backup_config():
        cfg = backup_service.load_config()
        return render_template("admin/backup.html", current_config=cfg)

    @bp.route("/backup/config", methods=["POST"])
    @admin_required
    def backup_save_config():
        data = request.get_json(silent=True) or {}
        allowed = {"db_type", "frequency", "backup_dir", "enabled"}
        cfg = {k: v for k, v in data.items() if k in allowed}

        if cfg.get("db_type", "sqlite") not in (
            "sqlite",
            "mysql",
            "postgresql",
            "mariadb",
        ):
            return jsonify(
                {"status": "error", "message": "Motor de BD desconocido"}
            ), 400

        if cfg.get("frequency") not in backup_service.FREQUENCY_CHOICES:
            return jsonify({"status": "error", "message": "Frecuencia inválida"}), 400

        if "enabled" in cfg:
            cfg["enabled"] = bool(cfg["enabled"])

        backup_service.save_config(cfg)
        return jsonify(
            {"status": "success", "message": "Configuración guardada correctamente"}
        )

    @bp.route("/backup/run", methods=["POST"])
    @admin_required
    def backup_run():
        result = backup_service.run_backup(is_auto=False)
        status_code = 200 if result["status"] == "success" else 500
        return jsonify(result), status_code

    @bp.route("/backup/list")
    @admin_required
    def backup_list():
        try:
            backups = backup_service.list_backups()
            return jsonify({"status": "success", "backups": backups})
        except Exception as e:
            return jsonify(
                {"status": "error", "message": str(e) or "Error leyendo salvas"}
            ), 500

    @bp.route("/backup/download/<filename>")
    @admin_required
    def backup_download(filename):
        path = backup_service.get_backup_file_path(filename)
        if path is None:
            return jsonify({"status": "error", "message": "Archivo no encontrado"}), 404
        return send_file(path, as_attachment=True, download_name=filename)

    @bp.route("/backup/delete/<filename>", methods=["DELETE"])
    @admin_required
    def backup_delete(filename):
        result = backup_service.delete_backup(filename)
        status_code = 200 if result["status"] == "success" else 400
        return jsonify(result), status_code
