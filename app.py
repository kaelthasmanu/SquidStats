import atexit
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, request, session
from flask_apscheduler import APScheduler
from flask_babel import Babel
from flask_socketio import SocketIO
from loguru import logger

from config import Config
from database.database import migrate_database
from routes import register_routes
from routes.auth_routes import csrf
from routes.stats_routes import realtime_data_thread
from services.auth.auth_service import AuthConfig
from services.notifications.notifications import (
    set_socketio_instance,
    start_notification_monitor,
    stop_notification_monitor,
)
from services.scheduler.scheduler_tasks import register_scheduler_tasks
from utils.filters import register_filters

logger.add(
    "logs/app.log", rotation="100 MB", colorize=True, retention="31 days", level="INFO"
)

# Import Telegram integration (optional)
try:
    from services.notifications.telegram_integration import (
        cleanup_telegram,
        initialize_telegram_service,
    )

    TELEGRAM_AVAILABLE = True
except Exception:
    TELEGRAM_AVAILABLE = False
    initialize_telegram_service = None
    cleanup_telegram = None

# Load environment variables
load_dotenv()

# Global shutdown event
shutdown_event = threading.Event()


def create_app():
    # Run database migration at startup
    logger.info("Running database migrations with Alembic...")
    try:
        migrate_database()
        logger.info("✓ Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        logger.error(
            "Please check your database configuration and run: python manage_db.py init"
        )
        # Continue anyway - the app might still work with existing schema

    # Migrate legacy BLACKLIST_DOMAINS from .env into DB (non-interactive)
    try:
        from manage_db import migrate_env_blacklist

        logger.info("Checking for legacy BLACKLIST_DOMAINS to migrate into DB...")
        migrate_env_blacklist(auto_confirm=True)
    except Exception as e:
        logger.error(f"Error migrating BLACKLIST_DOMAINS into DB: {e}")

    app = Flask(__name__, static_folder="./static")
    app.config.from_object(Config())

    # Configure session for remember me functionality
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        days=AuthConfig.REMEMBER_ME_DAYS
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = AuthConfig.SESSION_COOKIE_HTTPONLY
    app.config["SESSION_COOKIE_SECURE"] = AuthConfig.SESSION_COOKIE_SECURE
    app.config["SESSION_COOKIE_SAMESITE"] = AuthConfig.SESSION_COOKIE_SAMESITE

    # Initialize CSRF protection (shared instance with routes)
    csrf.init_app(app)

    # Initialize Flask-Babel for i18n
    def get_locale():
        # 1. Check session
        lang = session.get("lang")
        if lang and lang in Config.BABEL_SUPPORTED_LOCALES:
            return lang
        # 2. Check cookie
        lang = request.cookies.get("lang")
        if lang and lang in Config.BABEL_SUPPORTED_LOCALES:
            return lang
        # 3. Check Accept-Language header
        return request.accept_languages.best_match(
            Config.BABEL_SUPPORTED_LOCALES, default=Config.BABEL_DEFAULT_LOCALE
        )

    Babel(app, locale_selector=get_locale)

    # Make get_locale available in templates
    app.jinja_env.globals["get_locale"] = get_locale
    app.jinja_env.globals["LANGUAGES"] = Config.LANGUAGES

    # Initialize extensions
    # Pass explicit timezone to avoid tzlocal.get_localzone() failures in containers
    scheduler = APScheduler(scheduler=BackgroundScheduler(timezone=timezone.utc))
    scheduler.init_app(app)
    scheduler.start()

    # Register custom filters
    register_filters(app)

    # Register the date format filter for notifications
    @app.template_filter("datetime_format")
    def datetime_format(value, format="%d/%m/%Y %H:%M"):
        """Filtro para formatear fechas en las plantillas"""
        if isinstance(value, str):
            try:
                # Handle ISO format
                if "T" in value:
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                else:
                    # Try other common formats
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
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
    # Register all scheduler tasks from services.scheduler.scheduler_tasks and plugins.
    register_scheduler_tasks(scheduler)


def shutdown_app(scheduler, socketio):
    logger.info("\n🛑 Shutting down SquidStats...")

    # Set shutdown event to stop all threads
    shutdown_event.set()

    # Stop notification monitor
    logger.info("Stopping notification monitor...")
    stop_notification_monitor()

    # Cleanup Telegram service
    if TELEGRAM_AVAILABLE and cleanup_telegram:
        logger.info("Cleaning up Telegram service...")
        try:
            cleanup_telegram()
        except Exception as e:
            logger.error(f"Error cleaning up Telegram: {e}")

    # Stop scheduler
    logger.info("Stopping scheduler...")
    try:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")

    # Stop SocketIO
    logger.info("Stopping SocketIO...")
    try:
        if socketio:
            socketio.stop()
    except Exception as e:
        logger.error(f"Error stopping SocketIO: {e}")

    logger.info("✅ Shutdown complete")


def main():
    # Create Flask app and scheduler
    app, scheduler = create_app()

    # Setup scheduler tasks
    setup_scheduler_tasks(scheduler)

    # Initialize SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    # Set up Socket.IO in the notifications module
    set_socketio_instance(socketio)

    # Initialize Telegram service if available
    if TELEGRAM_AVAILABLE and initialize_telegram_service:
        logger.info("Initializing Telegram service...")
        try:
            initialize_telegram_service()
        except Exception as e:
            logger.error(f"Failed to initialize Telegram: {e}")

    # Start the notification monitor
    start_notification_monitor()

    # Start real-time data collection thread
    socketio.start_background_task(realtime_data_thread, socketio, shutdown_event)

    # Register signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"\n⚠️ Received signal {signum}")
        shutdown_app(scheduler, socketio)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # kill command

    # Register cleanup on exit
    atexit.register(lambda: shutdown_app(scheduler, socketio))

    # Run the application
    debug_mode = Config.DEBUG
    logger.info(
        f"Starting SquidStats application in {'debug' if debug_mode else 'production'} mode"
    )

    # Read host/port from environment variables if they exist (compatible with FLASK_HOST/PORT)
    host = Config.LISTEN_HOST
    port = Config.LISTEN_PORT

    try:
        socketio.run(
            app, debug=debug_mode, host=host, port=port, allow_unsafe_werkzeug=True
        )
    except KeyboardInterrupt:
        logger.info("\n⚠️ Keyboard interrupt received")
        shutdown_app(scheduler, socketio)
    except Exception as e:
        logger.error(f"Application error: {e}")
        shutdown_app(scheduler, socketio)
        raise


if __name__ == "__main__":
    main()
