from flask import Flask, render_template

from database.database import get_session
from parsers.connections import parse_raw_data, group_by_user
from services.fetch_data import fetch_squid_data
from parsers.cache import fetch_squid_cache_stats
import os
import logging
from parsers.log import process_logs
from flask_apscheduler import APScheduler
from services.fetch_data_logs import get_users_with_logs_optimized


# set configuration values
class Config:
    SCHEDULER_API_ENABLED = True

# Load environment variables

# Initialize Flask application
app = Flask(__name__, static_folder='./static')
app.config.from_object(Config())
scheduler = APScheduler()
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
        return render_template('index.html', grouped_connections=grouped_connections)

    except Exception as e:
        logger.error(f"Unexpected error in index route: {str(e)}")
        return render_template('error.html', message="An unexpected error occurred"), 500


@app.route('/stats')
def cache_stats():
    """Page showing Squid cache statistics."""
    try:
        data = fetch_squid_cache_stats()
        stats_data = vars(data) if hasattr(data, '__dict__') else data
        logger.info("Successfully fetched cache statistics")
        return render_template('cacheView.html', cache_stats=stats_data)

    except Exception as e:
        logger.error(f"Error fetching cache stats: {str(e)}")
        return render_template('error.html', message="Error retrieving cache statistics"), 500


@app.route('/logs')
def logs():
    try:
        db = get_session()
        users_data = get_users_with_logs_optimized(db)

        return render_template('logsView.html', users_data=users_data)
    except Exception as e:
        print(f"Error en ruta /logs: {e}")
        return render_template('error.html', message="Error retrieving logs"), 500

@scheduler.task('interval', id='do_job_1', seconds=30, misfire_grace_time=900)
def init_scheduler():
    """Initialize and start the background scheduler for log processing"""
    log_file = os.getenv("SQUID_LOG", "access.log")
    logger.info(f"Configurando scheduler para el archivo de log: {log_file}")

    if not os.path.exists(log_file):
        logger.error(f"Archivo de log no encontrado: {log_file}")
        return
    else:
        process_logs(log_file)


if __name__ == "__main__":

    # Execute app with Flask
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)