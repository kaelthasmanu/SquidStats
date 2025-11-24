import os
from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template, request

from config import logger
from database.database import get_session
from services.blacklist_users import find_blacklisted_sites
from services.fetch_data_logs import get_users_logs

logs_bp = Blueprint("logs", __name__)


@logs_bp.route("/logs")
def logs():
    try:
        db = get_session()
        users_data = get_users_logs(db)

        return render_template(
            "logsView.html",
            users_data=users_data,
            page_icon="user.ico",
            page_title="Actividad usuarios",
            icon="fas fa-user-friends",
            subtitle="Texto descriptivo aqui",
        )
    except Exception as e:
        logger.error(f"Error en ruta /logs: {e}")
        return render_template("error.html", message="Error retrieving logs"), 500


@logs_bp.route("/get-logs-by-date", methods=["POST"])
def get_logs_by_date():
    db = None
    try:
        page_int = request.json.get("page")
        page = request.args.get("page", page_int, type=int)
        per_page = request.args.get("per_page", 15, type=int)
        date_str = request.json.get("date")
        search = request.json.get("search")
        selected_date = datetime.strptime(date_str, "%Y-%m-%d")
        date_suffix = selected_date.strftime("%Y%m%d")

        db = get_session()
        users_data = get_users_logs(
            db, date_suffix, page=page, per_page=per_page, search=search
        )
        return jsonify(users_data)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400
    except Exception as e:
        logger.exception("Error en get-logs-by-date")

        try:
            show_details = bool(current_app.debug)
        except RuntimeError:
            show_details = False

        if show_details:
            return jsonify({"error": "Internal server error", "details": str(e)}), 500
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if db:
            db.close()


@logs_bp.route("/blacklist", methods=["GET"])
def blacklist_logs():
    db = None
    try:
        # Obtener parámetros de paginación
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        # Validar parámetros
        if page < 1 or per_page < 1 or per_page > 100:
            return render_template(
                "error.html", message="Invalid pagination parameters"
            ), 400

        db = get_session()

        # Obtener blacklist desde variables de entorno
        blacklist_env = os.getenv("BLACKLIST_DOMAINS")
        blacklist = (
            [domain.strip() for domain in blacklist_env.split(",") if domain.strip()]
            if blacklist_env
            else []
        )

        # Obtener resultados paginados
        result_data = find_blacklisted_sites(db, blacklist, page, per_page)

        if "error" in result_data:
            return render_template("error.html", message=result_data["error"]), 500

        return render_template(
            "blacklist.html",
            results=result_data["results"],
            pagination=result_data["pagination"],
            current_page=page,
            page_icon="shield-exclamation.ico",
            page_title="Registros Bloqueados",
            icon="fas fa-ban",
            subtitle="Texto descriptivo aqui",
        )

    except ValueError:
        return render_template("error.html", message="Invalid parameters"), 400

    except Exception as e:
        logger.error(f"Error in blacklist_logs: {str(e)}")
        return render_template("error.html", message="Internal server error"), 500

    finally:
        if db is not None:
            db.close()
