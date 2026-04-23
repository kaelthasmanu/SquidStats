from datetime import date, datetime
from io import BytesIO

from flask import Blueprint, render_template, request, send_file
from flask_babel import gettext as _
from loguru import logger

from database.database import get_dynamic_models, get_session
from services.analytics.auditoria_service import run_audit_operation
from services.analytics.fetch_data_logs import get_metrics_for_date
from services.analytics.get_reports import get_important_metrics
from utils.colors import color_map

# WeasyPrint is optional; if missing, PDF endpoint returns friendly error.
try:
    from weasyprint import CSS, HTML
    logger.info("WeasyPrint loaded successfully")
except Exception as e:
    CSS = None
    HTML = None
    logger.exception(f"WeasyPrint import failed: {e}")

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
            page_icon="favicon.ico",
            page_title=_("Reportes y gráficas"),
            icon="fas fa-chart-simple",
            subtitle=_("Top de la Actividad de los Usuarios y comportamiento"),
        )
    except Exception as e:
        logger.error(f"Error en ruta /reports: {str(e)}", exc_info=True)
        return render_template(
            "error.html", message="Error interno generando reportes"
        ), 500
    finally:
        if db:
            db.close()


@reports_bp.route("/reports/download/pdf")
def reports_download_pdf():
    """Pdf export endpoint for the same data shown in /reports."""
    if HTML is None or CSS is None:
        logger.error("PDF export requested but weasyprint is unavailable.")
        return render_template(
            "error.html",
            message=(
                "PDF no disponible: weasyprint o sus librerías nativas no están instaladas. "
            ),
        ), 503

    date_str = request.args.get("date")
    if date_str:
        try:
            selected = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return render_template(
                "error.html", message="Formato de fecha inválido"
            ), 400
    else:
        selected = date.today()

    date_suffix = selected.strftime("%Y%m%d")
    logger.info(f"Generating PDF report for date: {date_suffix}")

    db = None
    try:
        db = get_session()
        UserModel, LogModel = get_dynamic_models(date_suffix)

        if not UserModel or not LogModel:
            return render_template(
                "error.html", message="Error cargando datos para la fecha solicitada"
            ), 500

        metrics = get_important_metrics(db, UserModel, LogModel)
        if not metrics:
            return render_template(
                "error.html", message="No hay datos para la fecha solicitada"
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

        html = render_template(
            "reports_pdf.html",
            metrics=metrics,
            selected_date=selected,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        pdf_bytes = HTML(string=html, base_url=request.url_root).write_pdf(
            stylesheets=[CSS(string="body { font-family: Arial, sans-serif; }")]
        )

        buffer = BytesIO(pdf_bytes)
        buffer.seek(0)
        filename = f"squidstats_report_{selected.isoformat()}.pdf"
        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception:
        logger.exception("Error generating PDF report")
        return render_template(
            "error.html", message="Error interno generando reporte PDF"
        ), 500
    finally:
        if db:
            db.close()


@reports_bp.route("/reports/date/<date_str>")
def reports_for_date(date_str: str):
    """Render reports for a specific date provided as YYYY-MM-DD."""
    db = None
    try:
        try:
            selected = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return render_template("error.html", message="Invalid date format"), 400

        date_suffix = selected.strftime("%Y%m%d")
        logger.info(f"Generating reports for date: {date_suffix}")

        db = get_session()
        UserModel, LogModel = get_dynamic_models(date_suffix)

        if not UserModel or not LogModel:
            return render_template(
                "error.html", message="Error loading data for requested date"
            ), 500

        metrics = get_important_metrics(db, UserModel, LogModel)

        if not metrics:
            return render_template(
                "error.html", message="No data available for requested date"
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
            page_icon="favicon.ico",
            page_title=_("Reportes y gráficas") + f" - {selected.isoformat()}",
            icon="fas fa-chart-simple",
            subtitle=_("Top de la Actividad de los Usuarios y comportamiento"),
        )
    except Exception:
        logger.exception("Error generating reports for specific date")
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
        page_icon="favicon.ico",
        page_title=_("Centro de Auditoría"),
        icon="fas fa-magnifying-glass",
        subtitle=_("Herramienta para el análisis de actividad y seguridad."),
    )


@reports_bp.route("/auditoria/download/pdf", methods=["GET"])
def auditoria_download_pdf():
    if HTML is None or CSS is None:
        logger.error("PDF export requested but WeasyPrint is unavailable.")
        return render_template(
            "error.html",
            message=(
                "PDF no disponible: weasyprint o sus librerías nativas no están instaladas. "
            ),
        ), 503

    audit_type = request.args.get("audit_type", "top_users_data")
    # Keep incoming parameters as strings; list endpoints can be comma-separated.
    params = {
        "start_date": request.args.get("start_date", ""),
        "end_date": request.args.get("end_date", ""),
        "username": request.args.get("username", ""),
        "keyword": request.args.get("keyword", ""),
        "ip_address": request.args.get("ip_address", ""),
        "response_code": request.args.get("response_code", ""),
        "social_media_sites": request.args.get("social_media_sites", ""),
    }
    params["audit_type"] = audit_type

    db = None
    try:
        db = get_session()
        data = run_audit_operation(db, audit_type, params)

        if not data or data.get("error"):
            message = data.get("error", "No data for this audit selection")
            return render_template("error.html", message=message), 404

        rendered = render_template(
            "auditoria_pdf.html",
            audit_type=audit_type,
            params=params,
            data=data,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        pdf_bytes = HTML(string=rendered, base_url=request.url_root).write_pdf(
            stylesheets=[CSS(string="body { font-family: Arial, sans-serif; }")]
        )
        buffer = BytesIO(pdf_bytes)
        buffer.seek(0)
        filename = (
            f"auditoria_{audit_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    except Exception:
        logger.exception("Error generating auditoría PDF report")
        return render_template(
            "error.html", message="Error interno generando reporte PDF"
        ), 500
    finally:
        if db:
            db.close()
