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
from sqlalchemy import Table, inspect, text, MetaData, select, func

from config import Config, logger
from database.database import get_engine, get_session
from services.auth_service import AuthService, admin_required, api_auth_required
from utils.admin import SquidConfigManager

admin_bp = Blueprint("admin", __name__)

# Global manager instance
config_manager = SquidConfigManager()


def load_env_vars():
    env_vars = {}
    env_file = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key] = value.strip('"')
    return env_vars


def save_env_vars(env_vars):
    env_file = os.path.join(os.getcwd(), ".env")
    with open(env_file, "w") as f:
        for key, value in env_vars.items():
            f.write(f'{key}="{value}"\n')

def get_table_row_count(session, engine, table_name):
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)

    return session.execute(
        select(func.count()).select_from(table)
    ).scalar_one()


def get_table_size(session, db_type, table_name):
    if db_type == "SQLITE":
        result = session.execute(
            text("SELECT SUM(pgsize) FROM dbstat WHERE name = :name"),
            {"name": table_name},
        )
        return result.scalar() or 0

    if db_type in ("MYSQL", "MARIADB"):
        result = session.execute(
            text("""
                SELECT data_length + index_length
                FROM information_schema.tables
                WHERE table_name = :name
                AND table_schema = DATABASE()
            """),
            {"name": table_name},
        )
        return result.scalar() or 0

    if db_type in ("POSTGRES", "POSTGRESQL"):
        result = session.execute(
            text("SELECT pg_total_relation_size(:name)"),
            {"name": table_name},
        )
        return result.scalar() or 0

    return 0


@admin_bp.route("/")
@admin_required
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
@admin_required
def view_config():
    env_vars = load_env_vars()
    return render_template(
        "admin/config.html",
        config_content=config_manager.config_content,
        env_vars=env_vars,
    )


@admin_bp.route("/config/edit", methods=["GET", "POST"])
@admin_required
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


@admin_bp.route("/config/env/save", methods=["POST"])
@admin_required
def save_env():
    # Variables sensibles que no se pueden modificar desde la interfaz
    sensitive_vars = {"VERSION"}

    env_vars = {}
    for key in request.form:
        if key != "csrf_token" and key not in sensitive_vars:
            env_vars[key] = request.form[key]

    # Cargar variables existentes para mantener las sensibles
    existing_vars = load_env_vars()
    # Solo actualizar las no sensibles
    for key, value in env_vars.items():
        existing_vars[key] = value

    save_env_vars(existing_vars)
    flash("Variables de entorno guardadas exitosamente", "success")
    return redirect(url_for("admin.view_config"))


@admin_bp.route("/acls")
@admin_required
def manage_acls():
    acls = config_manager.get_acls()
    return render_template("admin/acls.html", acls=acls)


@admin_bp.route("/acls/add", methods=["POST"])
@admin_required
def add_acl():
    name = request.form["name"]
    acl_type = request.form["type"]
    value = request.form["value"]
    new_acl = f"acl {name} {acl_type} {value}"

    # Add the new ACL at the end of the ACLs section
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
@admin_required
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

            # Replace the line in the content
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
@admin_required
def delete_acl():
    acl_id = request.form["id"]

    try:
        acl_index = int(acl_id)
        acls = config_manager.get_acls()

        if 0 <= acl_index < len(acls):
            acl_to_delete = acls[acl_index]

            # Remove the line from the content
            lines = config_manager.config_content.split("\n")
            new_lines = []
            acl_count = 0

            for line in lines:
                if line.strip().startswith("acl ") and not line.strip().startswith("#"):
                    if acl_count == acl_index:
                        # Skip this line (delete it)
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
@admin_required
def manage_delay_pools():
    delay_pools = config_manager.get_delay_pools()
    return render_template("admin/delay_pools.html", delay_pools=delay_pools)


@admin_bp.route("/http-access")
@admin_required
def manage_http_access():
    rules = config_manager.get_http_access_rules()
    return render_template("admin/http_access.html", rules=rules)


@admin_bp.route("/view-logs")
@admin_required
def view_logs():
    # Get the requested number of lines (default 250, maximum 1000)
    max_lines = request.args.get("lines", 250, type=int)
    max_lines = min(max(max_lines, 10), 1000)  # Between 10 and 1000 lines

    log_files = [
        Config.SQUID_LOG,
        Config.SQUID_CACHE_LOG,
    ]
    logs = {}
    for log_file in log_files:
        try:
            with open(log_file) as f:
                # Read the last N lines
                lines = f.readlines()
                logs[os.path.basename(log_file)] = lines[-max_lines:]
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

    return render_template("admin/logs.html", logs=logs, max_lines=max_lines)


@admin_bp.route("/users")
@admin_required
def manage_users():
    users = AuthService.get_all_users()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users/create", methods=["GET", "POST"])
@admin_required
def create_user():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role", "admin")

        if not username or not password:
            flash("El nombre de usuario y la contraseña son obligatorios", "error")
            return redirect(url_for("admin.create_user"))

        if len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres", "error")
            return redirect(url_for("admin.create_user"))

        if AuthService.create_user(username, password, role):
            flash("Usuario creado exitosamente", "success")
            return redirect(url_for("admin.manage_users"))
        else:
            flash(
                "Error al crear usuario. El nombre de usuario ya puede existir.",
                "error",
            )

    return render_template("admin/user_form.html", user=None, action="create")


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id):
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")
        is_active = 1 if request.form.get("is_active") else 0

        if password and len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres", "error")
            return redirect(url_for("admin.edit_user", user_id=user_id))

        update_data = {"username": username, "role": role, "is_active": is_active}
        if password:
            update_data["password"] = password

        if AuthService.update_user(user_id, **update_data):
            flash("Usuario actualizado exitosamente", "success")
            return redirect(url_for("admin.manage_users"))
        else:
            flash("Error al actualizar usuario", "error")

    users = AuthService.get_all_users()
    user = next((u for u in users if u["id"] == user_id), None)
    if not user:
        flash("Usuario no encontrado", "error")
        return redirect(url_for("admin.manage_users"))

    return render_template("admin/user_form.html", user=user, action="edit")


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    if AuthService.delete_user(user_id):
        flash("Usuario eliminado exitosamente", "success")
    else:
        flash(
            "Error al eliminar usuario. No se puede eliminar el usuario admin.", "error"
        )
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/api/restart-squid", methods=["POST"])
@api_auth_required
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
@api_auth_required
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


@admin_bp.route("/api/get-tables", methods=["GET"])
@api_auth_required
def get_tables():
    session = None
    try:
        engine = get_engine()
        inspector = inspect(engine)
        session = get_session()
        db_type = Config.DATABASE_TYPE

        tables = inspector.get_table_names()
        table_info = []

        for table_name in tables:
            try:
                rows = get_table_row_count(session, engine, table_name)
                size = get_table_size(session, db_type, table_name)

                table_info.append({
                    "name": table_name,
                    "rows": rows,
                    "size": size,
                    "has_data": rows > 0,
                })

            except Exception as e:
                logger.warning(f"Error processing table {table_name}: {e}")
                table_info.append({
                    "name": table_name,
                    "rows": 0,
                    "size": 0,
                    "has_data": False,
                })

        return jsonify({"status": "success", "tables": table_info})

    except Exception as e:
        logger.exception("Error getting database tables")
        resp = {"status": "error", "message": "Error interno del servidor"}
        if current_app.debug:
            resp["details"] = str(e)
        return jsonify(resp), 500

    finally:
        if session:
            session.close()



@admin_bp.route("/clean-data")
@admin_required
def clean_data():
    """View for cleaning database tables."""
    return render_template("admin/clean_data.html")


@admin_bp.route("/api/delete-table-data", methods=["POST"])
@api_auth_required
def delete_table_data():
    """API endpoint to delete all data from a table."""
    try:
        data = request.get_json()
        table_name = data.get("table_name")

        if not table_name:
            return jsonify(
                {"status": "error", "message": "Nombre de tabla no proporcionado"}
            ), 400

        # Validate table name to prevent SQL injection
        import re

        if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
            return jsonify(
                {"status": "error", "message": "Nombre de tabla inválido"}
            ), 400

        engine = get_engine()
        inspector = inspect(engine)

        # Verify table exists
        if table_name not in inspector.get_table_names():
            return jsonify({"status": "error", "message": "La tabla no existe"}), 404

        # Delete all data from table
        with engine.connect() as conn:
            conn.execute(text(f"DELETE FROM {table_name}"))
            conn.commit()

        return jsonify(
            {
                "status": "success",
                "message": f"Datos de la tabla '{table_name}' eliminados correctamente",
            }
        )

    except Exception as e:
        logger.exception("Error deleting data from table")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False

        resp = {"status": "error", "message": "Error interno del servidor"}
        if show_details:
            resp["details"] = str(e)
        return jsonify(resp), 500
