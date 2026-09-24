from datetime import date, datetime, timedelta
from io import BytesIO

from flask import Blueprint, jsonify, render_template, request, send_file
from flask_babel import gettext as _
from loguru import logger

from database.database import get_session
from services.analytics.blacklist_users import find_blacklisted_sites
from services.analytics.fetch_data_logs import get_users_logs
from services.analytics.ldap_groups_report import get_group_traffic_summary

try:
    from weasyprint import CSS, HTML
except Exception:
    CSS = None
    HTML = None

logs_bp = Blueprint("logs", __name__)


def categorize_response(code):
    if code >= 100 and code <= 199:
        return "informational"
    if code >= 200 and code <= 299:
        return "successful"
    if code >= 300 and code <= 399:
        return "redirection"
    if code >= 400 and code <= 499:
        return "clientError"
    if code >= 500 and code <= 599:
        return "serverError"
    return "unknown"


def group_logs_by_url(logs):
    groups = {}
    for log in logs:
        url = log["url"]
        if url not in groups:
            groups[url] = {
                "url": url,
                "responses": {},
                "total_requests": 0,
                "total_data": 0,
                "entry_count": 0,
            }
        group = groups[url]
        group["total_requests"] += log["request_count"]
        group["total_data"] += log["data_transmitted"]
        group["entry_count"] += 1
        group["responses"][log["response"]] = (
            group["responses"].get(log["response"], 0) + log["request_count"]
        )

    grouped_logs = []
    for group in groups.values():
        dominant_response = 0
        max_count = 0
        for response, count in group["responses"].items():
            if count > max_count:
                max_count = count
                dominant_response = int(response)

        full_url = group["url"]
        if not full_url.startswith("http"):
            if ":443" in full_url or ":8443" in full_url:
                full_url = "https://" + full_url
            else:
                full_url = "http://" + full_url

        grouped_logs.append(
            {
                "url": group["url"],
                "full_url": full_url,
                "response": dominant_response,
                "request_count": group["total_requests"],
                "data_transmitted": group["total_data"],
                "is_grouped": group["entry_count"] > 1,
            }
        )

    return grouped_logs


def build_response_summary(logs):
    summary = {
        "informational": 0,
        "successful": 0,
        "redirection": 0,
        "clientError": 0,
        "serverError": 0,
        "unknown": 0,
    }
    for log in logs:
        summary[categorize_response(log["response"])] += 1
    return summary


def enrich_users_with_logs(users):
    for user in users:
        logs = user.get("logs", [])
        user["grouped_logs"] = group_logs_by_url(logs)
        user["response_summary"] = build_response_summary(logs)


def _parse_group_report_dates():
    today = date.today()
    start_value = request.args.get("start_date") or today.isoformat()
    end_value = request.args.get("end_date") or start_value
    try:
        start_date = datetime.strptime(start_value, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_value, "%Y-%m-%d").date()
    except ValueError:
        return today, today
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    if (end_date - start_date).days > 366:
        start_date = end_date - timedelta(days=366)
    return start_date, end_date


@logs_bp.route("/logs")
def logs():
    try:
        active_tab = request.args.get("tab", "activity")
        if active_tab == "groups":
            start_date, end_date = _parse_group_report_dates()
            selected_group_id = request.args.get("group_id", type=int)
            selected_username = request.args.get("user", type=str)
            selected_user_page = request.args.get("user_page", 1, type=int)
            db = get_session()
            try:
                group_report = get_group_traffic_summary(
                    db,
                    start_date,
                    end_date,
                    selected_group_id,
                    selected_username,
                    selected_user_page,
                )
            finally:
                db.close()
            return render_template(
                "logsView.html",
                users=[],
                page_icon="favicon.ico",
                page_title=_("Actividad de usuarios y Grupos"),
                icon="fas fa-user-friends",
                subtitle=_("Analisis de la Actividad de los Usuarios y Grupos"),
                selected_date=date.today().isoformat(),
                search_query="",
                pagination={
                    "page": 1,
                    "per_page": 15,
                    "total_pages": 1,
                    "total": 0,
                    "page_range": [],
                },
                active_tab=active_tab,
                group_report=group_report,
            )

        date_str = request.args.get("date")
        page = request.args.get("page", 1, type=int)
        search = request.args.get("search", "", type=str)

        if page is None or page < 1:
            page = 1

        if date_str:
            try:
                selected_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                selected_date = datetime.now()
        else:
            selected_date = datetime.now()

        date_suffix = selected_date.strftime("%Y%m%d")
        db = get_session()
        users_page = get_users_logs(
            db,
            date_suffix,
            page=page,
            per_page=15,
            search=search or None,
        )
        users = users_page.get("users", [])
        enrich_users_with_logs(users)

        page_number = users_page.get("page", 1)
        total_pages = users_page.get("total_pages", 1)
        page_start = max(1, page_number - 2)
        page_end = min(total_pages, page_number + 2)
        if page_number <= 3:
            page_end = min(5, total_pages)
        if page_number > total_pages - 2:
            page_start = max(1, total_pages - 4)

        return render_template(
            "logsView.html",
            users=users,
            page_icon="favicon.ico",
            page_title=_("Actividad de usuarios y Grupos"),
            icon="fas fa-user-friends",
            subtitle=_("Analisis de la Actividad de los Usuarios y Grupos"),
            selected_date=selected_date.strftime("%Y-%m-%d"),
            search_query=search or "",
            pagination={
                "page": page_number,
                "per_page": users_page.get("per_page", 15),
                "total_pages": total_pages,
                "total": users_page.get("total", 0),
                "page_range": list(range(page_start, page_end + 1)),
            },
            active_tab=active_tab,
            group_report=None,
        )
    except Exception as e:
        logger.error(f"Error en ruta /logs: {e}")
        return render_template("error.html", message="Error retrieving logs"), 500


@logs_bp.route("/logs/groups/download/pdf")
def logs_groups_download_pdf():
    """Export the complete groups report, including selected-user details."""
    if HTML is None or CSS is None:
        logger.error("Groups PDF export requested but WeasyPrint is unavailable.")
        return render_template(
            "error.html",
            message=_("La exportación PDF no está disponible en este momento."),
        ), 503

    start_date, end_date = _parse_group_report_dates()
    selected_group_id = request.args.get("group_id", type=int)
    selected_username = request.args.get("user", type=str)
    db = get_session()
    try:
        group_report = get_group_traffic_summary(
            db,
            start_date,
            end_date,
            selected_group_id,
            selected_username,
            selected_user_page=1,
            selected_user_page_size=1_000_000,
        )
        html = render_template(
            "logs_groups_pdf.html",
            group_report=group_report,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        pdf_bytes = HTML(string=html, base_url=request.url_root).write_pdf(
            stylesheets=[CSS(string="body { font-family: Arial, sans-serif; }")]
        )
        filename = f"squidstats_groups_{start_date.isoformat()}_{end_date.isoformat()}.pdf"
        buffer = BytesIO(pdf_bytes)
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception:
        logger.exception("Error generating groups PDF report")
        return render_template(
            "error.html", message=_("Error interno generando el reporte PDF.")
        ), 500
    finally:
        db.close()


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
        return jsonify({"error": _("Invalid date format")}), 400
    except Exception:
        logger.exception("Error en get-logs-by-date")
        return jsonify({"error": _("Internal server error")}), 500
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

        # Obtener resultados paginados
        result_data = find_blacklisted_sites(db, page, per_page)

        if "error" in result_data:
            return render_template("error.html", message=result_data["error"]), 500

        return render_template(
            "blacklist.html",
            results=result_data["results"],
            pagination=result_data["pagination"],
            domain_capped=result_data.get("domain_capped", False),
            domain_cap=result_data.get("domain_cap", 25),
            current_page=page,
            page_icon="favicon.ico",
            page_title=_("Registros Bloqueados"),
            icon="fas fa-ban",
            subtitle=_("Peticiones que deberian ser bloqueadas o fueron bloqueadas"),
        )

    except ValueError:
        return render_template("error.html", message="Invalid parameters"), 400

    except Exception as e:
        logger.error(f"Error in blacklist_logs: {str(e)}")
        return render_template("error.html", message="Internal server error"), 500

    finally:
        if db is not None:
            db.close()
