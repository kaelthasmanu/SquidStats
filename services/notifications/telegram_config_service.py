"""Telegram configuration persistence service.

Reads and writes Telegram notification settings to the ``telegram_config``
database table (single-row pattern, same as backup_config and ldap_config).

Sensitive fields (api_hash, bot_token) are encrypted at rest using Fernet
symmetric encryption. The encryption key is stored alongside the row and
is derived from a randomly-generated secret on first save.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from database.database import get_session
from database.models.models import TelegramConfig

_SENSITIVE_FIELDS = ("api_hash", "bot_token")
_SECRET_PLACEHOLDER = "".join(chr(8226) for _ in range(8))


def _default_config() -> dict:
    return {
        "enabled": False,
        "api_id": "",
        "api_hash": "",
        "bot_token": "",
        "phone": "",
        "session_name": "squidstats_bot",
        "recipients": [],
    }


def _get_fernet(raw_key: str | None) -> Fernet:
    if not raw_key:
        raise RuntimeError("No encryption key available")
    key_bytes = raw_key.encode() if isinstance(raw_key, str) else raw_key
    if len(key_bytes) != 44:
        key_bytes = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
    return Fernet(key_bytes)


def _generate_encryption_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _encrypt(value: str, encryption_key: str) -> str:
    if not value:
        return ""
    cipher = _get_fernet(encryption_key)
    return cipher.encrypt(value.encode()).decode()


def _decrypt(encrypted: str, encryption_key: str) -> str:
    if not encrypted:
        return ""
    try:
        cipher = _get_fernet(encryption_key)
        return cipher.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        logger.warning(
            "telegram_config: could not decrypt field, returning empty string"
        )
        return ""


def _recipients_to_list(raw: str) -> list[str]:
    """Convert comma-separated recipients string to a clean list."""
    if not raw:
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


def _recipients_to_str(recipients: list[str] | str) -> str:
    """Normalise recipients to a comma-separated string for storage."""
    if isinstance(recipients, list):
        return ",".join(r.strip() for r in recipients if r.strip())
    return recipients or ""


def load_config() -> dict:
    """Return Telegram config from the DB. Returns defaults if no row exists."""
    session = get_session()
    try:
        row = session.query(TelegramConfig).first()
        if row is None:
            return _default_config()

        api_hash = row.api_hash or ""
        bot_token = row.bot_token or ""

        if row.encryption_key:
            api_hash = _decrypt(api_hash, row.encryption_key)
            bot_token = _decrypt(bot_token, row.encryption_key)

        return {
            "enabled": bool(row.enabled),
            "api_id": row.api_id or "",
            "api_hash": api_hash,
            "bot_token": bot_token,
            "phone": row.phone or "",
            "session_name": row.session_name or "squidstats_bot",
            "recipients": _recipients_to_list(row.recipients or ""),
        }
    except Exception as exc:
        logger.warning(f"Could not read telegram_config from DB, using defaults: {exc}")
        return _default_config()
    finally:
        session.close()


def save_config(data: dict) -> None:
    """Persist Telegram configuration to the DB."""
    session = get_session()
    try:
        row = session.query(TelegramConfig).first()

        if row is None:
            row = TelegramConfig(created_at=datetime.now())
            session.add(row)

        # Ensure an encryption key exists
        if not row.encryption_key:
            row.encryption_key = _generate_encryption_key()

        row.enabled = 1 if data.get("enabled") else 0
        row.api_id = str(data.get("api_id") or "").strip()
        row.phone = str(data.get("phone") or "").strip()
        row.session_name = (
            str(data.get("session_name") or "squidstats_bot").strip()
            or "squidstats_bot"
        )
        row.recipients = _recipients_to_str(data.get("recipients", []))
        row.updated_at = datetime.now()

        # Encrypt sensitive fields only when a non-empty value is provided.
        # An empty string means "leave unchanged" (placeholder masking in the UI).
        new_api_hash = str(data.get("api_hash") or "").strip()
        if new_api_hash and new_api_hash != _SECRET_PLACEHOLDER:
            row.api_hash = _encrypt(new_api_hash, row.encryption_key)

        new_bot_token = str(data.get("bot_token") or "").strip()
        if new_bot_token and new_bot_token != _SECRET_PLACEHOLDER:
            row.bot_token = _encrypt(new_bot_token, row.encryption_key)

        session.commit()
        logger.info("Telegram configuration saved to DB")
    except Exception as exc:
        session.rollback()
        logger.error(f"Error saving telegram_config: {exc}")
        raise
    finally:
        session.close()
