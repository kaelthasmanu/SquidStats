import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask
from flask_apscheduler import APScheduler
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect

from config import Config, logger
from database.database import migrate_database
from parsers.log import process_logs
from routes import register_routes
from routes.stats_routes import realtime_data_thread
from services.metrics_service import MetricsService
from services.notifications import (
    has_remote_commits_with_messages,
    set_commit_notifications,
    set_socketio_instance,
    start_notification_monitor,
)
from utils.filters import register_filters

# Load environment variables
load_dotenv()


def create_app():
    # Run database migration at startup
    logger.info("Running database migration at startup...")
    try:
        migrate_database()
        logger.info("Database migration completed successfully")
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        # Continue anyway - the app might still work with existing schema

    app = Flask(__name__, static_folder="./static")
    app.config.from_object(Config())

    # Initialize CSRF protection
    CSRFProtect(app)

    # Initialize extensions
    scheduler = APScheduler()
    scheduler.init_app(app)
    scheduler.start()

    # Register custom filters
    register_filters(app)

    # Register the date format filter for notifications
    @app.template_filter('datetime_format')
    def datetime_format(value, format='%d/%m/%Y %H:%M'):
        """Filtro para formatear fechas en las plantillas"""
        if isinstance(value, str):
            try:
                # Handle ISO format
                if 'T' in value:
                    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                else:
                    # Try other common formats
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f']:
                        try:
                            value = datetime.strptime(value, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        return value  # Could not parse, returning original
            except Exception:
                return value
        if isinstance(value, datetime):
            return value.strftime(format)
        return value

    # Register all route blueprints
    register_routes(app)


    # Configure response headers
    @app.after_request
    def set_response_headers(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    return app, scheduler


def setup_scheduler_tasks(scheduler):
    @scheduler.task(
        "interval", id="check_notifications", minutes=30, misfire_grace_time=1800
    )
    def check_notifications_task():
        repo_path = os.path.dirname(os.path.abspath(__file__))
        has_updates, messages = has_remote_commits_with_messages(repo_path)
        set_commit_notifications(has_updates, messages)

    @scheduler.task("interval", id="do_job_1", seconds=30, misfire_grace_time=900)
    def init_scheduler():
        log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
        logger.info(f"Scheduler for file log: {log_file}")

        if not os.path.exists(log_file):
            logger.error(f"Log file not found: {log_file}")
            return
        else:
            process_logs(log_file)

    @scheduler.task("interval", id="cleanup_metrics", hours=1, misfire_grace_time=3600)
    def cleanup_old_metrics():
        try:
            success = MetricsService.cleanup_old_metrics()
            if success:
                logger.info("Cleanup of old metrics completed successfully")
            else:
                logger.warning("Error during cleanup of old metrics")
        except Exception as e:
            logger.error(f"Error in metrics cleanup task: {e}")


def main():
    # Create Flask app and scheduler
    app, scheduler = create_app()

    # Setup scheduler tasks
    setup_scheduler_tasks(scheduler)

    # Initialize SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    # Set up Socket.IO in the notifications module
    set_socketio_instance(socketio)

    # Start the notification monitor
    start_notification_monitor()

    # Start real-time data collection thread
    socketio.start_background_task(realtime_data_thread, socketio)

    # Run the application
    debug_mode = Config.DEBUG
    logger.info(
        f"Starting SquidStats application in {'debug' if debug_mode else 'production'} mode"
    )

    # Read host/port from environment variables if they exist (compatible with FLASK_HOST/PORT)
    host = os.getenv("LISTEN_HOST") or os.getenv("FLASK_HOST") or "0.0.0.0"
    port_str = os.getenv("LISTEN_PORT") or os.getenv("FLASK_PORT") or "5000"
    try:
        port = int(port_str)
    except ValueError:
        logger.warning(f"Invalid PORT value '{port_str}', falling back to 5000")
        port = 5000

    socketio.run(
        app, debug=debug_mode, host=host, port=port, allow_unsafe_werkzeug=True
    )


if __name__ == "__main__":
    main()
