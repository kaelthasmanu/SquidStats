import os

from dotenv import load_dotenv
from flask import Flask
from flask_apscheduler import APScheduler
from flask_socketio import SocketIO

from config import Config, logger
from parsers.log import process_logs
from routes import register_routes
from routes.main_routes import initialize_proxy_detection
from routes.stats_routes import realtime_data_thread
from services.metrics_service import MetricsService
from utils.filters import register_filters

# Load environment variables
load_dotenv()


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder="./static")
    app.config.from_object(Config())

    # Initialize extensions
    scheduler = APScheduler()
    scheduler.init_app(app)
    scheduler.start()

    # Register custom filters
    register_filters(app)

    # Register all route blueprints
    register_routes(app)

    # Initialize proxy detection
    initialize_proxy_detection()

    # Configure response headers
    @app.after_request
    def set_response_headers(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    return app, scheduler


def setup_scheduler_tasks(scheduler):
    """Configure scheduler tasks."""

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
    """Main application entry point."""
    # Create Flask app and scheduler
    app, scheduler = create_app()

    # Setup scheduler tasks
    setup_scheduler_tasks(scheduler)

    # Initialize SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    # Start real-time data collection thread
    socketio.start_background_task(realtime_data_thread, socketio)

    # Run the application
    debug_mode = Config.DEBUG
    logger.info(
        f"Starting SquidStats application in {'debug' if debug_mode else 'production'} mode"
    )

    socketio.run(
        app, debug=debug_mode, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True
    )


if __name__ == "__main__":
    main()
