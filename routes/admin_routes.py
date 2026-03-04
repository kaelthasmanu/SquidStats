import hashlib
import os
import re

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
    delete_blacklist_by_source_url,
    get_url_blacklists_with_counts,
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
    add_http_deny_blocklist as service_add_http_deny_blocklist,
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
from services.squid.http_access_service import (
    remove_http_deny_blocklist as service_remove_http_deny_blocklist,
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

    url_lists = get_url_blacklists_with_counts()

    # Determine which lists are currently enforced in Squid config
    enforced_urls = _get_enforced_blocklist_urls(config_manager)
    for item in url_lists:
        item["enforced"] = item["source_url"] in enforced_urls
    custom_enforced = "__custom__" in enforced_urls

    return render_template(
        "admin/blacklist.html",
        env_vars=env_vars,
        blacklist=blacklist,
        url_lists=url_lists,
        custom_enforced=custom_enforced,
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
    file_domains = set()
    url_domains = set()

    # Handle file upload
    uploaded = request.files.get("file")
    if uploaded and uploaded.filename:
        try:
            file_domains = import_domains_from_file(uploaded)
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
        ok, imported_url_domains, err = import_domains_from_url(url)
        if ok:
            url_domains.update(imported_url_domains)
            flash("Lista importada desde URL correctamente", "success")
        else:
            flash(f"Error importando desde URL: {err}", "error")

    # Merge with existing and save, preserving source metadata
    try:
        if file_domains:
            merge_and_save_blacklist(file_domains, source="file")

        if url_domains:
            merge_and_save_blacklist(url_domains, source="url", source_url=url)

        if not file_domains and not url_domains:
            flash("No se encontraron dominios para importar", "warning")
        else:
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


@admin_bp.route("/blacklist/delete-list", methods=["POST"])
@admin_required
def blacklist_delete_list():
    url = request.form.get("source_url")
    if not url:
        flash("URL no proporcionada", "error")
        return redirect(url_for("admin.manage_blacklist"))
    count = delete_blacklist_by_source_url(url)
    # Also disable enforcement if the list was enforced
    _disable_single_blocklist(url, config_manager)
    flash(f"Lista eliminada: {url} ({count} dominios)", "success")
    return redirect(url_for("admin.manage_blacklist"))


# ---------------------------------------------------------------------------
# Blocklist enforcement helpers & API
# ---------------------------------------------------------------------------

BLOCKLIST_ACL_NAME = "squidstats_blocklist"


def _is_allowed_blocklist_filename(filename: str) -> bool:
    """Allow only expected generated blocklist filenames."""
    from services.squid.acls_service import BLOCKLIST_PREFIX

    if not filename:
        return False

    # Never allow path separators or traversal sequences in filenames
    if os.path.basename(filename) != filename:
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False

    pattern = rf"^{re.escape(BLOCKLIST_PREFIX)}(?:custom|[a-f0-9]{{64}})\.txt$"
    return bool(re.fullmatch(pattern, filename))


def _build_blocklist_filename(source_url: str | None) -> str:
    """Build a deterministic safe filename for a blocklist source URL."""
    from services.squid.acls_service import BLOCKLIST_PREFIX

    if source_url is None:
        filename = f"{BLOCKLIST_PREFIX}custom.txt"
    else:
        if not _validate_source_url(source_url):
            raise ValueError("Invalid source URL")
        digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest().lower()
        filename = f"{BLOCKLIST_PREFIX}{digest}.txt"

    if not _is_allowed_blocklist_filename(filename):
        raise ValueError("Invalid blocklist filename")

    return filename


def _resolve_safe_blocklist_path(base_dir: str, filename: str) -> str | None:
    """Resolve and validate a blocklist file path to prevent path traversal.

    Ensures the resolved path is within base_dir using os.path.commonpath.
    Returns the safe path or None if traversal is detected.
    """
    if not _is_allowed_blocklist_filename(filename):
        return None

    base_dir = os.path.realpath(base_dir)
    candidate = os.path.realpath(os.path.join(base_dir, filename))

    try:
        if os.path.commonpath([base_dir, candidate]) != base_dir:
            return None
    except ValueError:
        # commonpath raises ValueError if paths are on different drives (Windows)
        return None

    return candidate


def _validate_source_url(source_url: str | None) -> bool:
    """Validate that source_url is a well-formed URL."""
    if not source_url:
        return True  # None is allowed for custom lists

    from urllib.parse import urlparse

    parsed = urlparse(source_url)
    # Ensure it's a proper URL with scheme and netloc
    if not (parsed.scheme and parsed.netloc):
        return False

    # Reject URLs with suspicious path traversal patterns
    if ".." in source_url or source_url.startswith("/") or "\\" in source_url:
        return False

    # Additional validation: reject control characters and other suspicious patterns
    if any(c in source_url for c in ["\x00", "\n", "\r", "\t"]):
        return False

    # Ensure URL is reasonably sized to prevent DoS
    if len(source_url) > 2048:
        return False

    return True


def _get_enforced_blocklist_urls(cm) -> set[str]:
    """Return the set of source_url values currently enforced as Squid ACLs.

    Parses the ACL config to find ``acl squidstats_blocklist dstdomain "..."``
    lines and maps each file back to its source_url.  Custom lists are
    represented by the sentinel ``__custom__``.
    """
    from services.squid.acls_service import BLOCKLIST_PREFIX

    enforced: set[str] = set()

    # Read configuration
    if cm.is_modular:
        content = cm.read_modular_config("100_acls.conf")
    else:
        content = cm.config_content

    if not content:
        return enforced

    # Pre-fetch all source URLs from DB to avoid queries in loop
    session = get_session()
    try:
        url_to_filename = {}
        urls = (
            session.query(BlacklistDomain.source_url)
            .filter(BlacklistDomain.source_url.isnot(None))
            .distinct()
            .all()
        )
        for (url,) in urls:
            from services.squid.acls_service import _sanitize_filename

            # Current safe naming (hash-based)
            try:
                url_to_filename[_build_blocklist_filename(url)] = url
            except ValueError:
                logger.warning("Skipping invalid blacklist source_url in DB mapping")
            # Legacy naming fallback for previously generated ACL entries
            url_to_filename[_sanitize_filename(url)] = url
    finally:
        session.close()

    for line in content.split("\n"):
        stripped = line.strip()
        if (
            stripped.startswith(f"acl {BLOCKLIST_ACL_NAME} ")
            and "dstdomain" in stripped
            and BLOCKLIST_PREFIX in stripped
        ):
            # Extract file path between quotes
            start = stripped.find('"')
            end = stripped.rfind('"')
            if start != -1 and end > start:
                filepath = stripped[start + 1 : end]
                fname = os.path.basename(filepath)
                if fname == f"{BLOCKLIST_PREFIX}custom.txt":
                    enforced.add("__custom__")
                else:
                    # Lookup source_url from pre-fetched mapping
                    source_url = url_to_filename.get(fname)
                    if source_url:
                        enforced.add(source_url)

    return enforced


def _get_enforced_blocklist_paths(cm) -> dict[str, str]:
    """Return validated enforced blocklist paths keyed by filename."""
    from services.squid.acls_service import (
        BLOCKLIST_PREFIX,
        _get_blocklists_dir,
    )

    enforced_paths: dict[str, str] = {}
    blocklists_dir = _get_blocklists_dir(cm)

    if cm.is_modular:
        content = cm.read_modular_config("100_acls.conf")
    else:
        content = cm.config_content

    if not content:
        return enforced_paths

    for line in content.split("\n"):
        stripped = line.strip()
        if (
            stripped.startswith(f"acl {BLOCKLIST_ACL_NAME} ")
            and "dstdomain" in stripped
            and BLOCKLIST_PREFIX in stripped
        ):
            match = re.search(r"""dstdomain\s+["']([^"']+)["']""", stripped)
            if not match:
                continue

            filepath = match.group(1)
            filename = os.path.basename(filepath)
            safe_path = _resolve_safe_blocklist_path(blocklists_dir, filename)
            if safe_path:
                enforced_paths[filename] = safe_path

    return enforced_paths


def _enable_single_blocklist(source_url: str | None, cm) -> tuple[bool, str]:
    """Enable Squid enforcement for a single blocklist (by source_url).

    - Writes the domain file for that source.
    - Adds the ACL directive.
    - Ensures the http_access deny rule exists.
    """
    from services.squid.acls_service import (
        _get_blocklists_dir,
        _write_domains_file,
    )

    # Validate source_url if provided
    if source_url is not None and not _validate_source_url(source_url):
        return False, "URL de fuente inválida"

    session = get_session()
    try:
        if source_url:
            rows = (
                session.query(BlacklistDomain.domain)
                .filter(
                    BlacklistDomain.active == 1,
                    BlacklistDomain.source_url == source_url,
                )
                .order_by(BlacklistDomain.domain)
                .all()
            )
            label = source_url
        else:
            rows = (
                session.query(BlacklistDomain.domain)
                .filter(
                    BlacklistDomain.active == 1,
                    BlacklistDomain.source_url.is_(None),
                )
                .order_by(BlacklistDomain.domain)
                .all()
            )
            label = "custom"
    except Exception:
        logger.exception("Error consultando dominios para activar blocklist")
        return False, "Error al consultar dominios"
    finally:
        session.close()

    try:
        filename = _build_blocklist_filename(source_url if source_url else None)
    except ValueError:
        return False, "URL de fuente inválida"

    domains = [d[0] for d in rows]
    if not domains:
        return False, f"No hay dominios activos para '{label}'"

    # Write file
    blocklists_dir = _get_blocklists_dir(cm)
    safe_path = _resolve_safe_blocklist_path(blocklists_dir, filename)
    if not safe_path:
        logger.error("Path traversal blocked for source: %s", label)
        return False, f"Nombre de archivo inválido para: '{label}'"
    ok, written_count = _write_domains_file(safe_path, domains, blocklists_dir)
    if not ok:
        return False, f"Error escribiendo archivo para '{label}'"

    # Add ACL directive (append without removing others)
    acl_line = f'acl {BLOCKLIST_ACL_NAME} dstdomain "{safe_path}"'
    comment_line = f"# Blocklist: {label} ({written_count} dominios)"

    try:
        if cm.is_modular:
            acl_content = cm.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                # Remove only this specific file's ACL if it exists already
                lines = [
                    ln
                    for ln in lines
                    if not (
                        ln.strip() == acl_line
                        or ln.strip() == acl_line.replace('"', "'")
                    )
                ]
                # Remove orphaned comments for this label
                lines = [ln for ln in lines if not ln.strip() == comment_line]
                lines.append(comment_line)
                lines.append(acl_line)
                new_content = "\n".join(lines)
                if not cm.save_modular_config("100_acls.conf", new_content):
                    return False, "Error guardando ACL en config modular"
            else:
                return False, "No se pudo leer la config modular"
        else:
            lines = cm.config_content.split("\n")
            lines = [
                ln
                for ln in lines
                if not (
                    ln.strip() == acl_line or ln.strip() == acl_line.replace('"', "'")
                )
            ]
            lines = [ln for ln in lines if not ln.strip() == comment_line]
            acl_section_end = -1
            for i, line in enumerate(lines):
                if line.strip().startswith("acl "):
                    acl_section_end = i
            if acl_section_end != -1:
                lines.insert(acl_section_end + 1, comment_line)
                lines.insert(acl_section_end + 2, acl_line)
            else:
                lines.append(comment_line)
                lines.append(acl_line)
            new_content = "\n".join(lines)
            cm.save_config(new_content)
    except Exception:
        logger.exception("Error agregando ACL para blocklist individual")
        return False, "Error al agregar ACL"

    # Ensure http_access deny rule exists
    ok, msg = service_add_http_deny_blocklist(BLOCKLIST_ACL_NAME, cm)
    if not ok:
        return False, msg

    return True, f"Blocklist '{label}' activada con {len(domains)} dominios"


def _disable_single_blocklist(source_url: str | None, cm) -> tuple[bool, str]:
    """Disable Squid enforcement for a single blocklist.

    - Removes the ACL line for this source.
    - Deletes the domain file.
    - If no blocklist ACLs remain, also removes the http_access deny rule.
    """
    # Validate source_url if provided
    if source_url is not None:
        if not isinstance(source_url, str):
            return False, "Formato de URL inválido"
        if not _validate_source_url(source_url):
            return False, "URL de fuente inválida"

    if source_url:
        label = source_url
    else:
        label = "custom"

    try:
        candidate_filename = _build_blocklist_filename(source_url if source_url else None)
    except ValueError:
        return False, "URL de fuente inválida"

    enforced_paths = _get_enforced_blocklist_paths(cm)
    safe_path = enforced_paths.get(candidate_filename)
    if not safe_path:
        return False, f"Blocklist '{label}' no está activada"

    acl_line = f'acl {BLOCKLIST_ACL_NAME} dstdomain "{safe_path}"'

    # Remove ACL directive
    try:
        if cm.is_modular:
            acl_content = cm.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                new_lines = []
                for ln in lines:
                    stripped = ln.strip()
                    if stripped == acl_line or stripped == acl_line.replace('"', "'"):
                        # Also remove the comment above
                        if new_lines and new_lines[-1].strip().startswith(
                            "# Blocklist:"
                        ):
                            new_lines.pop()
                        continue
                    new_lines.append(ln)
                new_content = "\n".join(new_lines)
                cm.save_modular_config("100_acls.conf", new_content)

        lines = cm.config_content.split("\n")
        new_lines = []
        for ln in lines:
            stripped = ln.strip()
            if stripped == acl_line or stripped == acl_line.replace('"', "'"):
                if new_lines and new_lines[-1].strip().startswith("# Blocklist:"):
                    new_lines.pop()
                continue
            new_lines.append(ln)
        new_content = "\n".join(new_lines)
        cm.save_config(new_content)
    except Exception:
        logger.exception("Error eliminando ACL de blocklist individual")
        return False, "Error al eliminar ACL"

    # Delete file
    if os.path.isfile(safe_path):
        try:
            os.remove(safe_path)
        except OSError:
            logger.exception(f"Error eliminando archivo: {safe_path}")

    # Check if any blocklist ACLs remain; if not, remove http_access deny rule too
    remaining = _get_enforced_blocklist_urls(cm)
    if not remaining:
        service_remove_http_deny_blocklist(BLOCKLIST_ACL_NAME, cm)

    return True, f"Blocklist '{label}' desactivada"


@admin_bp.route("/api/blocklist/toggle", methods=["POST"])
@api_auth_required
def blocklist_toggle():
    """Toggle Squid enforcement for a single blocklist.

    Expects JSON: ``{"source_url": "...", "enable": true/false}``
    Use ``source_url: null`` for the custom/manual list.
    """
    data = request.get_json()
    if data is None:
        return jsonify({"status": "error", "message": "JSON inválido"}), 400

    source_url = data.get("source_url")  # None for custom
    enable = data.get("enable", False)

    try:
        if enable:
            ok, msg = _enable_single_blocklist(source_url, config_manager)
        else:
            ok, msg = _disable_single_blocklist(source_url, config_manager)

        if ok:
            return jsonify({"status": "success", "message": msg})
        return jsonify({"status": "error", "message": msg}), 400
    except Exception as e:
        logger.exception("Error en toggle de blocklist")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False
        resp = {
            "status": "error",
            "message": "Error interno al cambiar estado de blocklist",
        }
        if show_details:
            resp["details"] = str(e)
        return jsonify(resp), 500
