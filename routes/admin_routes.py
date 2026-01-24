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
from sqlalchemy import MetaData, Table, func, inspect, select, text

from config import Config, logger
from database.database import get_engine, get_session
from services.auth_service import AuthService, admin_required, api_auth_required
from services.squid_config_splitter import SquidConfigSplitter
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

    return session.execute(select(func.count()).select_from(table)).scalar_one()


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

    # Check if using modular configuration
    if config_manager.is_modular:
        # Read the modular ACL config
        acl_content = config_manager.read_modular_config("100_acls.conf")
        if acl_content is not None:
            lines = acl_content.split("\n")
            # Add the new ACL at the end
            lines.append(new_acl)
            new_content = "\n".join(lines)
            if config_manager.save_modular_config("100_acls.conf", new_content):
                flash("ACL agregada exitosamente", "success")
            else:
                flash("Error al guardar la ACL", "error")
            return redirect(url_for("admin.manage_acls"))
    
    # Fallback to main config if not modular or read failed
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

            # Check if using modular configuration
            if config_manager.is_modular:
                # Read the modular ACL config
                acl_content = config_manager.read_modular_config("100_acls.conf")
                if acl_content is not None:
                    lines = acl_content.split("\n")
                    acl_count = 0
                    for i, line in enumerate(lines):
                        if line.strip().startswith("acl ") and not line.strip().startswith("#"):
                            if acl_count == acl_index:
                                lines[i] = new_acl_line
                                break
                            acl_count += 1
                    
                    new_content = "\n".join(lines)
                    if config_manager.save_modular_config("100_acls.conf", new_content):
                        flash("ACL actualizada exitosamente", "success")
                    else:
                        flash("Error al guardar la ACL", "error")
                    return redirect(url_for("admin.manage_acls"))
            
            # Fallback to main config if not modular or read failed
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

            # Check if using modular configuration
            if config_manager.is_modular:
                # Read the modular ACL config
                acl_content = config_manager.read_modular_config("100_acls.conf")
                if acl_content is not None:
                    lines = acl_content.split("\n")
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
                    if config_manager.save_modular_config("100_acls.conf", new_content):
                        flash(f"ACL '{acl_to_delete['name']}' eliminada exitosamente", "success")
                    else:
                        flash("Error al eliminar la ACL", "error")
                    return redirect(url_for("admin.manage_acls"))
            
            # Fallback to main config if not modular or read failed
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


@admin_bp.route("/http-access/delete", methods=["POST"])
@admin_required
def delete_http_access():
    index = request.form.get("index")
    
    try:
        rule_index = int(index)
        
        # Check if using modular configuration
        if config_manager.is_modular:
            http_content = config_manager.read_modular_config("120_http_access.conf")
            if http_content is not None:
                lines = http_content.split("\n")
                new_lines = []
                http_count = 0
                
                for line in lines:
                    if line.strip().startswith("http_access ") and not line.strip().startswith("#"):
                        if http_count == rule_index:
                            # Skip this line (delete it)
                            http_count += 1
                            continue
                        http_count += 1
                    new_lines.append(line)
                
                new_content = "\n".join(new_lines)
                if config_manager.save_modular_config("120_http_access.conf", new_content):
                    flash("Regla HTTP Access eliminada exitosamente", "success")
                else:
                    flash("Error al eliminar la regla", "error")
                return redirect(url_for("admin.manage_http_access"))
        
        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        new_lines = []
        http_count = 0
        
        for line in lines:
            if line.strip().startswith("http_access ") and not line.strip().startswith("#"):
                if http_count == rule_index:
                    http_count += 1
                    continue
                http_count += 1
            new_lines.append(line)
        
        new_content = "\n".join(new_lines)
        config_manager.save_config(new_content)
        flash("Regla HTTP Access eliminada exitosamente", "success")
        
    except (ValueError, IndexError) as e:
        flash(f"Error al eliminar la regla: {str(e)}", "error")
    
    return redirect(url_for("admin.manage_http_access"))


@admin_bp.route("/http-access/edit", methods=["POST"])
@admin_required
def edit_http_access():
    index = request.form.get("index")
    action = request.form.get("action")
    acl = request.form.get("acl")
    
    try:
        rule_index = int(index)
        new_rule = f"http_access {action} {acl}"
        
        # Check if using modular configuration
        if config_manager.is_modular:
            http_content = config_manager.read_modular_config("120_http_access.conf")
            if http_content is not None:
                lines = http_content.split("\n")
                http_count = 0
                
                for i, line in enumerate(lines):
                    if line.strip().startswith("http_access ") and not line.strip().startswith("#"):
                        if http_count == rule_index:
                            lines[i] = new_rule
                            break
                        http_count += 1
                
                new_content = "\n".join(lines)
                if config_manager.save_modular_config("120_http_access.conf", new_content):
                    flash("Regla HTTP Access actualizada exitosamente", "success")
                else:
                    flash("Error al actualizar la regla", "error")
                return redirect(url_for("admin.manage_http_access"))
        
        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        http_count = 0
        
        for i, line in enumerate(lines):
            if line.strip().startswith("http_access ") and not line.strip().startswith("#"):
                if http_count == rule_index:
                    lines[i] = new_rule
                    break
                http_count += 1
        
        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        flash("Regla HTTP Access actualizada exitosamente", "success")
        
    except (ValueError, IndexError) as e:
        flash(f"Error al actualizar la regla: {str(e)}", "error")
    
    return redirect(url_for("admin.manage_http_access"))


@admin_bp.route("/delay-pools/delete", methods=["POST"])
@admin_required
def delete_delay_pool():
    index = request.form.get("index")
    
    try:
        directive_index = int(index)
        
        # Check if using modular configuration
        if config_manager.is_modular:
            delay_content = config_manager.read_modular_config("110_delay_pools.conf")
            if delay_content is not None:
                lines = delay_content.split("\n")
                new_lines = []
                directive_count = 0
                
                for line in lines:
                    if line.strip().startswith("delay_") and not line.strip().startswith("#"):
                        if directive_count == directive_index:
                            # Skip this line (delete it)
                            directive_count += 1
                            continue
                        directive_count += 1
                    new_lines.append(line)
                
                new_content = "\n".join(new_lines)
                if config_manager.save_modular_config("110_delay_pools.conf", new_content):
                    flash("Directiva de delay pool eliminada exitosamente", "success")
                else:
                    flash("Error al eliminar la directiva", "error")
                return redirect(url_for("admin.manage_delay_pools"))
        
        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        new_lines = []
        directive_count = 0
        
        for line in lines:
            if line.strip().startswith("delay_") and not line.strip().startswith("#"):
                if directive_count == directive_index:
                    directive_count += 1
                    continue
                directive_count += 1
            new_lines.append(line)
        
        new_content = "\n".join(new_lines)
        config_manager.save_config(new_content)
        flash("Directiva de delay pool eliminada exitosamente", "success")
        
    except (ValueError, IndexError) as e:
        flash(f"Error al eliminar la directiva: {str(e)}", "error")
    
    return redirect(url_for("admin.manage_delay_pools"))


@admin_bp.route("/delay-pools/edit", methods=["POST"])
@admin_required
def edit_delay_pool():
    index = request.form.get("index")
    directive_line = request.form.get("directive_line")
    
    try:
        directive_index = int(index)
        
        # Check if using modular configuration
        if config_manager.is_modular:
            delay_content = config_manager.read_modular_config("110_delay_pools.conf")
            if delay_content is not None:
                lines = delay_content.split("\n")
                directive_count = 0
                
                for i, line in enumerate(lines):
                    if line.strip().startswith("delay_") and not line.strip().startswith("#"):
                        if directive_count == directive_index:
                            lines[i] = directive_line
                            break
                        directive_count += 1
                
                new_content = "\n".join(lines)
                if config_manager.save_modular_config("110_delay_pools.conf", new_content):
                    flash("Directiva de delay pool actualizada exitosamente", "success")
                else:
                    flash("Error al actualizar la directiva", "error")
                return redirect(url_for("admin.manage_delay_pools"))
        
        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        directive_count = 0
        
        for i, line in enumerate(lines):
            if line.strip().startswith("delay_") and not line.strip().startswith("#"):
                if directive_count == directive_index:
                    lines[i] = directive_line
                    break
                directive_count += 1
        
        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        flash("Directiva de delay pool actualizada exitosamente", "success")
        
    except (ValueError, IndexError) as e:
        flash(f"Error al actualizar la directiva: {str(e)}", "error")
    
    return redirect(url_for("admin.manage_delay_pools"))


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

                table_info.append(
                    {
                        "name": table_name,
                        "rows": rows,
                        "size": size,
                        "has_data": rows > 0,
                    }
                )

            except Exception as e:
                logger.warning(f"Error processing table {table_name}: {e}")
                table_info.append(
                    {
                        "name": table_name,
                        "rows": 0,
                        "size": 0,
                        "has_data": False,
                    }
                )

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
        metadata = MetaData()
        table = Table(table_name, metadata, autoload_with=engine)
        with engine.connect() as conn:
            conn.execute(table.delete())
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


@admin_bp.route("/config/split")
@admin_required
def split_config_view():
    """Vista para dividir el archivo squid.conf en archivos modulares."""
    try:
        splitter = SquidConfigSplitter()
        split_info = splitter.get_split_info()
        output_exists = splitter.check_output_dir_exists()
        files_count = splitter.count_files_in_output_dir()

        return render_template(
            "admin/split_config.html",
            split_info=split_info,
            output_dir=splitter.output_dir,
            input_file=splitter.input_file,
            output_exists=output_exists,
            files_count=files_count,
        )
    except Exception as e:
        logger.exception("Error al cargar la vista de división de configuración")
        flash(f"Error al cargar la vista: {str(e)}", "error")
        return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/api/split-config", methods=["POST"])
@api_auth_required
def split_config():
    """API endpoint para dividir el archivo squid.conf en archivos modulares."""
    try:
        data = request.get_json() or {}
        strict = data.get("strict", False)

        splitter = SquidConfigSplitter(strict=strict)

        if not os.path.exists(splitter.input_file):
            return jsonify({
                "status": "error",
                "message": f"Archivo squid.conf no encontrado en: {splitter.input_file}"
            }), 404

        results = splitter.split_config()

        return jsonify({
            "status": "success",
            "message": f"Configuración dividida exitosamente en {len(results)} archivos",
            "data": {
                "output_dir": splitter.output_dir,
                "files": results,
                "total_files": len(results)
            }
        })

    except FileNotFoundError as e:
        logger.error(f"Archivo no encontrado: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 404

    except PermissionError as e:
        logger.error(f"Error de permisos: {e}")
        return jsonify({
            "status": "error",
            "message": "No se tienen permisos suficientes para crear los archivos"
        }), 403

    except RuntimeError as e:
        logger.error(f"Error de validación: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

    except Exception as e:
        logger.exception("Error al dividir el archivo de configuración")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False

        resp = {
            "status": "error",
            "message": "Error interno al dividir la configuración"
        }
        if show_details:
            resp["details"] = str(e)
        return jsonify(resp), 500
