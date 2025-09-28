import os

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from config import logger
from utils.admin import SquidConfigManager

admin_bp = Blueprint("admin", __name__)

# Instancia global del manager
config_manager = SquidConfigManager()


@admin_bp.route("/")
def admin_dashboard():
    acls = config_manager.get_acls()
    delay_pools = config_manager.get_delay_pools()
    http_access_rules = config_manager.get_http_access_rules()
    stats = {
        "total_acls": len(acls),
        "total_delay_pools": len(delay_pools),
        "total_http_rules": len(http_access_rules),
    }
    status = config_manager.get_status()
    return render_template("admin/dashboardAdmin.html", stats=stats, status=status)


@admin_bp.route("/config")
def view_config():
    return render_template(
        "admin/config.html", config_content=config_manager.config_content
    )


@admin_bp.route("/config/edit", methods=["GET", "POST"])
def edit_config():
    if request.method == "POST":
        new_content = request.form["config_content"]
        try:
            config_manager.save_config(new_content)
            flash("Configuration saved successfully", "success")
            return redirect(url_for("admin.view_config"))
        except Exception as e:
            # Log full exception; avoid showing raw exception text to users
            logger.exception("Error saving configuration")
            try:
                show_details = bool(current_app.debug)
            except RuntimeError:
                show_details = False

            if show_details:
                flash(f"Error saving configuration: {str(e)}", "error")
            else:
                flash("Error saving configuration", "error")
    return render_template(
        "admin/edit_config.html", config_content=config_manager.config_content
    )


@admin_bp.route("/acls")
def manage_acls():
    acls = config_manager.get_acls()
    return render_template("admin/acls.html", acls=acls)


@admin_bp.route("/acls/add", methods=["POST"])
def add_acl():
    name = request.form["name"]
    acl_type = request.form["type"]
    value = request.form["value"]
    new_acl = f"acl {name} {acl_type} {value}"

    # Agregar la nueva ACL al final de la sección de ACLs
    lines = config_manager.config_content.split("\n")
    acl_section_end = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("acl "):
            acl_section_end = i
    if acl_section_end != -1:
        lines.insert(acl_section_end + 1, new_acl)
    else:
        lines.append(new_acl)

    new_content = "\n".join(lines)
    config_manager.save_config(new_content)
    flash("ACL agregada exitosamente", "success")
    return redirect(url_for("admin.manage_acls"))


@admin_bp.route("/acls/edit", methods=["POST"])
def edit_acl():
    acl_id = request.form["id"]
    new_name = request.form["name"]
    new_type = request.form["type"]
    new_value = request.form["value"]

    try:
        acl_index = int(acl_id)
        acls = config_manager.get_acls()

        if 0 <= acl_index < len(acls):
            new_acl_line = f"acl {new_name} {new_type} {new_value}"

            # Reemplazar la línea en el contenido
            lines = config_manager.config_content.split("\n")
            acl_count = 0
            for i, line in enumerate(lines):
                if line.strip().startswith("acl ") and not line.strip().startswith("#"):
                    if acl_count == acl_index:
                        lines[i] = new_acl_line
                        break
                    acl_count += 1

            new_content = "\n".join(lines)
            config_manager.save_config(new_content)
            flash("ACL actualizada exitosamente", "success")
        else:
            flash("ACL no encontrada", "error")
    except (ValueError, IndexError):
        flash("Error al actualizar la ACL", "error")

    return redirect(url_for("admin.manage_acls"))


@admin_bp.route("/acls/delete", methods=["POST"])
def delete_acl():
    acl_id = request.form["id"]

    try:
        acl_index = int(acl_id)
        acls = config_manager.get_acls()

        if 0 <= acl_index < len(acls):
            acl_to_delete = acls[acl_index]

            # Remover la línea del contenido
            lines = config_manager.config_content.split("\n")
            new_lines = []
            acl_count = 0

            for line in lines:
                if line.strip().startswith("acl ") and not line.strip().startswith("#"):
                    if acl_count == acl_index:
                        # Saltar esta línea (eliminarla)
                        acl_count += 1
                        continue
                    acl_count += 1
                new_lines.append(line)

            new_content = "\n".join(new_lines)
            config_manager.save_config(new_content)
            flash(f"ACL '{acl_to_delete['name']}' eliminada exitosamente", "success")
        else:
            flash("ACL no encontrada", "error")
    except (ValueError, IndexError):
        flash("Error al eliminar la ACL", "error")

    return redirect(url_for("admin.manage_acls"))


@admin_bp.route("/delay-pools")
def manage_delay_pools():
    delay_pools = config_manager.get_delay_pools()
    return render_template("admin/delay_pools.html", delay_pools=delay_pools)


@admin_bp.route("/http-access")
def manage_http_access():
    rules = config_manager.get_http_access_rules()
    return render_template("admin/http_access.html", rules=rules)


@admin_bp.route("/view-logs")
def view_logs():
    log_files = [
        os.getenv("SQUID_LOG", "/var/log/squid/access.log"),
        os.getenv("SQUID_CACHE_LOG", "/var/log/squid/cache.log"),
    ]
    logs = {}
    for log_file in log_files:
        try:
            with open(log_file) as f:
                # Leer las últimas 100 líneas
                lines = f.readlines()
                logs[os.path.basename(log_file)] = lines[-100:]
        except FileNotFoundError:
            logs[os.path.basename(log_file)] = ["Log file not found"]
        except Exception as e:
            # Log the exception with traceback on the server
            logger.exception("Error reading log file %s", log_file)
            try:
                show_details = bool(current_app.debug)
            except RuntimeError:
                show_details = False

            if show_details:
                logs[os.path.basename(log_file)] = [f"Error reading log: {str(e)}"]
            else:
                logs[os.path.basename(log_file)] = ["Error reading log"]

    return render_template("admin/logs.html", logs=logs)


@admin_bp.route("/api/restart-squid", methods=["POST"])
def restart_squid():
    try:
        os.system("systemctl restart squid")
        return jsonify({"status": "success", "message": "Squid restarted successfully"})
    except Exception as e:
        logger.exception("Error restarting squid")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False

        resp = {"status": "error", "message": "Internal server error"}
        if show_details:
            resp["details"] = str(e)
        return jsonify(resp), 500


@admin_bp.route("/api/reload-squid", methods=["POST"])
def reload_squid():
    try:
        os.system("systemctl reload squid")
        return jsonify(
            {"status": "success", "message": "Configuration reloaded successfully"}
        )
    except Exception as e:
        logger.exception("Error reloading squid configuration")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False

        resp = {"status": "error", "message": "Internal server error"}
        if show_details:
            resp["details"] = str(e)
        return jsonify(resp), 500
