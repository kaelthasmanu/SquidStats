import os
import time
from threading import Lock
from typing import Any

from flask import Blueprint, redirect, render_template

from config import logger
from parsers.connections import group_by_user, parse_raw_data
from parsers.log import find_last_parent_proxy
from parsers.squid_info import fetch_squid_info_stats
from services.fetch_data import fetch_squid_data
from utils.updateSquid import update_squid
from utils.updateSquidStats import updateSquidStats

main_bp = Blueprint("main", __name__)

# Global variables
parent_proxy_lock = Lock()
g_parent_proxy_ip = None


def initialize_proxy_detection():
    global g_parent_proxy_ip

    g_parent_proxy_ip = find_last_parent_proxy(
        os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    )
    if g_parent_proxy_ip:
        logger.info(f"Proxy parent detect with IP: {g_parent_proxy_ip}.")
    else:
        logger.info(
            "No proxy parent detected in recent logs. Assuming direct connection."
        )


def _build_error_page(message: str, status: int = 500, details: str | None = None):
    if details:
        logger.debug(f"Error details: {details}")
    return (
        render_template(
            "error.html",
            message=message,
            details=details if os.getenv("FLASK_DEBUG") else None,
        ),
        status,
    )


def _get_dashboard_context() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
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

        with parent_proxy_lock:
            parent_ip = g_parent_proxy_ip

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
            "parent_proxy_ip": parent_ip,
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
    context, error_response = _get_dashboard_context()
    if error_response:
        return error_response
    return render_template("index.html", **context)


@main_bp.route("/actualizar-conexiones")
def actualizar_conexiones():
    context, error_response = _get_dashboard_context()
    if error_response:
        return ("Error interno al refrescar conexiones", error_response[1])
    return render_template(
        "partials/conexiones.html",
        grouped_connections=context["grouped_connections"],
        parent_proxy_ip=context["parent_proxy_ip"],
        squid_version=context["squid_version"],
        squid_info_stats=context["squid_info_stats"],
        build_time_ms=context["build_time_ms"],
        connection_count=context["connection_count"],
    )


@main_bp.route("/install", methods=["POST"])
def install_package():
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
