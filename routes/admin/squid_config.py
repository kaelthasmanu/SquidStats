"""Admin Squid configuration routes (view, edit, env, split)."""

from flask import flash, jsonify, redirect, render_template, request, url_for
from loguru import logger

from services.auth.auth_service import admin_required, api_auth_required
from services.database.admin_helpers import load_env_vars, save_env_vars
from services.squid.config_service import save_config as service_save_config
from services.squid.split_config_service import (
    get_split_files_info as service_get_split_files_info,
    get_split_view_data as service_get_split_view_data,
    split_config as service_split_config,
)
from services.squid.squid_config_splitter import SquidConfigSplitter

from .helpers import (
    flash_and_redirect,
    flash_error_with_details,
    get_config_manager,
    is_debug,
    json_error,
    json_success,
    reload_config_manager,
)


def register_routes(bp):
    # ------------------------------------------------------------------
    # View / edit squid.conf
    # ------------------------------------------------------------------

    @bp.route("/config")
    @admin_required
    def view_config():
        cm = get_config_manager()
        env_vars = load_env_vars()
        return render_template(
            "admin/config.html",
            config_content=cm.config_content,
            env_vars=env_vars,
        )

    @bp.route("/config/edit", methods=["GET", "POST"])
    @admin_required
    def edit_config():
        cm = get_config_manager()
        if request.method == "POST":
            new_content = request.form["config_content"]
            ok, message = service_save_config(new_content, cm)
            if ok:
                flash(message, "success")
                return redirect(url_for("admin.view_config"))
            else:
                flash_error_with_details("Error saving configuration", Exception(message))
        return render_template(
            "admin/edit_config.html", config_content=cm.config_content
        )

    # ------------------------------------------------------------------
    # Environment variables
    # ------------------------------------------------------------------

    @bp.route("/config/env/save", methods=["POST"])
    @admin_required
    def save_env():
        sensitive_vars = {"VERSION"}

        env_vars = {}
        for key in request.form:
            if key != "csrf_token" and key not in sensitive_vars:
                env_vars[key] = request.form[key]

        existing_vars = load_env_vars()
        for key, value in env_vars.items():
            existing_vars[key] = value

        save_env_vars(existing_vars)
        flash("Variables de entorno guardadas exitosamente", "success")
        return redirect(url_for("admin.view_config"))

    # ------------------------------------------------------------------
    # Split config
    # ------------------------------------------------------------------

    @bp.route("/config/split")
    @admin_required
    def split_config_view():
        """Vista para dividir el archivo squid.conf en archivos modulares."""
        try:
            data = service_get_split_view_data()
            return render_template(
                "admin/split_config.html",
                split_info=data["split_info"],
                output_dir=data["output_dir"],
                input_file=data["input_file"],
                output_exists=data["output_exists"],
                files_count=data["files_count"],
            )
        except Exception as e:
            logger.exception("Error al cargar la vista de división de configuración")
            flash_error_with_details("Error al cargar la vista", e)
            return redirect(url_for("admin.admin_dashboard"))

    @bp.route("/api/split-config", methods=["POST"])
    @api_auth_required
    def split_config():
        """API endpoint para dividir el archivo squid.conf."""
        try:
            data = request.get_json() or {}
            strict = data.get("strict", False)

            resp, code = service_split_config(strict=strict)

            if code == 200:
                reload_config_manager()

            return jsonify(resp), code

        except FileNotFoundError as e:
            logger.error(f"Archivo no encontrado: {e}")
            return json_error(
                "Archivo requerido no encontrado. Verifique la configuración del archivo squid.conf.",
                404,
            )
        except PermissionError as e:
            logger.error(f"Error de permisos: {e}")
            return json_error(
                "No se tienen permisos suficientes para crear los archivos", 403
            )
        except RuntimeError as e:
            logger.error(f"Error de validación: {e}")
            return json_error(
                "Error de validación de la configuración", 400
            )
        except Exception as e:
            logger.exception("Error al dividir el archivo de configuración")
            return json_error(
                "Error interno al dividir la configuración",
                500,
                details=str(e),
            )

    @bp.route("/api/get-split-files", methods=["GET"])
    @api_auth_required
    def get_split_files():
        """API endpoint para obtener la lista de archivos generados en squid.d."""
        splitter = SquidConfigSplitter()
        result = service_get_split_files_info(splitter.output_dir)

        if result.get("status") == "success":
            return jsonify(result)
        return jsonify(result), result.get("code", 500)
