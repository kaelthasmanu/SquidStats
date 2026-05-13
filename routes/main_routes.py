import os
import time
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request
from flask_babel import gettext as _
from loguru import logger

from config import Config
from parsers.connections import group_by_user, parse_raw_data
from parsers.squid_info import fetch_squid_info_stats
from routes.admin.helpers import sanitize_error_page_message
from services.notifications.notifications import get_all_notifications
from services.squid.fetch_data import fetch_all_squid_data
from services.system.system_info import get_system_type
from utils.updateSquid import update_squid
from utils.updateSquidStats import updateSquidStats

main_bp = Blueprint("main", __name__)


def filter_valid_users(grouped_connections):
    """
    Filter valid users by removing anonymous and empty users
    This function centralizes the filtering logic that was previously in the template
    """
    valid_users = {}
    for user, user_data in grouped_connections.items():
        if user and user != "-" and user != "Anónimo":
            valid_users[user] = user_data
    return valid_users


@main_bp.app_context_processor
def inject_app_version():
    """Inject the application version into all templates"""
    version = getattr(Config, "VERSION", None) or os.getenv("VERSION", "-")
    return {"app_version": version}


def _build_error_page(message: str, status: int = 500):
    """
    Build a standardized error page
    """
    safe_message = sanitize_error_page_message(message)
    return (
        render_template(
            "error.html",
            message=safe_message,
        ),
        status,
    )


def _get_dashboard_context() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """
    Get and process the context for the dashboard
    Returns: (context_dict, error_response) - only one will be not None
    """
    t0 = time.time()
    try:
        proxy_results = fetch_all_squid_data()

        # Collect per-proxy status for the UI
        proxy_statuses: list[dict] = []
        all_connections: list = []

        for proxy in proxy_results:
            raw_data = proxy["data"]
            label = proxy["label"]
            ok = proxy["ok"]

            proxy_statuses.append({"label": label, "ok": ok})

            if not ok:
                logger.warning(f"Could not fetch data from proxy {label}: {raw_data}")
                continue

            try:
                conns = parse_raw_data(raw_data, source_host=label)
                all_connections.extend(conns)
            except Exception:
                logger.exception(f"Error parsing connections from proxy {label}")

        if not all_connections and all(not p["ok"] for p in proxy_results):
            logger.error("All Squid proxies returned errors")
            return None, _build_error_page("No data from any Squid proxy", 502)

        connections = all_connections

        try:
            grouped_connections = group_by_user(connections)
        except Exception:
            logger.exception("Error grouping connections by user")
            grouped_connections = {}

        # CENTRALIZED FILTERING: Generate valid users here instead of in the template
        valid_users = filter_valid_users(grouped_connections)

        try:
            squid_info_stats = fetch_squid_info_stats()
        except Exception:
            logger.exception("Error getting detailed Squid statistics")
            squid_info_stats = {}

        squid_version = (
            connections[0].get("squid_version", "No disponible")
            if connections
            else "No disponible"
        )

        multi_proxy = len(proxy_results) > 1

        context: dict[str, Any] = {
            "grouped_connections": grouped_connections,
            "valid_users": valid_users,
            "squid_version": squid_version,
            "squid_info_stats": squid_info_stats,
            "page_icon": "favicon.ico",
            "page_title": _("Inicio Dashboard"),
            "build_time_ms": int((time.time() - t0) * 1000),
            "connection_count": len(connections),
            "system_type": get_system_type(),
            "proxy_statuses": proxy_statuses,
            "multi_proxy": multi_proxy,
        }
        return context, None
    except Exception:  # Fallback catch-all
        logger.exception("Unexpected failure building dashboard context")
        return None, _build_error_page("Unexpected internal failure", 500)


@main_bp.route("/")
def index():
    # CHANGE: Detect if this is a request for partial content
    is_partial_request = request.args.get("partial") == "true"

    context, error_response = _get_dashboard_context()
    if error_response:
        return error_response

    # CHANGE: If it's a partial request, return only the connections template
    if is_partial_request:
        return render_template(
            "partials/conexiones.html",
            grouped_connections=context["grouped_connections"],
            valid_users=context["valid_users"],
            squid_version=context["squid_version"],
            squid_info_stats=context["squid_info_stats"],
            build_time_ms=context["build_time_ms"],
            connection_count=context["connection_count"],
            system_type=context["system_type"],
            proxy_statuses=context["proxy_statuses"],
            multi_proxy=context["multi_proxy"],
        )

    # Normal request: return the complete page
    return render_template("index.html", **context)


@main_bp.route("/install", methods=["POST"])
def install_package():
    """Route to install/update Squid packages"""
    ok = False
    try:
        ok = update_squid()
        if ok:
            logger.info("SquidStats update (install) completed successfully")
            flash(_("Squid actualizado correctamente."), "success")
        else:
            logger.warning("update_squid() returned False in /install")
            flash(
                _("Error al actualizar Squid. Revise los logs del servidor."), "error"
            )
    except Exception:
        logger.exception("Error executing update in /install")
        flash(
            _("Error inesperado al actualizar Squid. Revise los logs del servidor."),
            "error",
        )
    return redirect("/")


@main_bp.route("/update", methods=["POST"])
def update_web():
    """Route to update the web application"""
    ok = False
    try:
        ok = updateSquidStats()
        if ok:
            logger.info("SquidStats web update completed")
            flash(
                _(
                    "SquidStats actualizado correctamente. El servicio se ha reiniciado."
                ),
                "success",
            )
        else:
            logger.warning("updateSquidStats() returned False in /update")
            flash(
                _("Error al actualizar SquidStats. Revise los logs del servidor."),
                "error",
            )
    except Exception:
        logger.exception("Error executing update in /update")
        flash(
            _(
                "Error inesperado al actualizar SquidStats. Revise los logs del servidor."
            ),
            "error",
        )
    return redirect("/")


@main_bp.route("/all-notifications")
def all_notifications():
    """Page to view all notifications with pagination"""
    try:
        # Get pagination parameters
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        # Validate parameters
        if page < 1:
            page = 1
        if per_page not in [10, 20, 50, 100]:
            per_page = 20

        # Get notifications with pagination
        notifications_data = get_all_notifications(
            limit=None, page=page, per_page=per_page
        )

        return render_template(
            "all_notifications.html",
            page_title=_("Todas las Notificaciones"),
            page_icon="favicon.ico",
            subtitle=_("Historial completo de notificaciones del sistema"),
            icon="fas fa-bell",
            notifications=notifications_data["notifications"],
            unread_count=notifications_data["unread_count"],
            pagination=notifications_data.get(
                "pagination",
                {
                    "current_page": page,
                    "per_page": per_page,
                    "total_pages": 1,
                    "total_notifications": len(notifications_data["notifications"]),
                    "has_prev": False,
                    "has_next": False,
                },
            ),
        )
    except Exception as e:
        logger.error(f"Error loading notifications page: {e}")
        return render_template(
            "all_notifications.html",
            page_title=_("Todas las Notificaciones"),
            page_icon="favicon.ico",
            subtitle=_("Error al cargar las notificaciones"),
            icon="fa-bell",
            notifications=[],
            unread_count=0,
            pagination=None,
        )
