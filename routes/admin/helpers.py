"""
Shared helpers for admin route modules.

Centralizes repetitive patterns: flash+redirect, debug detection,
form field parsing, JSON error responses, and config_manager access.
"""

from flask import current_app, flash, jsonify, redirect, request, url_for
from loguru import logger

from utils.admin import SquidConfigManager


# ---------------------------------------------------------------------------
# Config manager accessor (replaces global mutable)
# ---------------------------------------------------------------------------

def get_config_manager() -> SquidConfigManager:
    """Return the shared :class:`SquidConfigManager` instance.

    Stored on ``current_app`` so it lives for the app's lifetime without
    needing a module-level mutable global.
    """
    cm = getattr(current_app, "_squid_config_manager", None)
    if cm is None:
        cm = SquidConfigManager()
        current_app._squid_config_manager = cm
    return cm


def reload_config_manager() -> SquidConfigManager:
    """Force-reload the :class:`SquidConfigManager` (e.g. after split)."""
    cm = SquidConfigManager()
    current_app._squid_config_manager = cm
    logger.info("Config manager reloaded")
    return cm


# ---------------------------------------------------------------------------
# Flash + Redirect helper
# ---------------------------------------------------------------------------

def flash_and_redirect(success: bool, message: str, endpoint: str, **kwargs):
    """Flash a message and redirect to *endpoint* in a single call."""
    flash(message, "success" if success else "error")
    return redirect(url_for(endpoint, **kwargs))


# ---------------------------------------------------------------------------
# Debug mode helper
# ---------------------------------------------------------------------------

def is_debug() -> bool:
    """Return ``True`` when the Flask app is running in debug mode.

    Safely handles the case where no application context is active.
    """
    try:
        return bool(current_app.debug)
    except RuntimeError:
        return False


# ---------------------------------------------------------------------------
# Form field parsing helpers
# ---------------------------------------------------------------------------

def get_int_form_field(name: str) -> int | None:
    """Parse an integer from ``request.form[name]``.

    Returns ``None`` when the value is missing or not a valid integer.
    """
    try:
        return int(request.form.get(name))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# JSON error response helpers
# ---------------------------------------------------------------------------

def json_error(message: str, status_code: int = 400, *, details: str | None = None):
    """Build a standard JSON error response.

    When the app is in debug mode and *details* is provided, the details
    are included in the payload.
    """
    resp = {"status": "error", "message": message}
    if is_debug() and details:
        resp["details"] = details
    return jsonify(resp), status_code


def json_success(message: str, *, extra: dict | None = None):
    """Build a standard JSON success response."""
    resp = {"status": "success", "message": message}
    if extra:
        resp.update(extra)
    return jsonify(resp)


# ---------------------------------------------------------------------------
# Flash error with debug details
# ---------------------------------------------------------------------------

def flash_error_with_details(
    user_message: str, exception: Exception | None = None
):
    """Flash an error message; include exception details in debug mode."""
    if is_debug() and exception is not None:
        flash(f"{user_message}: {exception}", "error")
    else:
        flash(user_message, "error")
