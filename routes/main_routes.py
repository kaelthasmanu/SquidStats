import os
import time
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request

from config import Config, logger
from parsers.connections import group_by_user, parse_raw_data
from parsers.squid_info import fetch_squid_info_stats
from services.fetch_data import fetch_squid_data
from utils.updateSquid import update_squid
from utils.updateSquidStats import updateSquidStats

main_bp = Blueprint("main", __name__)


def filter_valid_users(grouped_connections):
    """
    Filtra usuarios válidos eliminando usuarios anónimos y vacíos
    Esta función centraliza la lógica de filtrado que antes estaba en el template
    """
    valid_users = {}
    for user, user_data in grouped_connections.items():
        if user and user != "-" and user != "Anónimo":
            valid_users[user] = user_data
    return valid_users


@main_bp.app_context_processor
def inject_app_version():
    """Inyecta la versión de la aplicación en todos los templates"""
    version = getattr(Config, "VERSION", None) or os.getenv("VERSION", "-")
    return {"app_version": version}


def _build_error_page(message: str, status: int = 500, details: str | None = None):
    """
    Construye una página de error estandarizada
    """
    if details:
        logger.debug("Error details (server-only): %s", details)

    try:
        show_details = bool(current_app.debug)
    except RuntimeError:
        # No app context: be conservative and do not show details
        show_details = False

    return (
        render_template(
            "error.html",
            message=message,
            details=details if show_details else None,
        ),
        status,
    )


def _get_dashboard_context() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """
    Obtiene y procesa el contexto para el dashboard
    Retorna: (context_dict, error_response) - solo uno será no None
    """
    t0 = time.time()
    try:
        raw_data = fetch_squid_data()
        if not raw_data:
            logger.error("fetch_squid_data() returned empty response")
            return None, _build_error_page("Sin datos desde Squid", 502)
        if isinstance(raw_data, str) and raw_data.strip().lower().startswith("error"):
            logger.error(f"Failed to fetch Squid data: {raw_data}")
            return None, _build_error_page("Error conectando con Squid", 502, raw_data)

        try:
            connections = parse_raw_data(raw_data)
        except Exception as parse_err:
            logger.exception("Error parseando conexiones de Squid")
            return None, _build_error_page(
                "Error procesando datos de Squid", 500, str(parse_err)
            )

        if not connections:
            logger.warning("No se detectaron conexiones activas en la salida de Squid")
            connections = []

        try:
            grouped_connections = group_by_user(connections)
        except Exception:
            logger.exception("Error agrupando conexiones por usuario")
            grouped_connections = {}

        # FILTRADO CENTRALIZADO: Generar usuarios válidos aquí en lugar del template
        valid_users = filter_valid_users(grouped_connections)

        try:
            squid_info_stats = fetch_squid_info_stats()
        except Exception:
            logger.exception("Error obteniendo estadísticas detalladas de Squid")
            squid_info_stats = {}

        squid_version = (
            connections[0].get("squid_version", "No disponible")
            if connections
            else "No disponible"
        )

        context: dict[str, Any] = {
            "grouped_connections": grouped_connections,
            "valid_users": valid_users,
            "squid_version": squid_version,
            "squid_info_stats": squid_info_stats,
            "page_icon": "favicon.ico",
            "page_title": "Inicio Dashboard",
            "build_time_ms": int((time.time() - t0) * 1000),
            "connection_count": len(connections),
        }
        return context, None
    except Exception:  # Fallback catch-all
        logger.exception("Fallo inesperado construyendo el contexto del dashboard")
        return None, _build_error_page("Fallo interno inesperado", 500)


@main_bp.route("/")
def index():
    """
    Ruta unificada para el dashboard

    CAMBIO PRINCIPAL:
    - Ahora maneja tanto la carga completa de la página como las actualizaciones parciales
    - Elimina la necesidad de la ruta separada /actualizar-conexiones

    Detección de tipo de petición:
    - Petición normal: Devuelve index.html completo
    - Petición parcial (param partial=true): Devuelve solo el contenido de conexiones
    """

    # CAMBIO: Detectar si es una petición para contenido parcial
    is_partial_request = request.args.get("partial") == "true"

    context, error_response = _get_dashboard_context()
    if error_response:
        return error_response

    # CAMBIO: Si es petición parcial, devolver solo el template de conexiones
    if is_partial_request:
        return render_template(
            "partials/conexiones.html",
            grouped_connections=context["grouped_connections"],
            valid_users=context["valid_users"],
            squid_version=context["squid_version"],
            squid_info_stats=context["squid_info_stats"],
            build_time_ms=context["build_time_ms"],
            connection_count=context["connection_count"],
        )

    # Petición normal: devolver la página completa
    return render_template("index.html", **context)


@main_bp.route("/install", methods=["POST"])
def install_package():
    """Ruta para instalar/actualizar paquetes de Squid"""
    ok = False
    try:
        ok = update_squid()
        if ok:
            logger.info("Actualización de SquidStats (install) completada exitosamente")
        else:
            logger.warning("update_squid() retornó False en /install")
    except Exception:
        logger.exception("Error ejecutando actualización en /install")
    return redirect(f"/?install_status={'ok' if ok else 'fail'}")


@main_bp.route("/update", methods=["POST"])
def update_web():
    """Ruta para actualizar la aplicación web"""
    ok = False
    try:
        ok = updateSquidStats()
        if ok:
            logger.info("Actualización web de SquidStats completada")
        else:
            logger.warning("updateSquidStats() retornó False en /update")
    except Exception:
        logger.exception("Error ejecutando actualización en /update")
    return redirect(f"/?update_status={'ok' if ok else 'fail'}")
