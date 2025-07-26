from datetime import date, datetime

from flask import Blueprint, render_template, request

from config import logger
from database.database import get_dynamic_models, get_session
from services.fetch_data_logs import get_metrics_for_date
from services.get_reports import get_important_metrics
from utils.colors import color_map

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/reports")
def reports():
    db = None
    try:
        db = get_session()
        current_date = datetime.now().strftime("%Y%m%d")
        logger.info(f"Generating reports for date: {current_date}")
        UserModel, LogModel = get_dynamic_models(current_date)

        if not UserModel or not LogModel:
            return render_template(
                "error.html", message="Error loading data for reports"
            ), 500

        metrics = get_important_metrics(db, UserModel, LogModel)

        if not metrics:
            return render_template(
                "error.html", message="No data available for reports"
            ), 404

        http_codes = metrics.get("http_response_distribution", [])
        http_codes = sorted(http_codes, key=lambda x: x["count"], reverse=True)
        main_codes = http_codes[:8]
        other_codes = http_codes[8:]

        if other_codes:
            other_count = sum(item["count"] for item in other_codes)
            main_codes.append({"response_code": "Otros", "count": other_count})

        metrics["http_response_distribution_chart"] = {
            "labels": [str(item["response_code"]) for item in main_codes],
            "data": [item["count"] for item in main_codes],
            "colors": [
                color_map.get(str(item["response_code"]), color_map["Otros"])
                for item in main_codes
            ],
        }

        return render_template(
            "reports.html",
            metrics=metrics,
            page_icon="bar.ico",
            page_title="Reportes y gráficas",
        )
    except Exception as e:
        logger.error(f"Error en ruta /reports: {str(e)}", exc_info=True)
        return render_template(
            "error.html", message="Error interno generando reportes"
        ), 500
    finally:
        if db:
            db.close()


@reports_bp.route("/dashboard")
def dashboard():
    date_str = request.args.get("date")
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()

    metrics = get_metrics_for_date(selected_date)

    return render_template(
        "components/graph_reports.html", metrics=metrics, selected_date=selected_date
    )


@reports_bp.route("/auditoria", methods=["GET"])
def auditoria_logs():
    return render_template(
        "auditor.html",
        page_icon="magnifying-glass.ico",
        page_title="Centro de Auditoría",
    )
