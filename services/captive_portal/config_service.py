"""Captive portal settings stored in the single-row ``captive_portal_config`` table."""

from loguru import logger

from database.database import get_session
from database.models.models import CaptivePortalConfig

DEFAULTS = {
    "enabled": 0,
    "portal_title": "SquidStats Portal",
    "portal_public_url": "",
    "session_ttl_minutes": 480,
    "acl_ttl_seconds": 60,
    "acl_negative_ttl_seconds": 0,
}


def get_config() -> dict:
    """Return the captive portal settings, creating the default row if missing."""
    session = get_session()
    try:
        row = session.query(CaptivePortalConfig).first()
        if row is None:
            row = CaptivePortalConfig(**DEFAULTS)
            session.add(row)
            session.commit()
        return {
            "enabled": bool(row.enabled),
            "portal_title": row.portal_title,
            "portal_public_url": row.portal_public_url,
            "session_ttl_minutes": row.session_ttl_minutes,
            "acl_ttl_seconds": row.acl_ttl_seconds,
            "acl_negative_ttl_seconds": row.acl_negative_ttl_seconds,
        }
    finally:
        session.close()


def update_config(**fields) -> dict:
    """Persist the provided fields on the settings row and return the new state."""
    session = get_session()
    try:
        row = session.query(CaptivePortalConfig).first()
        if row is None:
            row = CaptivePortalConfig(**DEFAULTS)
            session.add(row)

        for key in DEFAULTS:
            if key in fields and fields[key] is not None:
                setattr(row, key, fields[key])

        try:
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Error saving captive portal configuration")
            raise
        return get_config()
    finally:
        session.close()


def is_enabled() -> bool:
    return get_config()["enabled"]
