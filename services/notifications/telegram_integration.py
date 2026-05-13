"""
Telegram Integration Wrapper
Integrates Telegram notifications with the existing notification system.
All configuration is loaded from the database via telegram_config_service.
"""

import asyncio
import threading
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from loguru import logger

from config import Config
from services.notifications.telegram_config_service import (
    load_config as load_telegram_config,
)
from services.notifications.telegram_service import (
    NotificationPriority,
    TelegramService,
    parse_http_proxy_url,
)

# ---------------------------------------------------------------------------
# Single persistent background event loop
# ---------------------------------------------------------------------------
# All Telegram async operations run on this one loop, which lives in its own
# daemon thread for the entire lifetime of the process.  Using a dedicated
# loop eliminates the "event loop must not change after connection" error that
# Telethon raises when callers create a fresh loop per request, and it
# guarantees the Telethon SQLiteSession is only ever touched from one thread,
# preventing "database is locked" conflicts.
# ---------------------------------------------------------------------------

_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_thread: threading.Thread | None = None
_bg_lock = threading.Lock()

_telegram_service: TelegramService | None = None


def _start_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _get_background_loop() -> asyncio.AbstractEventLoop:
    """Return the shared background event loop, starting it on first call."""
    global _bg_loop, _bg_thread

    if _bg_loop is not None and _bg_loop.is_running():
        return _bg_loop

    with _bg_lock:
        # Double-check after acquiring the lock.
        if _bg_loop is not None and _bg_loop.is_running():
            return _bg_loop

        _bg_loop = asyncio.new_event_loop()
        _bg_thread = threading.Thread(
            target=_start_background_loop,
            args=(_bg_loop,),
            daemon=True,
            name="telegram-event-loop",
        )
        _bg_thread.start()

        # Wait until the loop is actually running.
        deadline = time.monotonic() + 5.0
        while not _bg_loop.is_running():
            if time.monotonic() > deadline:
                raise RuntimeError("Telegram background event loop did not start in time")
            time.sleep(0.01)

        logger.debug("Telegram background event loop started (thread: telegram-event-loop)")
        return _bg_loop


def run_async(coro, timeout: float = 60) -> Any:
    """
    Submit *coro* to the shared Telegram background event loop and block the
    calling thread until the result is available (or *timeout* seconds elapse).

    Using the same loop for every call ensures Telethon never sees its
    internal asyncio state created on a different loop.
    """
    loop = _get_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def async_to_sync(async_func: Callable) -> Callable:
    """Decorator that runs an async function on the shared Telegram loop."""

    @wraps(async_func)
    def wrapper(*args, **kwargs):
        return run_async(async_func(*args, **kwargs))

    return wrapper



def initialize_telegram_service() -> bool:
    """
    Initialize or reinitialize the Telegram service from DB configuration.

    Returns:
        True if the service was initialized successfully.
    """
    global _telegram_service

    cfg = load_telegram_config()

    if not cfg.get("enabled"):
        logger.info("Telegram notifications disabled in configuration")
        return False

    api_id_raw = cfg.get("api_id", "")
    api_hash = cfg.get("api_hash", "")

    if not api_id_raw or not api_hash:
        logger.warning(
            "Telegram API credentials not configured. "
            "Set them via the admin panel → Telegram Configuration."
        )
        return False

    try:
        api_id = int(api_id_raw)
    except (ValueError, TypeError):
        logger.error(f"Invalid Telegram API ID (not an integer): {api_id_raw!r}")
        return False

    try:
        proxy_config = None
        if Config.HTTP_PROXY:
            proxy_config = parse_http_proxy_url(Config.HTTP_PROXY)
            if proxy_config:
                logger.info(f"Using HTTP proxy for Telegram: {Config.HTTP_PROXY}")
            else:
                logger.warning(f"Invalid proxy URL for Telegram: {Config.HTTP_PROXY}")

        # Reset the singleton so a fresh instance picks up new credentials.
        TelegramService._instance = None

        _telegram_service = TelegramService(
            api_id=api_id,
            api_hash=api_hash,
            bot_token=cfg.get("bot_token") or None,
            session_name=cfg.get("session_name") or "squidstats_bot",
            phone=cfg.get("phone") or None,
            enabled=True,
            proxy=proxy_config,
        )

        logger.info("Telegram service initialized successfully from DB configuration")
        return True

    except Exception as e:
        logger.error(f"Failed to initialize Telegram service: {e}")
        return False


def cleanup_telegram() -> None:
    """Cleanup Telegram service on application shutdown."""
    global _telegram_service

    if _telegram_service:
        try:
            run_async(_telegram_service.disconnect())
        except Exception as e:
            logger.debug("Error disconnecting Telegram service: %s", e)
        _telegram_service = None
        logger.info("Telegram service cleaned up")


def map_notification_type_to_priority(notification_type: str) -> NotificationPriority:
    """Map internal notification type to Telegram message priority."""
    mapping = {
        "error": NotificationPriority.CRITICAL,
        "warning": NotificationPriority.HIGH,
        "success": NotificationPriority.NORMAL,
        "info": NotificationPriority.LOW,
    }
    return mapping.get(notification_type.lower(), NotificationPriority.NORMAL)


def map_source_to_emoji(source: str) -> str:
    """Map notification source to a representative emoji."""
    mapping = {
        "security": "🔒",
        "system": "💻",
        "squid": "🦑",
        "users": "👥",
        "git": "📦",
        "database": "🗄️",
        "network": "🌐",
    }
    return mapping.get(source.lower(), "📢")


def _get_recipients() -> list[str]:
    """Load recipients list from DB configuration."""
    cfg = load_telegram_config()
    return [r.strip() for r in cfg.get("recipients", []) if r.strip()]


@async_to_sync
async def send_telegram_notification(
    notification_type: str,
    message: str,
    source: str = "system",
    extra_data: dict[str, Any] | None = None,
) -> bool:
    """
    Send a notification to all configured Telegram recipients.

    Args:
        notification_type: One of 'info', 'warning', 'error', 'success'.
        message: Notification body.
        source: Origin label shown in the message header.
        extra_data: Optional key/value dict appended to the message.

    Returns:
        True if the message was delivered to at least one recipient.
    """
    if _telegram_service is None:
        return False

    cfg = load_telegram_config()
    if not cfg.get("enabled"):
        return False

    recipients = [r.strip() for r in cfg.get("recipients", []) if r.strip()]
    if not recipients:
        logger.debug("No Telegram recipients configured")
        return False

    priority = map_notification_type_to_priority(notification_type)
    emoji = map_source_to_emoji(source)
    source_display = f"{emoji} {source.title()}"

    try:
        results = await _telegram_service.send_bulk_notifications(
            recipients=recipients,
            message=message,
            priority=priority,
            source=source_display,
            extra_data=extra_data,
        )

        success_count = sum(1 for ok in results.values() if ok)

        if success_count > 0:
            logger.info(
                f"Telegram notification sent to {success_count}/{len(recipients)} recipients"
            )
            return True

        logger.warning("Failed to send Telegram notification to any recipient")
        return False

    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
        return False


@async_to_sync
async def send_security_alert_telegram(
    alert_type: str, details: dict[str, Any]
) -> bool:
    """Send a security alert to all configured Telegram recipients."""
    if _telegram_service is None:
        return False

    recipients = _get_recipients()
    success_count = 0

    for recipient in recipients:
        try:
            if await _telegram_service.send_security_alert(
                recipient, alert_type, details
            ):
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to send security alert to {recipient}: {e}")

    return success_count > 0


@async_to_sync
async def send_system_alert_telegram(
    alert_message: str, metrics: dict[str, Any] | None = None
) -> bool:
    """Send a system alert to all configured Telegram recipients."""
    if _telegram_service is None:
        return False

    recipients = _get_recipients()
    success_count = 0

    for recipient in recipients:
        try:
            if await _telegram_service.send_system_alert(
                recipient, alert_message, metrics
            ):
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to send system alert to {recipient}: {e}")

    return success_count > 0


@async_to_sync
async def send_user_activity_alert_telegram(
    username: str, activity_data: dict[str, Any]
) -> bool:
    """Send a user activity alert to all configured Telegram recipients."""
    if _telegram_service is None:
        return False

    recipients = _get_recipients()
    success_count = 0

    for recipient in recipients:
        try:
            if await _telegram_service.send_user_activity_alert(
                recipient, username, activity_data
            ):
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to send user activity alert to {recipient}: {e}")

    return success_count > 0


def telegram_health_check() -> dict:
    """Return a health-check dict for the running Telegram service."""
    if _telegram_service is None:
        cfg = load_telegram_config()
        return {
            "enabled": cfg.get("enabled", False),
            "connected": False,
            "bot_mode": False,
            "session": cfg.get("session_name", ""),
        }
    return run_async(_telegram_service.health_check())
