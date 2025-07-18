import logging
import os
import socket
import sys
from datetime import date, datetime
from threading import Lock  # Importamos Lock para sincronización de hilos

from dotenv import load_dotenv
from flask import Blueprint, Flask, jsonify, redirect, render_template, request
from flask_apscheduler import APScheduler
from flask_socketio import SocketIO

from database.database import get_dynamic_models, get_session
from parsers.cache import fetch_squid_cache_stats
from parsers.connections import group_by_user, parse_raw_data
from parsers.log import find_last_parent_proxy, process_logs
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
from services.blacklist_users import find_blacklisted_sites
from services.fetch_data import fetch_squid_data
from services.fetch_data_logs import get_metrics_for_date, get_users_logs
from services.get_reports import get_important_metrics
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
from utils.colors import color_map
from utils.filters import register_filters
from utils.updateSquid import update_squid
from utils.updateSquidStats import updateSquidStats


class Config:
    SCHEDULER_API_ENABLED = True


load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

parent_proxy_lock = Lock()

g_parent_proxy_ip = find_last_parent_proxy(
    os.getenv("SQUID_LOG", "/var/log/squid/access.log")
)
if g_parent_proxy_ip:
    logger.info(
        f"Proxy padre detectado con IP: {g_parent_proxy_ip}. Esta configuración se mantendrá fija."
    )
else:
    logger.info(
        "No se detectó un proxy padre en los logs recientes. Asumiendo conexión directa."
    )

# Initialize Flask application
app = Flask(__name__, static_folder="./static")
app.config.from_object(Config())
scheduler = APScheduler()
app.secret_key = os.urandom(24).hex()
scheduler.init_app(app)
scheduler.start()

register_filters(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@app.route("/")
def index():
    try:
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

        squid_version = get_squid_version()
        network_info = get_network_info()
        squid_ip = "No disponible"
        if isinstance(network_info, list) and network_info:
            squid_ip = network_info[0].get("ip", "No disponible")

        return render_template(
            "index.html",
            grouped_connections=grouped_connections,
            parent_proxy_ip=parent_ip,
            squid_ip=squid_ip,
            squid_version=squid_version,
            page_icon="favicon.ico",
            page_title="Inicio Dashboard",
        )
    except Exception as e:
        logger.error(f"Unexpected error in index route: {str(e)}")
        return render_template(
            "error.html", message="An unexpected error occurred"
        ), 500


@app.route("/actualizar-conexiones")
def actualizar_conexiones():
    try:
        raw_data = fetch_squid_data()
        if "Error" in raw_data:
            logger.error(f"Failed to fetch Squid data: {raw_data}")
            return "Error", 500

        connections = parse_raw_data(raw_data)
        grouped_connections = group_by_user(connections)
        return render_template(
            "partials/conexiones.html", grouped_connections=grouped_connections
        )

    except Exception as e:
        logger.error(f"Unexpected error in /actualizar-conexiones route: {str(e)}")
        return "Error interno", 500


@app.route("/logs")
def logs():
    try:
        db = get_session()
        users_data = get_users_logs(db)

        return render_template(
            "logsView.html",
            users_data=users_data,
            page_icon="user.ico",
            page_title="Actividad usuarios",
        )
    except Exception as e:
        print(f"Error en ruta /logs: {e}")
        return render_template("error.html", message="Error retrieving logs"), 500


@scheduler.task("interval", id="do_job_1", seconds=30, misfire_grace_time=900)
def init_scheduler():
    """Initialize and start the background scheduler for log processing"""
    log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    logger.info(f"Configurando scheduler para el archivo de log: {log_file}")

    if not os.path.exists(log_file):
        logger.error(f"Archivo de log no encontrado: {log_file}")
        return
    else:
        process_logs(log_file)


@scheduler.task("interval", id="cleanup_metrics", hours=1, misfire_grace_time=3600)
def cleanup_old_metrics():
    try:
        success = MetricsService.cleanup_old_metrics()
        if success:
            logger.info("Limpieza de métricas antiguas completada exitosamente")
        else:
            logger.warning("Error durante la limpieza de métricas antiguas")
    except Exception as e:
        logger.error(f"Error en tarea de limpieza de métricas: {e}")


@app.route("/get-logs-by-date", methods=["POST"])
def get_logs_by_date():
    db = None
    try:
        page_int = request.json.get("page")
        page = request.args.get("page", page_int, type=int)
        per_page = request.args.get("per_page", 15, type=int)
        date_str = request.json.get("date")
        selected_date = datetime.strptime(date_str, "%Y-%m-%d")
        date_suffix = selected_date.strftime("%Y%m%d")

        db = get_session()
        users_data = get_users_logs(db, date_suffix, page=page, per_page=per_page)
        return jsonify(users_data)
    except ValueError:
        return jsonify({"error": "Formato de fecha inválido"}), 400
    except Exception as e:
        logger.error(f"Error en get-logs-by-date: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/reports")
def reports():
    db = None
    try:
        db = get_session()
        current_date = datetime.now().strftime("%Y%m%d")
        logger.info(f"Generando reportes para la fecha: {current_date}")
        UserModel, LogModel = get_dynamic_models(current_date)

        if not UserModel or not LogModel:
            return render_template(
                "error.html", message="Error al cargar datos para reportes"
            ), 500

        metrics = get_important_metrics(db, UserModel, LogModel)

        if not metrics:
            return render_template(
                "error.html", message="No hay datos disponibles para reportes"
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


@app.route("/install", methods=["POST"])
def install_package():
    install = update_squid()
    if not install:
        return redirect("/")
    else:
        return redirect("/")


@app.route("/update", methods=["POST"])
def update_web():
    install = updateSquidStats()
    if not install:
        return redirect("/")
    else:
        return redirect("/")


@app.route("/blacklist", methods=["GET"])
def blacklist_logs():
    db = None
    try:
        # Obtener parámetros de paginación
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        # Validar parámetros
        if page < 1 or per_page < 1 or per_page > 100:
            return render_template(
                "error.html", message="Parámetros de paginación inválidos"
            ), 400

        db = get_session()

        # Obtener blacklist desde variables de entorno
        blacklist_env = os.getenv("BLACKLIST_DOMAINS")
        blacklist = [
            domain.strip() for domain in blacklist_env.split(",") if domain.strip()
        ]

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
        )

    except ValueError:
        return render_template("error.html", message="Parámetros inválidos"), 400

    except Exception as e:
        logger.error(f"Error en blacklist_logs: {str(e)}")
        return render_template("error.html", message="Error interno del servidor"), 500

    finally:
        if db is not None:
            db.close()


reports_bp = Blueprint("reports", __name__)


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


app.register_blueprint(reports_bp)

# Usar threading.Lock para sincronización
realtime_data_lock = Lock()
realtime_cache_stats = {}
realtime_system_info = {}

# SocketIO en modo threading
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


def realtime_data_thread():
    global realtime_cache_stats, realtime_system_info
    import time

    data_collection_counter = 0

    while True:
        try:
            cache_data = fetch_squid_cache_stats()
            cache_stats = (
                vars(cache_data) if hasattr(cache_data, "__dict__") else cache_data
            )
            system_info = {
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
                "timestamp_utc": datetime.now().isoformat(),
            }
            network_stats = get_network_stats()

            # Guardar métricas en la base de datos solo cada 60 segundos (cada 4 iteraciones)
            data_collection_counter += 1
            if (
                data_collection_counter % 4 == 0
            ):  # Solo cada 4 iteraciones (60 segundos)
                ram_info = get_ram_info()
                swap_info = get_swap_info()
                cpu_info = get_cpu_info()

                # Convertir información de RAM y SWAP a bytes para guardar en BD
                def size_to_bytes(size_str):
                    if not size_str:
                        return 0
                    parts = size_str.strip().split()
                    if len(parts) != 2:
                        return 0
                    value, unit = float(parts[0]), parts[1].upper()
                    multipliers = {
                        "B": 1,
                        "KB": 1024,
                        "MB": 1024**2,
                        "GB": 1024**3,
                        "TB": 1024**4,
                    }
                    return int(value * multipliers.get(unit, 1))

                ram_bytes = size_to_bytes(ram_info.get("used", "0 B"))
                swap_bytes = size_to_bytes(swap_info.get("used", "0 B"))

                # Guardar en base de datos
                MetricsService.save_system_metrics(
                    cpu_usage=cpu_info.get("usage", "0%"),
                    ram_usage_bytes=ram_bytes,
                    swap_usage_bytes=swap_bytes,
                    net_sent_bytes_sec=network_stats.get("bytes_sent_per_sec", 0)
                    if network_stats
                    else 0,
                    net_recv_bytes_sec=network_stats.get("bytes_recv_per_sec", 0)
                    if network_stats
                    else 0,
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
            logger.error(f"Error en hilo de datos en tiempo real: {str(e)}")
        time.sleep(15)  # Actualizar cada 15 segundos en lugar de 5


@app.after_request
def set_response_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# Actualizar la ruta /stats para usar datos en tiempo real
@app.route("/stats")
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


@app.route("/api/metrics/today")
def get_today_metrics():
    """Obtiene métricas del día actual usando el nuevo servicio"""
    try:
        results = MetricsService.get_metrics_today()
        return jsonify(results)
    except Exception as e:
        logger.error(f"Error al obtener métricas del día: {e}")
        return jsonify([])


@app.route("/api/metrics/24hours")
def get_24hours_metrics():
    """Obtiene métricas de las últimas 24 horas"""
    try:
        results = MetricsService.get_metrics_last_24_hours()
        return jsonify(results)
    except Exception as e:
        logger.error(f"Error al obtener métricas de 24 horas: {e}")
        return jsonify([])


@app.route("/api/metrics/latest")
def get_latest_metric():
    """Obtiene la métrica más reciente"""
    try:
        result = MetricsService.get_latest_metric()
        return jsonify(result) if result else jsonify({})
    except Exception as e:
        logger.error(f"Error al obtener la métrica más reciente: {e}")
        return jsonify({})


@app.route("/auditoria", methods=["GET"])
def auditoria_logs():
    return render_template(
        "auditor.html",
        page_icon="magnifying-glass.ico",
        page_title="Centro de Auditoría",
    )


@app.route("/api/all-users", methods=["GET"])
def api_get_all_users():
    """Endpoint para obtener una lista de todos los usuarios para los filtros del frontend."""
    db = get_session()
    try:
        users = get_all_usernames(db)
        return jsonify(users)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/run-audit", methods=["POST"])
def api_run_audit():
    """Endpoint principal que ejecuta la auditoría solicitada desde el frontend."""
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
                return jsonify({"error": "Se requiere un nombre de usuario."}), 400
            result = get_user_activity_summary(db, username, start_date, end_date)
        elif audit_type == "top_users_data":
            result = get_top_users_by_data(db, start_date, end_date)
        elif audit_type == "daily_activity":
            if not start_date:
                return jsonify({"error": "Se requiere una fecha de inicio."}), 400
            if not end_date:
                return jsonify({"error": "Se requiere una fecha de fin."}), 400
            result = get_daily_activity(db, start_date, username)
        elif audit_type == "denied_access":
            result = find_denied_access(db, start_date, end_date, username)
        elif audit_type == "keyword_search":
            if not keyword:
                return jsonify({"error": "Se requiere una palabra clave."}), 400
            result = find_by_keyword(db, start_date, end_date, keyword, username)
        elif audit_type == "social_media_activity":
            if not social_media_sites:
                return jsonify(
                    {"error": "Debe seleccionar al menos una red social."}
                ), 400
            result = find_social_media_activity(
                db, start_date, end_date, social_media_sites, username
            )
        elif audit_type == "ip_activity":
            if not ip_address:
                return jsonify({"error": "Se requiere una dirección IP."}), 400
            result = find_by_ip(db, start_date, end_date, ip_address)
        elif audit_type == "response_code_search":
            if not response_code:
                return jsonify({"error": "Se requiere un código de respuesta."}), 400
            result = find_by_response_code(
                db, start_date, end_date, int(response_code), username
            )
        else:
            return jsonify({"error": "Tipo de auditoría no válido."}), 400

        return jsonify(result)

    except Exception as e:
        # Imprimir el error en el log del servidor para depuración
        print(f"Error en la API de auditoría: {e}")
        return jsonify({"error": "Ocurrió un error interno en el servidor."}), 500
    finally:
        db.close()


# Iniciar el hilo de actualización de datos en tiempo real
if __name__ == "__main__":
    socketio.start_background_task(realtime_data_thread)
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    socketio.run(
        app, debug=debug_mode, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True
    )
