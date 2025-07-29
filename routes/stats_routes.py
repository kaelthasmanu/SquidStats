import socket
import sys
from datetime import datetime
from threading import Lock

from flask import Blueprint, render_template

# from services.icap_service import fetch_cicap_stats
from config import logger
from parsers.cache import fetch_squid_cache_stats
from services.metrics_service import MetricsService
from services.system_info import (
    get_cpu_info,
    get_network_info,
    get_network_stats,
    get_os_info,
    get_ram_info,
    get_squid_version,
    get_swap_info,
    get_timezone,
    get_uptime,
)
from utils.size import size_to_bytes

stats_bp = Blueprint("stats", __name__)

# Global variables for real-time data
realtime_data_lock = Lock()
realtime_cache_stats = {}
realtime_system_info = {}


@stats_bp.route("/stats")
def cache_stats_realtime():
    try:
        with realtime_data_lock:
            stats_data = realtime_cache_stats if realtime_cache_stats else {}
            system_info_data = realtime_system_info if realtime_system_info else {}

        if not stats_data:
            data = fetch_squid_cache_stats()
            stats_data = vars(data) if hasattr(data, "__dict__") else data

        if not system_info_data:
            system_info_data = {
                "hostname": socket.gethostname(),
                "ips": get_network_info(),
                "os": get_os_info(),
                "uptime": get_uptime(),
                "ram": get_ram_info(),
                "swap": get_swap_info(),
                "cpu": get_cpu_info(),
                "python_version": sys.version.split()[0],
                "squid_version": get_squid_version(),
                "timezone": get_timezone(),
                "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        network_stats = get_network_stats()
        logger.info("Successfully fetched cache statistics and system info")
        return render_template(
            "cacheView.html",
            cache_stats=stats_data,
            system_info=system_info_data,
            network_stats=network_stats,
            page_icon="statistics.ico",
            page_title="Estadísticas del Sistema",
        )
    except Exception as e:
        logger.error(f"Error in /stats: {str(e)}")
        return render_template(
            "error.html", message="Error retrieving cache statistics or system info"
        ), 500


""" @stats_bp.route("/print_icap_service")
def print_icap_service():
    try:
        print(fetch_cicap_stats())
        print("--- END OF ICAP SERVICE MODULE ---")
        return "ICAP service module content printed to console.", 200
    except Exception as e:
        print(f"Error printing icap_service.py: {e}")
        return f"Error printing icap_service.py: {e}", 500
 """


def realtime_data_thread(socketio):
    global realtime_cache_stats, realtime_system_info
    import time

    data_collection_counter = 0

    while True:
        try:
            cache_data = fetch_squid_cache_stats()
            cache_stats = (
                vars(cache_data) if hasattr(cache_data, "__dict__") else cache_data
            )

            # Validar network_info
            network_info = get_network_info()
            if not isinstance(network_info, list | dict) or network_info in (
                "No disponible",
                None,
                "",
            ):
                logger.error(f"get_network_info() returned an error: {network_info}")
                network_info = []

            # Validar ram_info
            ram_info = get_ram_info()
            if not isinstance(ram_info, dict) or ram_info in (
                "No disponible",
                None,
                "",
            ):
                logger.error(f"get_ram_info() returned an error: {ram_info}")
                ram_info = {"used": "0 B"}

            # Validar swap_info
            swap_info = get_swap_info()
            if not isinstance(swap_info, dict) or swap_info in (
                "No disponible",
                None,
                "",
            ):
                logger.error(f"get_swap_info() returned an error: {swap_info}")
                swap_info = {"used": "0 B"}

            # Validar cpu_info
            cpu_info = get_cpu_info()
            if not isinstance(cpu_info, dict) or cpu_info in (
                "No disponible",
                None,
                "",
            ):
                logger.error(f"get_cpu_info() devolvió un error: {cpu_info}")
                cpu_info = {"usage": "0%"}

            # Validar network_stats
            network_stats = get_network_stats()
            if not isinstance(network_stats, dict) or network_stats in (
                "No disponible",
                None,
                "",
            ):
                logger.error(f"get_network_stats() returned an error: {network_stats}")
                network_stats = {}

            system_info = {
                "hostname": socket.gethostname(),
                "ips": network_info,
                "os": get_os_info(),
                "uptime": get_uptime(),
                "ram": ram_info,
                "swap": swap_info,
                "cpu": cpu_info,
                "python_version": sys.version.split()[0],
                "squid_version": get_squid_version(),
                "timezone": get_timezone(),
                "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp_utc": datetime.now().isoformat(),
            }

            # Guardar métricas en la base de datos solo cada 60 segundos (cada 4 iteraciones)
            data_collection_counter += 1
            if data_collection_counter % 4 == 0:
                ram_bytes = size_to_bytes(ram_info.get("used", "0 B"))
                swap_bytes = size_to_bytes(swap_info.get("used", "0 B"))

                # Guardar en base de datos
                MetricsService.save_system_metrics(
                    cpu_usage=cpu_info.get("usage", "0%"),
                    ram_usage_bytes=ram_bytes,
                    swap_usage_bytes=swap_bytes,
                    net_sent_bytes_sec=network_stats.get("bytes_sent_per_sec", 0),
                    net_recv_bytes_sec=network_stats.get("bytes_recv_per_sec", 0),
                )

            with realtime_data_lock:
                realtime_cache_stats = cache_stats
                realtime_system_info = system_info

            socketio.emit(
                "system_update",
                {
                    "cache_stats": cache_stats,
                    "system_info": system_info,
                    "network_stats": network_stats,
                },
            )
        except Exception as e:
            logger.error(f"Error in real-time data thread: {str(e)}")
        time.sleep(15)  # Actualizar cada 15 segundos
