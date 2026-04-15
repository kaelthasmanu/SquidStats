"""Service layer for SSL Bump detection."""

from loguru import logger
from flask_babel import gettext as _


def get_ssl_bump_status(config_manager) -> dict:
    """Return SSL Bump detection results from *config_manager*.

    Wraps :meth:`SquidConfigManager.detect_ssl_bump` with error handling so
    callers always receive a well-formed dict.
    """
    try:
        return config_manager.detect_ssl_bump()
    except Exception:
        logger.exception("Error detecting SSL Bump status")
        return {
            "enabled": False,
            "mode": None,
            "cert": None,
            "generate_certs": False,
            "sslcrtd_configured": False,
            "sslcrtd_children": None,
            "http_port_entry": None,
            "ssl_bump_rules": [],
            "source": "main",
            "error": _("Error al detectar la configuración SSL Bump"),
        }
