"""Lifecycle management for captive-portal sessions (IP -> authenticated user).

Sessions are consulted directly by the external ACL helper
(``services/captive_portal/helper/captive_portal_helper.py``) that Squid
invokes via ``external_acl_type``.
"""

import ipaddress
from datetime import datetime, timedelta

from flask_babel import gettext as _
from loguru import logger

from database.database import get_session
from database.models.models import CaptivePortalSession
from services.captive_portal.config_service import is_enabled


def _validate_ip(ip: str) -> bool:
    if not ip or len(ip) > 45:
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def create_session(ip: str, username: str, ttl_minutes: int) -> tuple[bool, str]:
    """Create or renew an active session for *ip*."""
    if not _validate_ip(ip):
        return False, _("Dirección IP inválida")

    now = datetime.now()
    expires_at = now + timedelta(minutes=max(1, ttl_minutes))

    session = get_session()
    try:
        record = session.query(CaptivePortalSession).filter_by(ip=ip).first()
        if record is None:
            record = CaptivePortalSession(ip=ip, username=username)
            session.add(record)
        record.username = username
        record.active = 1
        record.expires_at = expires_at
        session.commit()
        return True, _("Sesión activa para %s (%s)") % (username, ip)
    except Exception:
        session.rollback()
        logger.exception("Error creating captive portal session for %s", ip)
        return False, _("Error al guardar la sesión")
    finally:
        session.close()


def get_active_session(ip: str) -> dict | None:
    """Return the active, non-expired session for *ip*, if any."""
    if not is_enabled() or not _validate_ip(ip):
        return None

    session = get_session()
    try:
        record = (
            session.query(CaptivePortalSession)
            .filter_by(ip=ip, active=1)
            .first()
        )
        if record is None or record.expires_at <= datetime.now():
            return None
        return {
            "ip": record.ip,
            "username": record.username,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
        }
    finally:
        session.close()


def revoke_session(ip: str) -> tuple[bool, str]:
    """Deactivate the session for *ip*."""
    if not _validate_ip(ip):
        return False, _("Dirección IP inválida")

    session = get_session()
    try:
        record = session.query(CaptivePortalSession).filter_by(ip=ip, active=1).first()
        if record is None:
            return False, _("No hay sesión activa para %s") % ip
        record.active = 0
        session.commit()
        return True, _("Sesión revocada para %s") % ip
    except Exception:
        session.rollback()
        logger.exception("Error revoking captive portal session for %s", ip)
        return False, _("Error al revocar la sesión")
    finally:
        session.close()


def list_active_sessions() -> list[dict]:
    """Return all active, non-expired sessions ordered by most recent."""
    session = get_session()
    try:
        rows = (
            session.query(CaptivePortalSession)
            .filter(CaptivePortalSession.active == 1)
            .filter(CaptivePortalSession.expires_at > datetime.now())
            .order_by(CaptivePortalSession.created_at.desc())
            .all()
        )
        return [
            {
                "ip": r.ip,
                "username": r.username,
                "created_at": r.created_at,
                "expires_at": r.expires_at,
            }
            for r in rows
        ]
    finally:
        session.close()


def cleanup_expired_sessions() -> int:
    """Deactivate all sessions past their expiry. Returns the number affected."""
    session = get_session()
    try:
        rows = (
            session.query(CaptivePortalSession)
            .filter(CaptivePortalSession.active == 1)
            .filter(CaptivePortalSession.expires_at <= datetime.now())
            .all()
        )
        for r in rows:
            r.active = 0
        session.commit()
        return len(rows)
    except Exception:
        session.rollback()
        logger.exception("Error cleaning up expired captive portal sessions")
        return 0
    finally:
        session.close()
