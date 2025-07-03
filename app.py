import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, redirect, jsonify, render_template_string
from flask_socketio import SocketIO, emit
from flask_apscheduler import APScheduler
from database.database import (
    create_dynamic_tables, get_engine, get_session, get_dynamic_models
)
from parsers.connections import parse_raw_data, group_by_user
from services.fetch_data import fetch_squid_data
from parsers.cache import fetch_squid_cache_stats
from parsers.log import process_logs, find_last_parent_proxy
from services.fetch_data_logs import get_users_logs, get_users_with_logs_by_date
from services.blacklist_users import find_blacklisted_sites, find_blacklisted_sites_by_date
from services.system_info import (
    get_network_info, get_os_info, get_uptime, get_ram_info,
    get_swap_info, get_cpu_info, get_squid_version, get_timezone, get_network_stats
)
from services.get_reports import get_important_metrics, get_metrics_by_date_range
from utils.colors import color_map
from utils.updateSquid import update_squid
from utils.updateSquidStats import updateSquidStats
from dotenv import load_dotenv
from datetime import datetime
import socket
import sys
import os
import logging
import time
from threading import Lock  # Importamos Lock para sincronización de hilos

class Config:
    SCHEDULER_API_ENABLED = True

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

parent_proxy_lock = Lock()

g_parent_proxy_ip = find_last_parent_proxy(os.getenv("SQUID_LOG", "/var/log/squid/access.log"))
if g_parent_proxy_ip:
    logger.info(f"Proxy padre detectado con IP: {g_parent_proxy_ip}. Esta configuración se mantendrá fija.")
else:
    logger.info("No se detectó un proxy padre en los logs recientes. Asumiendo conexión directa.")

# Initialize Flask application
app = Flask(__name__, static_folder='./static')
app.config.from_object(Config())
scheduler = APScheduler()
app.secret_key = os.urandom(24).hex()
scheduler.init_app(app)
scheduler.start()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.route('/')
def index():
    try:
        raw_data = fetch_squid_data()
        if 'Error' in raw_data:
            logger.error(f"Failed to fetch Squid data: {raw_data}")
            return render_template('error.html', message="Error connecting to Squid"), 500

        connections = parse_raw_data(raw_data)
        grouped_connections = group_by_user(connections)

        with parent_proxy_lock:
            parent_ip = g_parent_proxy_ip

        squid_version = get_squid_version()
        network_info = get_network_info()
        squid_ip = "No disponible"
        if isinstance(network_info, list) and network_info:
            squid_ip = network_info[0].get('ip', 'No disponible')
        
        return render_template(
            'index.html',
            grouped_connections=grouped_connections,
            parent_proxy_ip=parent_ip,
            squid_ip=squid_ip,
            squid_version=squid_version,
            page_icon='favicon.ico',
            page_title='Inicio Dashboard'
        )
    except Exception as e:
        logger.error(f"Unexpected error in index route: {str(e)}")
        return render_template('error.html', message="An unexpected error occurred"), 500

@app.route('/actualizar-conexiones')
def actualizar_conexiones():
    try:
        raw_data = fetch_squid_data()
        if 'Error' in raw_data:
            logger.error(f"Failed to fetch Squid data: {raw_data}")
            return "Error", 500

        connections = parse_raw_data(raw_data)
        grouped_connections = group_by_user(connections)
        return render_template('partials/conexiones.html', grouped_connections=grouped_connections)

    except Exception as e:
        logger.error(f"Unexpected error in /actualizar-conexiones route: {str(e)}")
        return "Error interno", 500

@app.route('/logs')
def logs():
    try:
        db = get_session()
        users_data = get_users_logs(db)

        return render_template('logsView.html', users_data=users_data, page_icon='user.ico', page_title='Actividad usuarios' )
    except Exception as e:
        print(f"Error en ruta /logs: {e}")
        return render_template('error.html', message="Error retrieving logs"), 500

@scheduler.task('interval', id='do_job_1', seconds=30, misfire_grace_time=900)
def init_scheduler():
    """Initialize and start the background scheduler for log processing"""
    log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    logger.info(f"Configurando scheduler para el archivo de log: {log_file}")

    if not os.path.exists(log_file):
        logger.error(f"Archivo de log no encontrado: {log_file}")
        return
    else:
        process_logs(log_file)

@app.template_filter('divide')
def divide_filter(value, divisor):
    return value / divisor

@app.template_filter('format_bytes')
def format_bytes_filter(value):
    value = int(value)
    if value >= 1024**3:  # GB
        return f"{(value / (1024**3)):.2f} GB"
    elif value >= 1024**2:  # MB
        return f"{(value / (1024**2)):.2f} MB"
    elif value >= 1024:  # KB
        return f"{(value / 1024):.2f} KB"
    return f"{value} bytes"

@app.route('/get-logs-by-date', methods=['POST'])
def get_logs_by_date():
    db = None
    try:
        page_int = request.json.get('page')
        page = request.args.get('page', page_int, type=int)
        per_page = request.args.get('per_page', 15, type=int)
        date_str = request.json.get('date')
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        date_suffix = selected_date.strftime('%Y%m%d')

        db = get_session()
        users_data = get_users_logs(db, date_suffix, page=page, per_page=per_page)
        return jsonify(users_data)
    except ValueError:
        return jsonify({'error': 'Formato de fecha inválido'}), 400
    except Exception as e:
        logger.error(f"Error en get-logs-by-date: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()

@app.route('/reports')
def reports():
    db = None
    try:
        db = get_session()
        current_date = datetime.now().strftime("%Y%m%d")
        logger.info(f"Generando reportes para la fecha: {current_date}")
        UserModel, LogModel = get_dynamic_models(current_date)

        if not UserModel or not LogModel:
            return render_template('error.html', message="Error al cargar datos para reportes"), 500

        metrics = get_important_metrics(db, UserModel, LogModel)

        if not metrics:
            return render_template('error.html', message="No hay datos disponibles para reportes"), 404

        http_codes = metrics.get('http_response_distribution', [])
        http_codes = sorted(http_codes, key=lambda x: x['count'], reverse=True)
        main_codes = http_codes[:8]
        other_codes = http_codes[8:]

        if other_codes:
            other_count = sum(item['count'] for item in other_codes)
            main_codes.append({'response_code': 'Otros', 'count': other_count})

        metrics['http_response_distribution_chart'] = {
            'labels': [str(item['response_code']) for item in main_codes],
            'data': [item['count'] for item in main_codes],
            'colors': [color_map.get(str(item['response_code']), color_map['Otros']) for item in main_codes]
        }

        return render_template('reports.html', metrics=metrics, page_icon='bar.ico', page_title='Reportes y gráficas')
    except Exception as e:
        logger.error(f"Error en ruta /reports: {str(e)}", exc_info=True)
        return render_template('error.html', message="Error interno generando reportes"), 500
    finally:
        if db:
            db.close()

@app.route('/install', methods=['POST'])
def install_package():
    install = update_squid()
    if install == False:
        return redirect('/')
    else:
        return redirect('/')

@app.route('/update', methods=['POST'])
def update_web():
    install = updateSquidStats()
    if install == False:
        return redirect('/')
    else:
        return redirect('/')

@app.route('/blacklist', methods=['GET'])
def blacklist_logs():
    db = None
    try:
        # Obtener parámetros de paginación
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        # Validar parámetros
        if page < 1 or per_page < 1 or per_page > 100:
            return render_template('error.html',
                                   message="Parámetros de paginación inválidos"), 400

        db = get_session()

        # Obtener blacklist desde variables de entorno
        blacklist_env = os.getenv('BLACKLIST_DOMAINS')
        blacklist = [domain.strip() for domain in blacklist_env.split(',') if domain.strip()]

        # Obtener resultados paginados
        result_data = find_blacklisted_sites(db, blacklist, page, per_page)

        if 'error' in result_data:
            return render_template('error.html',
                                   message=result_data['error']), 500

        return render_template(
            'blacklist.html',
            results=result_data['results'],
            pagination=result_data['pagination'],
            current_page=page,
            page_icon='shield-exclamation.ico',
            page_title='Registros Bloqueados'
        )

    except ValueError:
        return render_template('error.html',
                               message="Parámetros inválidos"), 400

    except Exception as e:
        logger.error(f"Error en blacklist_logs: {str(e)}")
        return render_template('error.html',
                               message="Error interno del servidor"), 500

    finally:
        if db is not None:
            db.close()

if __name__ == "__main__":

    # Execute app with Flask
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    # CAMBIO PRINCIPAL: Configurar SocketIO y variables globales para tiempo real
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    
    # async_mode='eventlet' es obligatorio si usas eventlet.monkey_patch()
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

    realtime_data_lock = Lock()
    realtime_cache_stats = {}
    realtime_system_info = {}

    def realtime_data_thread():
        global realtime_cache_stats, realtime_system_info

        while True:
            try:
                cache_data = fetch_squid_cache_stats()
                cache_stats = vars(cache_data) if hasattr(cache_data, '__dict__') else cache_data
                
                system_info = {
                    'hostname': socket.gethostname(),
                    'ips': get_network_info(),
                    'os': get_os_info(),
                    'uptime': get_uptime(),
                    'ram': get_ram_info(),
                    'swap': get_swap_info(),
                    'cpu': get_cpu_info(),
                    'python_version': sys.version.split()[0],
                    'squid_version': get_squid_version(),
                    'timezone': get_timezone(),
                    'local_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                network_stats = get_network_stats()
                
                # Actualizar las variables globales con bloqueo
                with realtime_data_lock:
                    realtime_cache_stats = cache_stats
                    realtime_system_info = system_info
                
                socketio.emit('system_update', {
                    'cache_stats': cache_stats,
                    'system_info': system_info,
                    'network_stats': network_stats
                })
                
            except Exception as e:
                logger.error(f"Error en hilo de datos en tiempo real: {str(e)}")
            
            eventlet.sleep(5)

    #Manejador de conexión WebSocket
    @socketio.on('connect')
    def handle_connect():
        logger.info(f"Cliente conectado: {request.sid}")
        
        with realtime_data_lock:
            cache_stats = realtime_cache_stats
            system_info = realtime_system_info

        if cache_stats or system_info:  # solo si hay datos válidos
            network_stats = get_network_stats()
            socketio.emit('system_update', {
                'cache_stats': cache_stats,
                'system_info': system_info,
                'network_stats': network_stats
            })

    @app.after_request
    def set_response_headers(response):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # Actualizar la ruta /stats para usar datos en tiempo real
    @app.route('/stats')
    def cache_stats_realtime():
        try:
            with realtime_data_lock:
                stats_data = realtime_cache_stats if realtime_cache_stats else {}
                system_info_data = realtime_system_info if realtime_system_info else {}
            
            if not stats_data:
                data = fetch_squid_cache_stats()
                stats_data = vars(data) if hasattr(data, '__dict__') else data
            
            if not system_info_data:
                system_info_data = {
                    'hostname': socket.gethostname(), 
                    'ips': get_network_info(),
                    'os': get_os_info(), 
                    'uptime': get_uptime(), 
                    'ram': get_ram_info(),
                    'swap': get_swap_info(), 
                    'cpu': get_cpu_info(),
                    'python_version': sys.version.split()[0],
                    'squid_version': get_squid_version(), 
                    'timezone': get_timezone(),
                    'local_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            
            network_stats = get_network_stats()
            logger.info("Successfully fetched cache statistics and system info")
            return render_template(
                'cacheView.html',
                cache_stats=stats_data,
                system_info=system_info_data,
                network_stats=network_stats,
                page_icon='statistics.ico',
                page_title='Estadísticas del Sistema'
            )
        except Exception as e:
            logger.error(f"Error in /stats: {str(e)}")
            return render_template('error.html', message="Error retrieving cache statistics or system info"), 500

    # Actualizar funciones de template
    @app.template_filter('format_bytes')
    def format_bytes_filter(value):
        value = int(value)
        if value >= 1024**3:
            return f"{(value / (1024**3)):.2f} GB"
        elif value >= 1024**2:
            return f"{(value / (1024**2)):.2f} MB"
        elif value >= 1024:
            return f"{(value / 1024):.2f} KB"
        return f"{value} bytes"

    @app.template_filter('divide')
    def divide_filter(numerator, denominator, precision=2):
        try:
            num = float(numerator)
            den = float(denominator)
            if den == 0:
                logger.warning("Intento de división por cero en plantilla")
                return 0.0
            return round(num / den, precision)
        except (TypeError, ValueError) as e:
            logger.error(f"Error en filtro divide: {str(e)}")
            return 0.0

    from flask import Blueprint
    from datetime import date
    from services.fetch_data_logs import get_metrics_for_date

    reports_bp = Blueprint('reports', __name__)

    @reports_bp.route('/dashboard')
    def dashboard():
        date_str = request.args.get('date')
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = date.today()
        else:
            selected_date = date.today()

        metrics = get_metrics_for_date(selected_date)

        return render_template(
            'components/graph_reports.html',
            metrics=metrics,
            selected_date=selected_date
        )

    app.register_blueprint(reports_bp)

    # Iniciar el hilo de actualización de datos en tiempo real
    socketio.start_background_task(realtime_data_thread)
    
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=5000)

if __name__ == "__main__":
    # CAMBIO PRINCIPAL: Iniciar el hilo de actualización de datos en tiempo real
    socketio.start_background_task(realtime_data_thread)
    
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=5000)