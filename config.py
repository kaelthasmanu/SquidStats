import logging
import os
from typing import Any

from dotenv import load_dotenv

# Configure logging first
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Try to load environment variables
try:
    load_dotenv()
    logger.info("Variables de entorno cargadas correctamente desde .env")
except Exception as e:
    logger.warning(
        f"No se pudo cargar el archivo .env: {e}. Usando valores predeterminados."
    )


def safe_get_env(
    key: str, default: Any = None, var_type: type = str, required: bool = False
) -> Any:
    try:
        value = os.getenv(key)

        if value is None or value.strip() == "":
            if required:
                logger.warning(
                    f"Variable requerida '{key}' no encontrada en .env. "
                    f"Usando valor por defecto: {default}"
                )
            return default

        # Conversión según el tipo
        if var_type is bool:
            return value.lower() in ("true", "1", "yes", "si", "sí")
        elif var_type is int:
            try:
                return int(value)
            except (ValueError, TypeError) as e:
                logger.error(
                    f"Error al convertir '{key}' a entero (valor: '{value}'): {e}. "
                    f"Usando valor por defecto: {default}"
                )
                return default
        elif var_type is float:
            try:
                return float(value)
            except (ValueError, TypeError) as e:
                logger.error(
                    f"Error al convertir '{key}' a float (valor: '{value}'): {e}. "
                    f"Usando valor por defecto: {default}"
                )
                return default
        else:
            return value.strip()

    except Exception as e:
        logger.error(
            f"Error inesperado al obtener variable '{key}': {e}. "
            f"Usando valor por defecto: {default}"
        )
        return default


def safe_get_list(key: str, default: list | None = None, separator: str = ",") -> list:
    if default is None:
        default = []

    try:
        value = os.getenv(key, "").strip()
        if not value:
            return default

        result = [item.strip() for item in value.split(separator) if item.strip()]
        return result if result else default

    except Exception as e:
        logger.error(
            f"Error al procesar lista desde '{key}': {e}. "
            f"Usando valor por defecto: {default}"
        )
        return default


class Config:

    # API Scheduler
    SCHEDULER_API_ENABLED = True

    # Security settings
    SECRET_KEY = safe_get_env("SECRET_KEY", os.urandom(24).hex())
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # CSRF tokens don't expire

    # Database settings
    DATABASE_URL = safe_get_env("DATABASE_URL", "sqlite:///squidstats.db")
    DATABASE_TYPE = safe_get_env("DATABASE_TYPE", "SQLITE").upper()
    DATABASE_STRING_CONNECTION = safe_get_env(
        "DATABASE_STRING_CONNECTION", "/opt/SquidStats/"
    )

    # Squid settings
    SQUID_LOG = safe_get_env("SQUID_LOG", "/var/log/squid/access.log")
    SQUID_CACHE_LOG = safe_get_env("SQUID_CACHE_LOG", "/var/log/squid/cache.log")
    SQUID_HOST = safe_get_env("SQUID_HOST", "127.0.0.1")
    SQUID_PORT = safe_get_env("SQUID_PORT", 3128, var_type=int)
    BLACKLIST_DOMAINS = safe_get_env("BLACKLIST_DOMAINS", "")

    # Flask settings
    DEBUG = safe_get_env("FLASK_DEBUG", False, var_type=bool)
    LISTEN_HOST = safe_get_env("LISTEN_HOST") or safe_get_env("FLASK_HOST") or "0.0.0.0"
    LISTEN_PORT = safe_get_env(
        "LISTEN_PORT", safe_get_env("FLASK_PORT", 5000, var_type=int), var_type=int
    )

    # Log parsing mode: 'DETAILED' (current behavior) or 'DEFAULT' (classic Squid format)
    LOG_FORMAT = safe_get_env("LOG_FORMAT", "DETAILED").upper()

    # Application version
    VERSION = safe_get_env("VERSION", "2.1")

    # Authentication settings
    JWT_SECRET_KEY = SECRET_KEY
    JWT_EXPIRY_HOURS = safe_get_env("JWT_EXPIRY_HOURS", 24, var_type=int)
    MAX_LOGIN_ATTEMPTS = safe_get_env("MAX_LOGIN_ATTEMPTS", 5, var_type=int)
    LOCKOUT_DURATION_MINUTES = safe_get_env(
        "LOCKOUT_DURATION_MINUTES", 15, var_type=int
    )
    FIRST_PASSWORD = safe_get_env("FIRST_PASSWORD", "")

    # Telegram Notifications
    TELEGRAM_ENABLED = safe_get_env("TELEGRAM_ENABLED", False, var_type=bool)
    TELEGRAM_API_ID = safe_get_env("TELEGRAM_API_ID", None)
    TELEGRAM_API_HASH = safe_get_env("TELEGRAM_API_HASH", None)
    TELEGRAM_BOT_TOKEN = safe_get_env("TELEGRAM_BOT_TOKEN", None)
    TELEGRAM_SESSION_NAME = safe_get_env("TELEGRAM_SESSION_NAME", "squidstats_bot")
    TELEGRAM_PHONE = safe_get_env("TELEGRAM_PHONE", None)
    TELEGRAM_RECIPIENTS = safe_get_list("TELEGRAM_RECIPIENTS", [])

    # Proxy settings
    HTTP_PROXY = safe_get_env("HTTP_PROXY", "")
    HTTPS_PROXY = safe_get_env("HTTPS_PROXY", "")
    NO_PROXY = safe_get_env("NO_PROXY", "")
