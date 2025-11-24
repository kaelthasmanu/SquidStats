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

    # Squid settings
    SQUID_LOG = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
    BLACKLIST_DOMAINS = os.getenv("BLACKLIST_DOMAINS", "")

    # Flask settings
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Log parsing mode: 'DETAILED' (current behavior) or 'DEFAULT' (classic Squid format)
    LOG_FORMAT = os.getenv("LOG_FORMAT", "DETAILED").upper()
