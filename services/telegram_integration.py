"""
Telegram Integration Wrapper
Integrates Telegram notifications with the existing notification system
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Any

from loguru import logger

from config import Config
from services.telegram_service import (
    NotificationPriority,
    TelegramService,
    get_telegram_service,
    parse_http_proxy_url,
)

# Thread pool for async execution
_executor = ThreadPoolExecutor(max_workers=2)
_telegram_service: TelegramService | None = None


def run_async(coro):
    """
    Run an async coroutine in a new event loop
    Helper for calling async functions from sync code
    Always creates a new event loop in the current thread
    """
    # Always create a new event loop for the thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            # Cancel all remaining tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            # Run loop until all tasks are cancelled
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        finally:
            loop.close()


def async_to_sync(async_func: Callable) -> Callable:
    """
    Decorator to convert async function to sync
    Runs async function in thread pool to avoid blocking
    """

    @wraps(async_func)
    def wrapper(*args, **kwargs):
        # Execute in thread pool with a new event loop
        future = _executor.submit(run_async, async_func(*args, **kwargs))
        return future.result(timeout=60)

    return wrapper


def initialize_telegram_service() -> bool:
    """
    Initialize Telegram service with config

    Returns:
        True if initialized successfully
    """
    global _telegram_service

    if not Config.TELEGRAM_ENABLED:
        logger.info("Telegram notifications disabled in config")
        return False

    if not Config.TELEGRAM_API_ID or not Config.TELEGRAM_API_HASH:
        logger.warning(
            "Telegram API credentials not configured. "
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in environment."
        )
        return False

    try:
        api_id = int(Config.TELEGRAM_API_ID)

        # Configure proxy if available
        proxy_config = None
        if Config.HTTP_PROXY:
            proxy_config = parse_http_proxy_url(Config.HTTP_PROXY)
            if proxy_config:
                logger.info(f"Using HTTP proxy: {Config.HTTP_PROXY}")
            else:
                logger.warning(f"Invalid proxy URL: {Config.HTTP_PROXY}")

        _telegram_service = get_telegram_service(
            api_id=api_id,
            api_hash=Config.TELEGRAM_API_HASH,
            bot_token=Config.TELEGRAM_BOT_TOKEN,
            session_name=Config.TELEGRAM_SESSION_NAME,
            phone=Config.TELEGRAM_PHONE,
            enabled=Config.TELEGRAM_ENABLED,
            proxy=proxy_config,
        )

        logger.info("Telegram service initialized successfully")
        return True

    except ValueError as e:
        logger.error(f"Invalid Telegram API ID: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to initialize Telegram service: {e}")
        return False


def map_notification_type_to_priority(notification_type: str) -> NotificationPriority:
    """
    Map notification type to Telegram priority

    Args:
        notification_type: Notification type from the system

    Returns:
        NotificationPriority enum value
    """
    mapping = {
        "error": NotificationPriority.CRITICAL,
        "warning": NotificationPriority.HIGH,
        "success": NotificationPriority.NORMAL,
        "info": NotificationPriority.LOW,
    }

    return mapping.get(notification_type.lower(), NotificationPriority.NORMAL)


def map_source_to_emoji(source: str) -> str:
    """
    Map notification source to emoji

    Args:
        source: Notification source

    Returns:
        Emoji string
    """
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


@async_to_sync
async def send_telegram_notification(
    notification_type: str,
    message: str,
    source: str = "system",
    extra_data: dict[str, Any] | None = None,
) -> bool:
    """
    Send notification to all configured Telegram recipients

    Args:
        notification_type: Type of notification ('info', 'warning', 'error', 'success')
        message: Notification message
        source: Source of the notification
        extra_data: Additional data to include

    Returns:
        True if sent to at least one recipient
    """
    if not _telegram_service or not Config.TELEGRAM_ENABLED:
        return False

    if not Config.TELEGRAM_RECIPIENTS:
        logger.debug("No Telegram recipients configured")
        return False

    # Filter empty recipients
    recipients = [r.strip() for r in Config.TELEGRAM_RECIPIENTS if r.strip()]

    if not recipients:
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

        success_count = sum(1 for success in results.values() if success)

        if success_count > 0:
            logger.info(
                f"Telegram notification sent to {success_count}/{len(recipients)} recipients"
            )
            return True
        else:
            logger.warning("Failed to send Telegram notification to any recipient")
            return False

    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
        return False


@async_to_sync
async def send_security_alert_telegram(
    alert_type: str, details: dict[str, Any]
) -> bool:
    """
    Send security alert to Telegram

    Args:
        alert_type: Type of security alert
        details: Alert details

    Returns:
        True if sent successfully
    """
    if not _telegram_service or not Config.TELEGRAM_RECIPIENTS:
        return False

    recipients = [r.strip() for r in Config.TELEGRAM_RECIPIENTS if r.strip()]
    success_count = 0

    for recipient in recipients:
        try:
            success = await _telegram_service.send_security_alert(
                recipient, alert_type, details
            )
            if success:
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to send security alert to {recipient}: {e}")

    return success_count > 0


@async_to_sync
async def send_system_alert_telegram(
    alert_message: str, metrics: dict[str, Any] | None = None
) -> bool:
    """
    Send system alert to Telegram

    Args:
        alert_message: Alert message
        metrics: System metrics

    Returns:
        True if sent successfully
    """
    if not _telegram_service or not Config.TELEGRAM_RECIPIENTS:
        return False

    recipients = [r.strip() for r in Config.TELEGRAM_RECIPIENTS if r.strip()]
    success_count = 0

    for recipient in recipients:
        try:
            success = await _telegram_service.send_system_alert(
                recipient, alert_message, metrics
            )
            if success:
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to send system alert to {recipient}: {e}")

    return success_count > 0


@async_to_sync
async def send_user_activity_alert_telegram(
    username: str, activity_data: dict[str, Any]
) -> bool:
    """
    Send user activity alert to Telegram

    Args:
        username: Username with high activity
        activity_data: Activity details

    Returns:
        True if sent successfully
    """
    if not _telegram_service or not Config.TELEGRAM_RECIPIENTS:
        return False

    recipients = [r.strip() for r in Config.TELEGRAM_RECIPIENTS if r.strip()]
    success_count = 0

    for recipient in recipients:
        try:
            success = await _telegram_service.send_user_activity_alert(
                recipient, username, activity_data
            )
            if success:
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to send user activity alert to {recipient}: {e}")

    return success_count > 0


@async_to_sync
async def telegram_health_check() -> dict[str, Any]:
    """
    Check Telegram service health

    Returns:
        Health status dictionary
    """
    if not _telegram_service:
        return {
            "enabled": Config.TELEGRAM_ENABLED,
            "initialized": False,
            "connected": False,
        }

    try:
        health = await _telegram_service.health_check()
        return health
    except Exception as e:
        logger.error(f"Telegram health check failed: {e}")
        return {
            "enabled": Config.TELEGRAM_ENABLED,
            "initialized": True,
            "connected": False,
            "error": str(e),
        }


def cleanup_telegram() -> None:
    """Cleanup Telegram service on shutdown"""
    global _telegram_service

    if _telegram_service:
        try:
            run_async(_telegram_service.disconnect())
            logger.info("Telegram service disconnected")
        except Exception as e:
            logger.error(f"Error during Telegram cleanup: {e}")
        finally:
            _telegram_service = None

    _executor.shutdown(wait=True)
