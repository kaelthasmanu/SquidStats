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
from loguru import logger

from config import Config
from database.database import get_session
from database.models.models import BlacklistDomain
from services.auth.auth_service import AuthService, admin_required, api_auth_required
from services.auth.user_service import (
    create_user as service_create_user,
)
from services.auth.user_service import (
    delete_user as service_delete_user,
)
from services.auth.user_service import (
    get_all_users as service_get_all_users,
)
from services.auth.user_service import (
    update_user as service_update_user,
)
from services.database.admin_helpers import (
    load_env_vars,
    save_env_vars,
)
from services.database.db_admin_service import (
    delete_table_data as service_delete_table_data,
)
from services.database.db_info_service import get_tables_info as service_get_tables_info
from services.security.blacklist_service import (
    import_domains_from_file,
    import_domains_from_url,
    merge_and_save_blacklist,
    save_custom_list,
    test_pihole_connection,
)
from services.squid.acls_service import add_acl as service_add_acl
from services.squid.acls_service import delete_acl as service_delete_acl
from services.squid.acls_service import edit_acl as service_edit_acl
from services.squid.config_service import save_config as service_save_config
from services.squid.delay_pools_service import (
    add_delay_pool as service_add_delay_pool,
)
from services.squid.delay_pools_service import (
    delete_delay_pool as service_delete_delay_pool,
)
from services.squid.delay_pools_service import (
    edit_delay_pool as service_edit_delay_pool,
)
from services.squid.http_access_service import (
    add_http_access as service_add_http_access,
)
from services.squid.http_access_service import (
    delete_http_access as service_delete_http_access,
)
from services.squid.http_access_service import (
    edit_http_access as service_edit_http_access,
)
from services.squid.http_access_service import (
    move_http_access as service_move_http_access,
)
from services.squid.split_config_service import (
    get_split_files_info as service_get_split_files_info,
)
from services.squid.split_config_service import (
    get_split_view_data as service_get_split_view_data,
)
from services.squid.split_config_service import (
    split_config as service_split_config,
)
from services.squid.squid_config_splitter import SquidConfigSplitter
from services.system.logs_service import read_logs as service_read_logs
from services.system.system_service import (
    reload_squid as service_reload_squid,
)
from services.system.system_service import (
    restart_squid as service_restart_squid,
)
from utils.admin import SquidConfigManager

admin_bp = Blueprint("admin", __name__)

# Global manager instance
config_manager = SquidConfigManager()


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
        ok, message = service_save_config(new_content, config_manager)
        if ok:
            flash(message, "success")
            return redirect(url_for("admin.view_config"))
        else:
            try:
                show_details = bool(current_app.debug)
            except RuntimeError:
                show_details = False

            if show_details:
                flash(f"Error saving configuration: {message}", "error")
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
    """Display ACLs management interface with categorization and metadata."""
    acls = config_manager.get_acls()
    return render_template("admin/acls_new.html", acls=acls)


@admin_bp.route("/acls/add", methods=["POST"])
@admin_required
def add_acl():
    """Add a new ACL with options, multiple values, and comment."""
    name = request.form.get("name")
    acl_type = request.form.get("type")
    values = request.form.getlist("values[]")
    options = request.form.getlist("options[]")
    comment = request.form.get("comment", "").strip()

    success, message = service_add_acl(
        name, acl_type, values, options, comment, config_manager
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_acls"))
    success, message = service_add_acl(
        name, acl_type, values, options, comment, config_manager
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_acls"))


@admin_bp.route("/acls/edit", methods=["POST"])
@admin_required
def edit_acl():
    """Edit an existing ACL using line number for precise targeting."""
    acl_id = request.form.get("id")
    new_name = request.form.get("name")
    acl_type = request.form.get("type")
    values = request.form.getlist("values[]")
    options = request.form.getlist("options[]")
    comment = request.form.get("comment", "").strip()

    try:
        acl_index = int(acl_id)
    except (ValueError, TypeError):
        flash("ID de ACL inválido", "error")
        return redirect(url_for("admin.manage_acls"))

    success, message = service_edit_acl(
        acl_index, new_name, acl_type, values, options, comment, config_manager
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_acls"))


@admin_bp.route("/acls/delete", methods=["POST"])
@admin_required
def delete_acl():
    """Delete an ACL using its ID (index) and line number."""
    acl_id = request.form.get("id")
    try:
        acl_index = int(acl_id)
    except (ValueError, TypeError):
        flash("ID de ACL inválido", "error")
        return redirect(url_for("admin.manage_acls"))

    success, message = service_delete_acl(acl_index, config_manager)
    flash(message, "success" if success else "error")
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


@admin_bp.route("/blacklist", methods=["GET"])
@admin_required
def manage_blacklist():
    """Render the blacklist management UI."""
    env_vars = load_env_vars()
    # Provide current blacklist domains to the template — now read from DB
    session = get_session()
    try:
        # Only show entries that were added via the 'custom' source
        rows = (
            session.query(BlacklistDomain)
            .filter(
                BlacklistDomain.active == 1,
                BlacklistDomain.source.in_(["custom", "env_migration"]),
            )
            .order_by(BlacklistDomain.domain)
            .all()
        )
        # Provide domains separated by newlines so the custom textarea can be pre-filled
        blacklist = "\n".join([r.domain for r in rows])
    finally:
        session.close()

    return render_template(
        "admin/blacklist.html", env_vars=env_vars, blacklist=blacklist
    )


@admin_bp.route("/blacklist/test-connection", methods=["POST"])
@admin_required
def blacklist_test_connection():
    host = request.form.get("host") or request.form.get("pihole_host")
    token = request.form.get("token") or request.form.get("api_token")
    if not host:
        flash("Host de Pi-hole no proporcionado", "error")
        return redirect(url_for("admin.manage_blacklist"))
    success, msg = test_pihole_connection(host, token)
    flash(msg, "success" if success else "error")

    return redirect(url_for("admin.manage_blacklist"))


@admin_bp.route("/blacklist/sync", methods=["POST"])
@admin_required
def blacklist_sync():
    # Placeholder: kick off background sync job in production
    # For now just flash success and return
    flash("Sincronización de listas iniciada (en segundo plano)", "success")
    return redirect(url_for("admin.manage_blacklist"))


@admin_bp.route("/blacklist/import", methods=["POST"])
@admin_required
def blacklist_import():
    # Import domains from uploaded file or URL and append to BLACKLIST_DOMAINS
    domains = set()

    # Handle file upload
    uploaded = request.files.get("file")
    if uploaded and uploaded.filename:
        try:
            file_domains = import_domains_from_file(uploaded)
            domains.update(file_domains)
            flash("Archivo importado correctamente", "success")
        except Exception as e:
            logger.exception("Error importando archivo de blacklist")
            try:
                show_details = bool(current_app.debug)
            except RuntimeError:
                show_details = False
            if show_details:
                flash(f"Error al procesar el archivo: {str(e)}", "error")
            else:
                flash("Error al procesar el archivo", "error")
            return redirect(url_for("admin.manage_blacklist"))

    # Handle URL import
    url = request.form.get("url")
    if url:
        ok, url_domains, err = import_domains_from_url(url)
        if ok:
            domains.update(url_domains)
            flash("Lista importada desde URL correctamente", "success")
        else:
            flash(f"Error importando desde URL: {err}", "error")

    # Merge with existing and save
    try:
        merge_and_save_blacklist(domains)
        flash("Blacklist actualizada exitosamente", "success")
    except Exception as e:
        logger.exception("Error guardando BLACKLIST_DOMAINS")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False
        if show_details:
            flash(f"Error al guardar blacklist: {str(e)}", "error")
        else:
            flash("Error al guardar blacklist", "error")

    return redirect(url_for("admin.manage_blacklist"))


@admin_bp.route("/blacklist/save-custom", methods=["POST"])
@admin_required
def blacklist_save_custom():
    custom = request.form.get("custom_list", "")
    if not custom.strip():
        flash("Lista personalizada vacía", "error")
        return redirect(url_for("admin.manage_blacklist"))

    # parse lines and commas
    items = []
    for line in custom.splitlines():
        for part in line.split(","):
            d = part.strip()
            if d:
                items.append(d)

    try:
        save_custom_list(items)
        flash("Lista personalizada guardada en BLACKLIST_DOMAINS", "success")
    except Exception as e:
        logger.exception("Error guardando lista personalizada")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False
        if show_details:
            flash(f"Error al guardar la lista: {str(e)}", "error")
        else:
            flash("Error al guardar la lista", "error")

    return redirect(url_for("admin.manage_blacklist"))


@admin_bp.route("/http-access/delete", methods=["POST"])
@admin_required
def delete_http_access():
    index = request.form.get("index")
    try:
        rule_index = int(index)
    except (ValueError, TypeError):
        flash("Índice de regla inválido", "error")
        return redirect(url_for("admin.manage_http_access"))

    success, message = service_delete_http_access(rule_index, config_manager)
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_http_access"))


@admin_bp.route("/http-access/edit", methods=["POST"])
@admin_required
def edit_http_access():
    """Edit an http_access rule with support for multiple ACLs and description"""
    index = request.form.get("index")
    action = request.form.get("action")
    acls = request.form.getlist("acls[]")
    description = request.form.get("description", "").strip()

    try:
        rule_index = int(index)
    except (ValueError, TypeError):
        flash("Índice de regla inválido", "error")
        return redirect(url_for("admin.manage_http_access"))

    success, message = service_edit_http_access(
        rule_index, action, acls, description, config_manager
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_http_access"))


@admin_bp.route("/http-access/add", methods=["POST"])
@admin_required
def add_http_access():
    """Add a new http_access rule"""
    action = request.form.get("action")
    acls = request.form.getlist("acls[]")
    description = request.form.get("description", "").strip()

    success, message = service_add_http_access(
        action, acls, description, config_manager
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_http_access"))


@admin_bp.route("/http-access/move", methods=["POST"])
@admin_required
def move_http_access():
    """Move an http_access rule up or down"""
    index = request.form.get("index")
    direction = request.form.get("direction")  # 'up' or 'down'

    try:
        rule_index = int(index)
    except (ValueError, TypeError):
        flash("Índice de regla inválido", "error")
        return redirect(url_for("admin.manage_http_access"))

    success, message = service_move_http_access(rule_index, direction, config_manager)
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_http_access"))


@admin_bp.route("/delay-pools/delete", methods=["POST"])
@admin_required
def delete_delay_pool():
    """Delete all directives related to a specific delay pool"""
    pool_number = request.form.get("pool_number")

    success, message = service_delete_delay_pool(pool_number, config_manager)
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_delay_pools"))


@admin_bp.route("/delay-pools/edit", methods=["POST"])
@admin_required
def edit_delay_pool():
    """Edit all directives related to a specific delay pool"""
    pool_number = request.form.get("pool_number")
    pool_class = request.form.get("pool_class")
    parameters = request.form.get("parameters")
    access_actions = request.form.getlist("access_action[]")
    access_acls = request.form.getlist("access_acl[]")

    success, message = service_edit_delay_pool(
        pool_number, pool_class, parameters, access_actions, access_acls, config_manager
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_delay_pools"))


@admin_bp.route("/delay-pools/add", methods=["POST"])
@admin_required
def add_delay_pool():
    """Add a new delay pool with all its directives"""
    pool_number = request.form.get("pool_number")
    pool_class = request.form.get("pool_class")
    parameters = request.form.get("parameters")
    access_actions = request.form.getlist("access_action[]")
    access_acls = request.form.getlist("access_acl[]")

    success, message = service_add_delay_pool(
        pool_number, pool_class, parameters, access_actions, access_acls, config_manager
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.manage_delay_pools"))


@admin_bp.route("/view-logs")
@admin_required
def view_logs():
    # Get the requested number of lines (default 250, maximum 1000)
    max_lines = request.args.get("lines", 250, type=int)
    max_lines = min(max(max_lines, 10), 1000)  # Between 10 and 1000 lines

    log_files = [Config.SQUID_LOG, Config.SQUID_CACHE_LOG]
    logs = service_read_logs(log_files, max_lines, debug=bool(current_app.debug))
    return render_template("admin/logs.html", logs=logs, max_lines=max_lines)


@admin_bp.route("/users")
@admin_required
def manage_users():
    users = service_get_all_users()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users/create", methods=["GET", "POST"])
@admin_required
def create_user():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role", "admin")

        ok, message = service_create_user(username, password, role)
        flash(message, "success" if ok else "error")
        if ok:
            return redirect(url_for("admin.manage_users"))

    return render_template("admin/user_form.html", user=None, action="create")


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id):
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")
        is_active = 1 if request.form.get("is_active") else 0

        ok, message = service_update_user(user_id, username, password, role, is_active)
        flash(message, "success" if ok else "error")
        if ok:
            return redirect(url_for("admin.manage_users"))

    users = AuthService.get_all_users()
    user = next((u for u in users if u["id"] == user_id), None)
    if not user:
        flash("Usuario no encontrado", "error")
        return redirect(url_for("admin.manage_users"))

    return render_template("admin/user_form.html", user=user, action="edit")


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    ok, message = service_delete_user(user_id)
    flash(message, "success" if ok else "error")
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/api/restart-squid", methods=["POST"])
@api_auth_required
def restart_squid():
    success, message, details = service_restart_squid()
    if success:
        return jsonify({"status": "success", "message": message})
    resp = {"status": "error", "message": message}
    if bool(current_app.debug) and details:
        resp["details"] = details
    return jsonify(resp), 500


@admin_bp.route("/api/reload-squid", methods=["POST"])
@api_auth_required
def reload_squid():
    success, message, details = service_reload_squid()
    if success:
        return jsonify({"status": "success", "message": message})
    resp = {"status": "error", "message": message}
    if bool(current_app.debug) and details:
        resp["details"] = details
    return jsonify(resp), 500


@admin_bp.route("/api/get-tables", methods=["GET"])
@api_auth_required
def get_tables():
    resp, code = service_get_tables_info()
    return jsonify(resp), code


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

        # Prevent deletion of critical tables like admin_users and alembic_version
        if table_name == "admin_users" or table_name == "alembic_version":
            return jsonify(
                {
                    "status": "error",
                    "message": "No se puede eliminar estas tablas críticas",
                }
            ), 400

        resp, code = service_delete_table_data(table_name)
        return jsonify(resp), code

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
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False
        if show_details:
            flash(f"Error al cargar la vista: {str(e)}", "error")
        else:
            flash("Error al cargar la vista", "error")
        return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/api/split-config", methods=["POST"])
@api_auth_required
def split_config():
    """API endpoint para dividir el archivo squid.conf en archivos modulares."""
    try:
        data = request.get_json() or {}
        strict = data.get("strict", False)

        resp, code = service_split_config(strict=strict)

        # Reload config_manager to detect modular configuration if successful
        if code == 200:
            global config_manager
            config_manager = SquidConfigManager()
            logger.info("Config manager reloaded after splitting configuration")

        return jsonify(resp), code

    except FileNotFoundError as e:
        logger.error(f"Archivo no encontrado: {e}")
        return jsonify(
            {
                "status": "error",
                "message": "Archivo requerido no encontrado. Verifique la configuración del archivo squid.conf.",
            }
        ), 404

    except PermissionError as e:
        logger.error(f"Error de permisos: {e}")
        return jsonify(
            {
                "status": "error",
                "message": "No se tienen permisos suficientes para crear los archivos",
            }
        ), 403

    except RuntimeError as e:
        logger.error(f"Error de validación: {e}")
        return jsonify(
            {
                "status": "error",
                "message": "Error de validación de la configuración",
            }
        ), 400

    except Exception as e:
        logger.exception("Error al dividir el archivo de configuración")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False

        resp = {
            "status": "error",
            "message": "Error interno al dividir la configuración",
        }
        if show_details:
            resp["details"] = str(e)
        return jsonify(resp), 500


@admin_bp.route("/api/get-split-files", methods=["GET"])
@api_auth_required
def get_split_files():
    """API endpoint para obtener la lista de archivos generados en squid.d."""
    splitter = SquidConfigSplitter()
    result = service_get_split_files_info(splitter.output_dir)

    if result.get("status") == "success":
        return jsonify(result)
    return jsonify(result), result.get("code", 500)
