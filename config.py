import logging
import os

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Config:
    SCHEDULER_API_ENABLED = True
    SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(24).hex()
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # CSRF tokens don't expire

    # Database settings
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///squidstats.db")
    DATABASE_TYPE = os.getenv("DATABASE_TYPE", "SQLITE").upper()
    DATABASE_STRING_CONNECTION = os.getenv(
        "DATABASE_STRING_CONNECTION", "/opt/SquidStats/"
    )

    # Squid settings
    SQUID_LOG = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    SQUID_CACHE_LOG = os.getenv("SQUID_CACHE_LOG", "/var/log/squid/cache.log")
    SQUID_HOST = os.getenv("SQUID_HOST", "127.0.0.1")
    SQUID_PORT = int(os.getenv("SQUID_PORT", 3128))
    BLACKLIST_DOMAINS = os.getenv("BLACKLIST_DOMAINS", "")

    # Flask settings
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    LISTEN_HOST = os.getenv("LISTEN_HOST") or os.getenv("FLASK_HOST") or "0.0.0.0"
    LISTEN_PORT = int(os.getenv("LISTEN_PORT") or os.getenv("FLASK_PORT") or 5000)

    # Log parsing mode: 'DETAILED' (current behavior) or 'DEFAULT' (classic Squid format)
    LOG_FORMAT = os.getenv("LOG_FORMAT", "DETAILED").upper()

    # Application version
    VERSION = os.getenv("VERSION", "2.1")

    # Authentication settings
    JWT_SECRET_KEY = SECRET_KEY
    JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", 24))
    MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", 5))
    LOCKOUT_DURATION_MINUTES = int(os.getenv("LOCKOUT_DURATION_MINUTES", 15))
    FIRST_PASSWORD = os.getenv("FIRST_PASSWORD", "").strip()

    # Telegram Notifications
    TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "squidstats_bot")
    TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE")
    TELEGRAM_RECIPIENTS = os.getenv("TELEGRAM_RECIPIENTS", "").split(
        ","
    )  # Comma-separated list

    # Proxy settings
    HTTP_PROXY = os.getenv("HTTP_PROXY", "").strip()
    HTTPS_PROXY = os.getenv("HTTPS_PROXY", "").strip()
    NO_PROXY = os.getenv("NO_PROXY", "").strip()
