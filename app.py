# ------------------- MONKEY PATCHING PARA EVENTLET -------------------
import eventlet
eventlet.monkey_patch()

# ------------------- IMPORTACIONES FLASK Y EXTENSIONES -------------------
from flask import Flask, render_template, request, redirect, jsonify
from flask_socketio import SocketIO, emit
from flask_apscheduler import APScheduler

# ------------------- UTILIDADES Y SERVICIOS PERSONALIZADOS -------------------
from database.database import get_session, get_dynamic_models
from parsers.connections import parse_raw_data, group_by_user
from services.fetch_data import fetch_squid_data
from parsers.cache import fetch_squid_cache_stats
from parsers.log import process_logs
from services.fetch_data_logs import get_users_with_logs_optimized, get_users_with_logs_by_date
from services.blacklist_users import find_blacklisted_sites, find_blacklisted_sites_by_date
from services.system_info import (
    get_network_info, get_os_info, get_uptime, get_ram_info,
    get_swap_info, get_cpu_info, get_squid_version, get_timezone
)
from services.get_reports import get_important_metrics, get_metrics_by_date_range
from utils.colors import color_map
from utils.updateSquid import update_squid
from utils.updateSquidStats import updateSquidStats

# ------------------- PAQUETES ESTÁNDAR -------------------
from dotenv import load_dotenv
from datetime import datetime
import socket
import sys
import os
import logging
import time
from threading import Lock  # Importamos Lock para sincronización de hilos

# ------------------- CONFIGURACIÓN -------------------
class Config:
    SCHEDULER_API_ENABLED = True

load_dotenv()

# ------------------- INICIALIZACIÓN APP -------------------
app = Flask(__name__, static_folder='./static')
app.config.from_object(Config())
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.secret_key = os.urandom(24).hex()

# ------------------- INICIALIZACIÓN SOCKETIO -------------------
# async_mode='eventlet' es obligatorio si usas eventlet.monkey_patch()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ------------------- SCHEDULER -------------------
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# ------------------- LOGGING -------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ======================================================================
# CAMBIO PRINCIPAL: Variables globales para datos en tiempo real
# ======================================================================
# Bloqueo para acceso seguro a las variables compartidas entre hilos
realtime_data_lock = Lock()
# Almacenamiento de las últimas estadísticas de caché
realtime_cache_stats = {}
# Almacenamiento de la última información del sistema
realtime_system_info = {}

# ======================================================================
# CAMBIO PRINCIPAL: Hilo para actualización periódica de datos
# ======================================================================
def realtime_data_thread():
    """Hilo que actualiza los datos del sistema y caché periódicamente y los envía a los clientes via WebSocket"""
    global realtime_cache_stats, realtime_system_info
    
    while True:
        try:
            # Obtener estadísticas de caché de Squid
            cache_data = fetch_squid_cache_stats()
            cache_stats = vars(cache_data) if hasattr(cache_data, '__dict__') else cache_data
            
            # Obtener información del sistema
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
            
            # Actualizar las variables globales con bloqueo
            with realtime_data_lock:
                realtime_cache_stats = cache_stats
                realtime_system_info = system_info
            
            # Emitir los datos actualizados a todos los clientes
            socketio.emit('system_update', {
                'cache_stats': cache_stats,
                'system_info': system_info
            })
            
            logger.info("Datos en tiempo real actualizados y emitidos")
            
        except Exception as e:
            logger.error(f"Error en hilo de datos en tiempo real: {str(e)}")
        
        # Esperar 5 segundos antes de la próxima actualización
        time.sleep(5)

# ======================================================================
# CAMBIO PRINCIPAL: Manejador de conexión WebSocket
# ======================================================================
@socketio.on('connect')
def handle_connect():
    """Manejador para cuando un cliente se conecta a través de WebSocket"""
    logger.info(f"Cliente conectado: {request.sid}")
    
    # Enviar los datos actuales al cliente que se acaba de conectar
    with realtime_data_lock:
        if realtime_cache_stats and realtime_system_info:
            emit('system_update', {
                'cache_stats': realtime_cache_stats,
                'system_info': realtime_system_info
            })

# ------------------- NO CACHÉ PARA RESPUESTAS -------------------
@app.after_request
def set_response_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ------------------- RUTA PRINCIPAL -------------------
@app.route('/')
def index():
    try:
        raw_data = fetch_squid_data()
        if 'Error' in raw_data:
            logger.error(f"Failed to fetch Squid data: {raw_data}")
            return render_template('error.html', message="Error connecting to Squid"), 500

        connections = parse_raw_data(raw_data)
        grouped_connections = group_by_user(connections)

        return render_template(
            'index.html',
            grouped_connections=grouped_connections,
            page_icon='favicon.ico',
            page_title='Inicio Dashboard'
        )
    except Exception as e:
        logger.error(f"Unexpected error in index route: {str(e)}")
        return render_template('error.html', message="An unexpected error occurred"), 500

# ------------------- RUTA AJAX PARA ACTUALIZAR CONEXIONES -------------------
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

# ------------------- VISTA DE ESTADÍSTICAS -------------------
@app.route('/stats')
def cache_stats():
    try:
        # CAMBIO: Usamos las variables globales para obtener los datos más recientes
        with realtime_data_lock:
            stats_data = realtime_cache_stats if realtime_cache_stats else {}
            system_info = realtime_system_info if realtime_system_info else {}
        
        # Si no hay datos en tiempo real, intentamos obtenerlos de forma síncrona
        if not stats_data:
            data = fetch_squid_cache_stats()
            stats_data = vars(data) if hasattr(data, '__dict__') else data
        if not system_info:
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

        logger.info("Successfully fetched cache statistics and system info")
        return render_template(
            'cacheView.html',
            cache_stats=stats_data,
            system_info=system_info,
            page_icon='statistics.ico',
            page_title='Estadísticas del Sistema'
        )
    except Exception as e:
        logger.error(f"Error in /stats: {str(e)}")
        return render_template('error.html', message="Error retrieving cache statistics or system info"), 500

# ------------------- VISTA DE LOGS DE USUARIOS -------------------
@app.route('/logs')
def logs():
    db = None
    try:
        db = get_session()
        users_data = get_users_with_logs_optimized(db)
        return render_template('logsView.html', users_data=users_data, page_icon='user.ico', page_title='Actividad usuarios')
    except Exception as e:
        logger.error(f"Error en ruta /logs: {e}")
        return render_template('error.html', message="Error retrieving logs"), 500
    finally:
        if db:
            db.close()

# ------------------- VISTA DE REPORTES -------------------
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

# ------------------- API: LOGS POR FECHA -------------------
@app.route('/get-logs-by-date', methods=['POST'])
def get_logs_by_date():
    db = None
    try:
        date_str = request.json.get('date')
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        date_suffix = selected_date.strftime('%Y%m%d')

        db = get_session()
        users_data = get_users_with_logs_by_date(db, date_suffix)
        return jsonify(users_data)
    except ValueError:
        return jsonify({'error': 'Formato de fecha inválido'}), 400
    except Exception as e:
        logger.error(f"Error en get-logs-by-date: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()

# ------------------- INSTALACIÓN DE SQUID -------------------
@app.route('/install', methods=['POST'])
def install_package():
    success = update_squid()
    return redirect('/')

# ------------------- ACTUALIZACIÓN DE STATS -------------------
@app.route('/update', methods=['POST'])
def update_web():
    success = updateSquidStats()
    return redirect('/')

# ------------------- VISTA DE REGISTROS BLOQUEADOS -------------------
@app.route('/blacklist')
def blacklist_logs():
    db = None
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        if page < 1 or per_page < 1 or per_page > 100:
            return render_template('error.html', message="Parámetros de paginación inválidos"), 400

        db = get_session()
        blacklist = ["facebook.com", "twitter.com", "instagram.com", "tiktok.com"]
        result_data = find_blacklisted_sites(db, blacklist, page, per_page)

        if 'error' in result_data:
            return render_template('error.html', message=result_data['error']), 500

        return render_template(
            'blacklist.html',
            results=result_data['results'],
            pagination=result_data['pagination'],
            current_page=page,
            page_icon='shield-exclamation.ico',
            page_title='Registros Bloqueados'
        )
    except Exception as e:
        logger.error(f"Error en blacklist_logs: {str(e)}")
        return render_template('error.html', message="Error interno del servidor"), 500
    finally:
        if db:
            db.close()

# ------------------- REPORTES POR RANGO -------------------
@app.route('/reports-range', methods=['POST'])
def reports_by_range():
    db = None
    try:
        start_date = request.json.get('start_date')
        end_date = request.json.get('end_date')

        if not start_date or not end_date:
            return jsonify({'error': 'Fechas requeridas'}), 400

        db = get_session()
        metrics = get_metrics_by_date_range(start_date, end_date, db)
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error en reports-range: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()

# ------------------- PROCESAMIENTO DE LOGS AUTOMÁTICO -------------------
@scheduler.task('interval', id='do_job_1', seconds=30, misfire_grace_time=900)
def init_scheduler():
    log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    logger.info(f"Configurando scheduler para el archivo de log: {log_file}")
    if not os.path.exists(log_file):
        logger.error(f"Archivo de log no encontrado: {log_file}")
        return
    process_logs(log_file)

# ------------------- FILTRO DE FORMATO DE BYTES PARA TEMPLATES -------------------
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

# ------------------- FILTRO DE DIVISIÓN SEGURA -------------------
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

# ------------------- EJECUCIÓN DE LA APLICACIÓN -------------------
if __name__ == "__main__":
    # CAMBIO PRINCIPAL: Iniciar el hilo de actualización de datos en tiempo real
    socketio.start_background_task(realtime_data_thread)
    
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=5000)