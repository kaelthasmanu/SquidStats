from flask import Blueprint, jsonify, request

from config import logger
from database.database import get_session
from services.auditoria_service import (
    find_by_ip,
    find_by_keyword,
    find_by_response_code,
    find_denied_access,
    find_social_media_activity,
    get_all_usernames,
    get_daily_activity,
    get_top_users_by_data,
    get_user_activity_summary,
)
from services.metrics_service import MetricsService

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
        return jsonify({"error": str(e)}), 500
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
        else:
            return jsonify({"error": "Invalid audit type."}), 400

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error en la API de auditoría: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        db.close()
