from threading import Lock

from flask import Blueprint, render_template

from parsers.connections import group_by_user, parse_raw_data
from parsers.log import find_last_parent_proxy
from parsers.squid_info import fetch_squid_info_stats
from services.fetch_data import fetch_squid_data
from utils.updateSquidStats import updateSquidStats

main_bp = Blueprint("main", __name__)

# Global variables
parent_proxy_lock = Lock()
g_parent_proxy_ip = None


def initialize_proxy_detection():
    global g_parent_proxy_ip
    import os

    from config import logger

    g_parent_proxy_ip = find_last_parent_proxy(
        os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    )
    if g_parent_proxy_ip:
        logger.info(f"Proxy parent detect with IP: {g_parent_proxy_ip}.")
    else:
        logger.info(
            "No proxy parent detected in recent logs. Assuming direct connection."
        )


@main_bp.route("/")
def index():
    try:
        from config import logger

        raw_data = fetch_squid_data()
        if "Error" in raw_data:
            logger.error(f"Failed to fetch Squid data: {raw_data}")
            return render_template(
                "error.html", message="Error connecting to Squid"
            ), 500

        connections = parse_raw_data(raw_data)
        grouped_connections = group_by_user(connections)

        with parent_proxy_lock:
            parent_ip = g_parent_proxy_ip

        # Obtener estadísticas detalladas de Squid
        squid_info_stats = fetch_squid_info_stats()

        return render_template(
            "index.html",
            grouped_connections=grouped_connections,
            parent_proxy_ip=parent_ip,
            squid_version=connections[0].get("squid_version", "No disponible"),
            squid_info_stats=squid_info_stats,
            page_icon="favicon.ico",
            page_title="Inicio Dashboard",
        )
    except Exception as e:
        from config import logger

        logger.error(f"Unexpected error in index route: {str(e)}")
        return render_template(
            "error.html", message="An unexpected error occurred"
        ), 500


@main_bp.route("/actualizar-conexiones")
def actualizar_conexiones():
    try:
        from config import logger

        raw_data = fetch_squid_data()
        if "Error" in raw_data:
            logger.error(f"Failed to fetch Squid data: {raw_data}")
            return "Error", 500

        connections = parse_raw_data(raw_data)
        grouped_connections = group_by_user(connections)

        with parent_proxy_lock:
            parent_ip = g_parent_proxy_ip

        squid_info_stats = fetch_squid_info_stats()

        return render_template(
            "partials/conexiones.html",
            grouped_connections=grouped_connections,
            parent_proxy_ip=parent_ip,
            # squid_ip=squid_ip,
            # squid_version=,
            squid_info_stats=squid_info_stats,
        )

    except Exception as e:
        from config import logger

        logger.error(f"Unexpected error in /actualizar-conexiones route: {str(e)}")
        return "Error interno", 500


@main_bp.route("/install", methods=["POST"])
def install_package():
    from flask import redirect

    updateSquidStats()
    return redirect("/")


@main_bp.route("/update", methods=["POST"])
def update_web():
    from flask import redirect

    updateSquidStats()
    return redirect("/")
