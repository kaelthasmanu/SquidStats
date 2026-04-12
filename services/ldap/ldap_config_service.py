"""LDAP configuration persistence service.

Reads and writes LDAP/AD connection settings to the ``ldap_config`` database
table (single-row pattern, same as backup_config).
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from database.database import get_session
from database.models.models import LdapConfig


def _default_config() -> dict:
    return {
        "host": "",
        "port": 389,
        "use_ssl": False,
        "auth_type": "SIMPLE",
        "bind_dn": "",
        "bind_password": "",
        "base_dn": "",
    }


def load_config() -> dict:
    """Return LDAP config from the DB. Returns defaults if no row exists."""
    session = get_session()
    try:
        row = session.query(LdapConfig).first()
        if row is None:
            cfg = _default_config()
            print("[LDAP DEBUG] load_config: no config row found, returning defaults", cfg)
            return cfg

        cfg = {
            "host": row.host or "",
            "port": row.port or 389,
            "use_ssl": bool(row.use_ssl),
            "auth_type": row.auth_type or "SIMPLE",
            "bind_dn": row.bind_dn or "",
            "bind_password": row.bind_password or "",
            "base_dn": row.base_dn or "",
        }
        print(f"[LDAP DEBUG] load_config: loaded row id={row.id} config={cfg}")
        return cfg
    except Exception as exc:
        logger.warning(f"Could not read ldap_config from DB, using defaults: {exc}")
        print(f"[LDAP DEBUG] load_config: exception reading config -> {exc}")
        return _default_config()
    finally:
        session.close()


def save_config(cfg: dict) -> None:
    """Upsert LDAP configuration into the database (single-row table)."""
    session = get_session()
    try:
        print(f"[LDAP DEBUG] save_config: incoming cfg={cfg}")
        row = session.query(LdapConfig).first()
        if row is None:
            row = LdapConfig(created_at=datetime.now())
            session.add(row)

        row.host = cfg.get("host", "")
        row.port = int(cfg.get("port", 389) or 389)
        row.use_ssl = 1 if cfg.get("use_ssl") else 0
        row.auth_type = cfg.get("auth_type", "SIMPLE")
        row.bind_dn = cfg.get("bind_dn", "")
        row.base_dn = cfg.get("base_dn", "")
        row.updated_at = datetime.now()

        # Only overwrite the password if a non-empty value is supplied
        new_password = cfg.get("bind_password", "")
        if new_password:
            row.bind_password = new_password

        session.commit()
        print(f"[LDAP DEBUG] save_config: saved row id={row.id} host={row.host} port={row.port} use_ssl={row.use_ssl} auth_type={row.auth_type} base_dn={row.base_dn}")
    except Exception as exc:
        session.rollback()
        logger.error(f"Error saving ldap_config to DB: {exc}")
        print(f"[LDAP DEBUG] save_config: exception -> {exc}")
        raise
    finally:
        session.close()
