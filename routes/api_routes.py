from flask import Blueprint, current_app, jsonify, request
from loguru import logger

from database.database import get_session
from services.auditoria_service import (
    find_by_ip,
    find_by_keyword,
    find_by_response_code,
    find_denied_access,
    find_social_media_activity,
    get_all_usernames,
    get_daily_activity,
    get_top_ips_by_data,
    get_top_urls_by_data,
    get_top_users_by_data,
    get_top_users_by_requests,
    get_total_data_consumed,
    get_user_activity_summary,
)
from services.metrics_service import MetricsService
from services.notifications import (
    delete_all_notifications,
    delete_notification,
    get_all_notifications,
    mark_notifications_read,
)

api_bp = Blueprint("api", __name__)


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
    audit_type = data.get("audit_type")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    username = data.get("username")
    keyword = data.get("keyword")
    ip_address = data.get("ip_address")
    response_code = data.get("response_code")
    social_media_sites = data.get("social_media_sites")

    db = get_session()
    try:
        if audit_type == "user_summary":
            if not username:
                return jsonify({"error": "Username is required."}), 400
            result = get_user_activity_summary(db, username, start_date, end_date)
        elif audit_type == "top_users_data":
            result = get_top_users_by_data(db, start_date, end_date)
        elif audit_type == "top_urls_data":
            result = get_top_urls_by_data(db, start_date, end_date)
        elif audit_type == "top_users_requests":
            result = get_top_users_by_requests(db, start_date, end_date)
        elif audit_type == "top_ips_data":
            result = get_top_ips_by_data(db, start_date, end_date)
        elif audit_type == "daily_activity":
            if not start_date:
                return jsonify({"error": "Start date is required."}), 400
            if not end_date:
                return jsonify({"error": "End date is required."}), 400
            result = get_daily_activity(db, start_date, username)
        elif audit_type == "denied_access":
            result = find_denied_access(db, start_date, end_date, username)
        elif audit_type == "keyword_search":
            if not keyword:
                return jsonify({"error": "Keyword is required."}), 400
            result = find_by_keyword(db, start_date, end_date, keyword, username)
        elif audit_type == "social_media_activity":
            if not social_media_sites:
                return jsonify(
                    {"error": "At least one social media site must be selected."}
                ), 400
            result = find_social_media_activity(
                db, start_date, end_date, social_media_sites, username
            )
        elif audit_type == "ip_activity":
            if not ip_address:
                return jsonify({"error": "IP address is required."}), 400
            result = find_by_ip(db, start_date, end_date, ip_address)
        elif audit_type == "response_code_search":
            if not response_code:
                return jsonify({"error": "Response code is required."}), 400
            result = find_by_response_code(
                db, start_date, end_date, int(response_code), username
            )
        elif audit_type == "total_data_consumed":
            if not start_date:
                return jsonify({"error": "Start date is required."}), 400
            if not end_date:
                return jsonify({"error": "End date is required."}), 400
            result = get_total_data_consumed(db, start_date, end_date)
        else:
            return jsonify({"error": "Invalid audit type."}), 400

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error en la API de auditoría: {e}")
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
        return jsonify(
            {"success": True, "unread_count": get_all_notifications()["unread_count"]}
        )
    except Exception as e:
        logger.error(f"Error deleting notification: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500


@api_bp.route("/notifications/delete-all", methods=["DELETE"])
def api_delete_all_notifications():
    try:
        delete_all_notifications()
        return jsonify({"success": True, "unread_count": 0})
    except Exception as e:
        logger.error(f"Error deleting all notifications: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500
