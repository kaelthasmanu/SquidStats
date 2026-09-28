"""Authenticates end users attempting to open a captive-portal session.

Delegates credential verification to the LDAP/AD directory already
configured for the deployment (``services/ldap``), since captive-portal
users are network users, not SquidStats admin accounts.
"""

from flask_babel import gettext as _

from services.ldap import ldap_config_service, ldap_service


def authenticate(username: str, password: str) -> tuple[bool, str]:
    """Return ``(True, username)`` on success or ``(False, error_message)``."""
    cfg = ldap_config_service.load_config()
    if not cfg.get("host"):
        return False, _("El portal cautivo requiere LDAP/AD configurado.")

    result = ldap_service.authenticate_user(cfg, username, password)
    if result.get("status") == "success":
        return True, result.get("username", username)
    return False, result.get("message", _("Usuario o contraseña incorrectos."))
