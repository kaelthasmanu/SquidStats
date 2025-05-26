from flask import Flask, render_template, request, redirect, jsonify
from database.database import get_session
from parsers.connections import parse_raw_data, group_by_user
from services.fetch_data import fetch_squid_data
from parsers.cache import fetch_squid_cache_stats
import os
import logging
from parsers.log import process_logs
from flask_apscheduler import APScheduler
from services.fetch_data_logs import get_users_with_logs_optimized
from dotenv import load_dotenv
from services.get_reports import get_important_metrics
from utils.colors import color_map
from utils.updateSquid import update_squid
from utils.updateSquidStats import updateSquidStats
import datetime
#from services.fetch_data_logs import get_users_with_logs_by_date
from services.blacklist_users import find_blacklisted_sites, find_blacklisted_sites_by_date

# set configuration values
class Config:
    SCHEDULER_API_ENABLED = True

load_dotenv()

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
    """Main page showing Squid statistics grouped by users."""
    try:
        raw_data = fetch_squid_data()
        if 'Error' in raw_data:
            logger.error(f"Failed to fetch Squid data: {raw_data}")
            return render_template('error.html', message="Error connecting to Squid"), 500

        connections = parse_raw_data(raw_data)
        grouped_connections = group_by_user(connections)

        return render_template(
            'index.html',
            grouped_connections=grouped_connections, page_icon='favicon.ico', page_title='Inicio Dashboard')

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

@app.route('/stats')
def cache_stats():
    """Page showing Squid cache statistics."""
    try:
        data = fetch_squid_cache_stats()
        stats_data = vars(data) if hasattr(data, '__dict__') else data
        logger.info("Successfully fetched cache statistics")
        return render_template('cacheView.html', cache_stats=stats_data, page_icon='statistics.ico', page_title='Estadísticas')

    except Exception as e:
        logger.error(f"Error fetching cache stats: {str(e)}")
        return render_template('error.html', message="Error retrieving cache statistics"), 500

@app.route('/logs')
def logs():
    try:
        db = get_session()
        users_data = get_users_with_logs_optimized(db)

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

'''
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

    except ValueError as ve:
        return jsonify({'error': 'Formato de fecha inválido'}), 400
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if db is not None:
            db.close()

'''
@app.route('/reports')
def reports():
    db = get_session()
    metrics = get_important_metrics(db)

    http_codes = metrics['http_response_distribution']
    http_codes = sorted(metrics['http_response_distribution'], key=lambda x: x['count'], reverse=True)
    main_codes = http_codes[:8]
    other_codes = http_codes[8:]

    if other_codes:
        other_count = sum(item['count'] for item in other_codes)
        main_codes.append({'response_code': 'Otros', 'count': other_count})

    metrics['http_response_distribution_chart'] = {
        'labels': [str(item['response_code']) for item in main_codes],
        'data': [item['count'] for item in main_codes],
        'colors': [color_map.get(str(code['response_code']), color_map['Otros']) for code in main_codes]
    }

    return render_template('reports.html', metrics=metrics, page_icon='bar.ico', page_title='Reportes y gráficas')

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
def check_blacklist():
    db = None
    db = get_session()
    try:
        blacklist = ["facebook.com", "twitter.com", "instagram.com", "tiktok.com"]  # Ejemplo
        resultados = find_blacklisted_sites(db, blacklist)

        return render_template('blacklist.html',
                               results=resultados,
                               page_icon='shield-exclamation.ico',
                               page_title='Registros de Blacklist')
    except Exception as e:
        logger.error(f"Error en check-blacklist: {str(e)}")
        return jsonify({'error': 'Error interno del servidor'}), 500

    finally:
        if db is not None:
            db.close()


@app.route('/check-blacklist-by-date', methods=['POST'])
def check_blacklist_by_date():
    db = None
    try:
        data = request.get_json()
        if not data or 'sites' not in data or 'date' not in data:
            return jsonify({'error': 'Parámetros faltantes'}), 400

        blacklist = data['sites']
        date_str = data['date']

        try:
            fecha_consulta = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Formato de fecha inválido (usar YYYY-MM-DD)'}), 400

        db = get_session()
        resultados = find_blacklisted_sites_by_date(db, blacklist, fecha_consulta)

        return jsonify({
            'date': date_str,
            'count': len(resultados),
            'results': resultados
        })

    except Exception as e:
        logger.error(f"Error en check-blacklist-by-date: {str(e)}")
        return jsonify({'error': 'Error interno del servidor'}), 500

    finally:
        if db is not None:
            db.close()

if __name__ == "__main__":

    # Execute app with Flask
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)