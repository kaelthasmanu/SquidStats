from flask import Blueprint, current_app, jsonify, request
from loguru import logger
from werkzeug.exceptions import BadRequest

from database.database import get_session
from routes.admin.helpers import get_config_manager, json_error, json_success
from services.analytics.auditoria_service import (
    get_all_usernames,
    run_audit_operation,
)
from services.auth.auth_service import admin_required
from services.notifications.notifications import (
    delete_all_notifications,
    delete_notification,
    get_all_notifications,
    mark_notifications_read,
)
from services.squid.user_restrictions_service import (
    block_user,
    get_user_status,
    throttle_user,
    unblock_user,
    unthrottle_user,
)
from services.system.metrics_service import MetricsService
from services.system.system_service import reload_squid, restart_squid

api_bp = Blueprint("api", __name__)


REQUIRED_FIELDS = {
    "user_summary": ["username"],
    "daily_activity": ["start_date", "end_date"],
    "keyword_search": ["keyword"],
    "social_media_activity": ["social_media_sites"],
    "ip_activity": ["ip_address"],
    "response_code_search": ["response_code"],
    "total_data_consumed": ["start_date", "end_date"],
}


@api_bp.route("/metrics/today")
def get_today_metrics():
    try:
        results = MetricsService.get_metrics_today()
        return jsonify(results)
    except Exception as e:
        logger.error(f"Error retrieving today's metrics: {e}")
        return jsonify([])


@api_bp.route("/metrics/24hours")
def get_24hours_metrics():
    try:
        results = MetricsService.get_metrics_last_24_hours()
        return jsonify(results)
    except Exception as e:
        logger.error(f"Error retrieving 24 hours metrics: {e}")
        return jsonify([])


@api_bp.route("/metrics/latest")
def get_latest_metric():
    try:
        result = MetricsService.get_latest_metric()
        return jsonify(result) if result else jsonify({})
    except Exception as e:
        logger.error(f"Error retrieving latest metric: {e}")
        return jsonify({})


@api_bp.route("/all-users", methods=["GET"])
def api_get_all_users():
    db = get_session()
    try:
        users = get_all_usernames(db)
        return jsonify(users)
    except Exception as e:
        logger.exception("Error retrieving all users")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False

        resp = {"error": "Internal server error"}
        if show_details:
            resp["details"] = str(e)
        return jsonify(resp), 500
    finally:
        db.close()


@api_bp.route("/run-audit", methods=["POST"])
def api_run_audit():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    audit_type = data.get("audit_type")

    db = get_session()

    try:
        validate_required_fields(audit_type, data)
        result = run_audit_operation(db, audit_type, data)
        return jsonify(result)

    except BadRequest as e:
        logger.warning(f"Bad request in audit API: {e}")
        return jsonify({"error": "Bad request"}), 400

    except ValueError:
        return jsonify({"error": "Invalid numeric value"}), 400

    except Exception:
        logger.exception("Audit API error")
        return jsonify({"error": "Internal server error"}), 500

    finally:
        db.close()


# API para notificaciones del sistema
@api_bp.route("/notifications", methods=["GET"])
def api_get_notifications():
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        return jsonify(get_all_notifications(page=page, per_page=per_page))
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify({"unread_count": 0, "notifications": [], "pagination": {}})


@api_bp.route("/notifications/mark-read", methods=["POST"])
def api_mark_notifications_read():
    try:
        data = request.get_json()
        notification_ids = data.get("notification_ids", data.get("ids", []))
        mark_notifications_read(notification_ids)
        return jsonify(
            {"success": True, "unread_count": get_all_notifications()["unread_count"]}
        )
    except Exception as e:
        logger.exception("Error marking notifications as read")
        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False
        resp = {"success": False, "error": "Internal server error"}
        if show_details:
            resp["details"] = str(e)
        return jsonify(resp), 500


@api_bp.route("/notifications/<int:notification_id>", methods=["DELETE"])
def api_delete_notification(notification_id):
    try:
        delete_notification(notification_id)
        return json_success(
            "Notification deleted",
            extra={"unread_count": get_all_notifications()["unread_count"]},
        )
    except Exception as e:
        logger.exception("Error deleting notification")
        return json_error("Internal server error", 500, details=str(e))


@api_bp.route("/notifications/delete-all", methods=["DELETE"])
def api_delete_all_notifications():
    try:
        delete_all_notifications()
        return json_success("All notifications deleted", extra={"unread_count": 0})
    except Exception as e:
        logger.exception("Error deleting all notifications")
        return json_error("Internal server error", 500, details=str(e))


@api_bp.route("/restart-squid", methods=["POST"])
@admin_required
def api_restart_squid():
    success, message, details = restart_squid()
    if success:
        return json_success(message)
    return json_error(
        message or "Could not restart squid",
        500,
        details=str(details) if details else None,
    )


@api_bp.route("/reload-squid", methods=["POST"])
@admin_required
def api_reload_squid():
    success, message, details = reload_squid()
    if success:
        return json_success(message)
    return json_error(
        message or "Could not reload squid",
        500,
        details=str(details) if details else None,
    )


def validate_required_fields(audit_type, data):
    required = REQUIRED_FIELDS.get(audit_type, [])
    missing = [field for field in required if not data.get(field)]
    if missing:
        raise BadRequest(f"Missing required fields: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# Connections: block / throttle actions
# ---------------------------------------------------------------------------


@api_bp.route("/connections/status", methods=["GET"])
@admin_required
def api_connection_status():
    ip = request.args.get("ip", "").strip()
    if not ip:
        return json_error("Se requiere el parámetro 'ip'", 400)
    db = get_session()
    try:
        status = get_user_status(ip, db)
        return jsonify({"status": "success", **status})
    except Exception:
        logger.exception("Error getting connection status")
        return json_error("Error interno", 500)
    finally:
        db.close()


@api_bp.route("/connections/block", methods=["POST"])
@admin_required
def api_block_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    ip = str(data.get("ip", "")).strip()
    if not username or not ip:
        return json_error("Se requieren los campos 'username' e 'ip'", 400)

    db = get_session()
    try:
        cm = get_config_manager()
        success, message = block_user(username, ip, db, cm)
        if success:
            reload_squid()
            return json_success(message)
        return json_error(message, 409)
    except Exception:
        logger.exception("Error blocking user")
        return json_error("Error interno al bloquear el usuario", 500)
    finally:
        db.close()


@api_bp.route("/connections/unblock", methods=["POST"])
@admin_required
def api_unblock_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    ip = str(data.get("ip", "")).strip()
    if not username or not ip:
        return json_error("Se requieren los campos 'username' e 'ip'", 400)

    db = get_session()
    try:
        cm = get_config_manager()
        success, message = unblock_user(username, ip, db, cm)
        if success:
            reload_squid()
            return json_success(message)
        return json_error(message, 409)
    except Exception:
        logger.exception("Error unblocking user")
        return json_error("Error interno al desbloquear el usuario", 500)
    finally:
        db.close()


@api_bp.route("/connections/throttle", methods=["POST"])
@admin_required
def api_throttle_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    ip = str(data.get("ip", "")).strip()
    try:
        pool_number = int(data.get("pool_number"))
    except (TypeError, ValueError):
        return json_error("El campo 'pool_number' debe ser un entero", 400)
    if not username or not ip:
        return json_error(
            "Se requieren los campos 'username', 'ip' y 'pool_number'", 400
        )

    db = get_session()
    try:
        cm = get_config_manager()
        success, message = throttle_user(username, ip, pool_number, db, cm)
        if success:
            reload_squid()
            return json_success(message)
        return json_error(message, 409)
    except Exception:
        logger.exception("Error throttling user")
        return json_error("Error interno al reducir la velocidad", 500)
    finally:
        db.close()


@api_bp.route("/connections/unthrottle", methods=["POST"])
@admin_required
def api_unthrottle_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    ip = str(data.get("ip", "")).strip()
    if not username or not ip:
        return json_error("Se requieren los campos 'username' e 'ip'", 400)

    db = get_session()
    try:
        cm = get_config_manager()
        success, message = unthrottle_user(username, ip, db, cm)
        if success:
            reload_squid()
            return json_success(message)
        return json_error(message, 409)
    except Exception:
        logger.exception("Error unthrottling user")
        return json_error("Error interno al restaurar la velocidad", 500)
    finally:
        db.close()


@api_bp.route("/delay-pools", methods=["GET"])
@admin_required
def api_list_delay_pools():
    try:
        cm = get_config_manager()
        pools = cm.get_delay_pools()
        return jsonify({"status": "success", "pools": pools})
    except Exception:
        logger.exception("Error listing delay pools")
        return json_error("Error interno al listar delay pools", 500)
