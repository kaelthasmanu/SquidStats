import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, Optional
from urllib.parse import urlparse

from loguru import logger
from telethon import TelegramClient, errors
from telethon.tl.types import InputPeerUser, User


def parse_http_proxy_url(proxy_url: str) -> dict[str, Any] | None:
    """
    Convert HTTP proxy URL to Telethon proxy dict

    Args:
        proxy_url: HTTP proxy URL (http://user:pass@host:port or http://host:port)

    Returns:
        Dict compatible with Telethon proxy format, or None if invalid

    Example:
        "http://proxy.example.com:8080" -> {
            "proxy_type": "http",
            "addr": "proxy.example.com",
            "port": 8080
        }

        "http://user:pass@proxy.example.com:8080" -> {
            "proxy_type": "http",
            "addr": "proxy.example.com",
            "port": 8080,
            "username": "user",
            "password": "pass"
        }
    """
    if not proxy_url or not proxy_url.strip():
        return None

    try:
        parsed = urlparse(proxy_url.strip())

        # Only accept HTTP proxies
        if parsed.scheme.lower() != "http":
            logger.warning(f"Unsupported proxy scheme '{parsed.scheme}': {proxy_url}")
            return None

        if not parsed.hostname or not parsed.port:
            logger.warning(f"Invalid proxy URL format: {proxy_url}")
            return None

        proxy_dict = {
            "proxy_type": "http",
            "addr": parsed.hostname,
            "port": parsed.port,
        }

        # Add authentication if present
        if parsed.username:
            proxy_dict["username"] = parsed.username
        if parsed.password:
            proxy_dict["password"] = parsed.password

        logger.debug(f"Parsed proxy: {proxy_dict}")
        return proxy_dict

    except Exception as e:
        logger.error(f"Failed to parse proxy URL '{proxy_url}': {e}")
        return None


class NotificationPriority(Enum):
    LOW = "🔵"
    NORMAL = "ℹ️"
    HIGH = "⚠️"
    CRITICAL = "🚨"


class TelegramNotificationError(Exception):
    """Base exception for Telegram notification errors"""

    pass


class TelegramConnectionError(TelegramNotificationError):
    """Raised when connection to Telegram fails"""

    pass


class TelegramSendError(TelegramNotificationError):
    """Raised when sending message fails"""

    pass


def async_retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except (errors.FloodWaitError, errors.SlowModeWaitError) as e:
                    wait_time = e.seconds if hasattr(e, "seconds") else current_delay
                    logger.warning(
                        f"Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_attempts})"
                    )
                    await asyncio.sleep(wait_time)
                    last_exception = e
                except Exception as e:
                    logger.warning(
                        f"Error on attempt {attempt + 1}/{max_attempts}: {e}"
                    )
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    last_exception = e
                    break

            raise TelegramSendError(
                f"Failed after {max_attempts} attempts"
            ) from last_exception

        return wrapper

    return decorator


class TelegramService:
    _instance: Optional["TelegramService"] = None
    _lock = asyncio.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        bot_token: str | None = None,
        session_name: str = "squidstats_bot",
        phone: str | None = None,
        enabled: bool = True,
        proxy: dict[str, Any] | None = None,
    ):
        if self._initialized:
            return

        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.session_name = session_name
        self.phone = phone
        self.enabled = enabled
        self.proxy = proxy

        self._client: TelegramClient | None = None
        self._connected = False
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._recipients: dict[str, InputPeerUser] = {}

        self._initialized = True
        logger.info("TelegramService initialized")

    async def _ensure_connected(self) -> None:
        """Ensure client is connected, connect if necessary"""
        if not self.enabled:
            raise TelegramNotificationError("Telegram notifications are disabled")

        if self._client and self._connected:
            try:
                await self._client.get_me()
                return
            except Exception as e:
                logger.warning(f"Connection check failed: {e}")
                self._connected = False

        await self.connect()

    async def connect(self) -> None:
        """Establish connection to Telegram"""
        if not self.enabled:
            logger.info("Telegram notifications disabled, skipping connection")
            return

        async with self._lock:
            try:
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass

                self._client = TelegramClient(
                    self.session_name, self.api_id, self.api_hash, proxy=self.proxy
                )

                await self._client.connect()

                if self.bot_token:
                    # Bot mode
                    await self._client.sign_in(bot_token=self.bot_token)
                    logger.info("Connected to Telegram as bot")
                elif self.phone:
                    # User mode
                    if not await self._client.is_user_authorized():
                        await self._client.send_code_request(self.phone)
                        logger.warning(
                            "Authorization required. Check your Telegram for code."
                        )
                    else:
                        logger.info("Connected to Telegram as user")
                else:
                    # Try to use existing session
                    if not await self._client.is_user_authorized():
                        raise TelegramConnectionError(
                            "No bot_token or phone provided and no valid session exists"
                        )
                    logger.info("Connected using existing session")

                self._connected = True

            except errors.ApiIdInvalidError:
                raise TelegramConnectionError("Invalid API ID or Hash")
            except errors.PhoneNumberInvalidError:
                raise TelegramConnectionError("Invalid phone number")
            except Exception as e:
                self._connected = False
                raise TelegramConnectionError(f"Failed to connect: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from Telegram"""
        if self._client:
            try:
                await self._client.disconnect()
                self._connected = False
                logger.info("Disconnected from Telegram")
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")

    @asynccontextmanager
    async def session(self):
        """Context manager for Telegram session"""
        await self._ensure_connected()
        try:
            yield self._client
        except Exception as e:
            logger.error(f"Error in Telegram session: {e}")
            raise

    def _format_message(
        self,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        source: str = "SquidStats",
        timestamp: bool = True,
        extra_data: dict[str, Any] | None = None,
    ) -> str:
        parts = [f"{priority.value} **{source}**\n"]

        if timestamp:
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            parts.append(f"🕐 {time_str}\n")

        parts.append(f"\n{message}")

        if extra_data:
            parts.append("\n\n📊 **Detalles:**")
            for key, value in extra_data.items():
                parts.append(f"\n• {key}: `{value}`")

        return "".join(parts)

    async def _resolve_recipient(self, recipient: str | int) -> InputPeerUser | int:
        if isinstance(recipient, int):
            return recipient

        # Check cache
        if recipient in self._recipients:
            return self._recipients[recipient]

        # Resolve entity
        try:
            async with self.session() as client:
                # Convert channel IDs to int for better resolution
                resolve_target = recipient
                if isinstance(recipient, str) and recipient.startswith("-100"):
                    resolve_target = int(recipient)

                entity = await client.get_entity(resolve_target)
                if isinstance(entity, User):
                    self._recipients[recipient] = entity
                return entity
        except Exception as e:
            logger.error(f"Failed to resolve recipient {recipient}: {e}")
            raise TelegramSendError(f"Invalid recipient: {recipient}") from e

    @async_retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def send_notification(
        self,
        recipient: str | int,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        source: str = "SquidStats",
        parse_mode: str = "md",
        **kwargs,
    ) -> bool:
        if not self.enabled:
            logger.debug("Telegram notifications disabled")
            return False

        try:
            formatted_message = self._format_message(
                message, priority=priority, source=source, **kwargs
            )

            entity = await self._resolve_recipient(recipient)

            async with self.session() as client:
                await client.send_message(
                    entity, formatted_message, parse_mode=parse_mode
                )

            logger.info(f"Notification sent to {recipient}")
            return True

        except TelegramSendError:
            raise
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            raise TelegramSendError(f"Send failed: {e}") from e

    async def send_bulk_notifications(
        self,
        recipients: list[str | int],
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        **kwargs,
    ) -> dict[str, bool]:
        results = {}

        for recipient in recipients:
            try:
                success = await self.send_notification(
                    recipient, message, priority=priority, **kwargs
                )
                results[str(recipient)] = success
            except Exception as e:
                logger.error(f"Failed to send to {recipient}: {e}")
                results[str(recipient)] = False

        return results

    async def send_security_alert(
        self, recipient: str | int, alert_type: str, details: dict[str, Any]
    ) -> bool:
        message = f"🔐 **Alerta de Seguridad: {alert_type}**"

        return await self.send_notification(
            recipient,
            message,
            priority=NotificationPriority.CRITICAL,
            source="Security Monitor",
            extra_data=details,
        )

    async def send_system_alert(
        self,
        recipient: str | int,
        alert_message: str,
        metrics: dict[str, Any] | None = None,
    ) -> bool:
        return await self.send_notification(
            recipient,
            alert_message,
            priority=NotificationPriority.HIGH,
            source="System Monitor",
            extra_data=metrics,
        )

    async def send_user_activity_alert(
        self, recipient: str | int, username: str, activity_data: dict[str, Any]
    ) -> bool:
        message = f"👤 **Alta actividad detectada: {username}**"

        return await self.send_notification(
            recipient,
            message,
            priority=NotificationPriority.HIGH,
            source="User Monitor",
            extra_data=activity_data,
        )

    async def health_check(self) -> dict[str, Any]:
        status = {
            "enabled": self.enabled,
            "connected": False,
            "bot_mode": bool(self.bot_token),
            "session": self.session_name,
            "error": None,
        }

        if not self.enabled:
            return status

        try:
            await self._ensure_connected()
            async with self.session() as client:
                me = await client.get_me()
                status["connected"] = True
                status["user_id"] = me.id
                status["username"] = getattr(me, "username", None)
        except Exception as e:
            status["error"] = str(e)
            logger.error(f"Health check failed: {e}")

        return status

    def __del__(self):
        """Cleanup on deletion"""
        if self._client and self._connected:
            try:
                # Try to disconnect gracefully
                if self._event_loop and self._event_loop.is_running():
                    asyncio.create_task(self.disconnect())
            except Exception:
                pass


# Singleton instance
_telegram_service: TelegramService | None = None


def get_telegram_service(
    api_id: int | None = None,
    api_hash: str | None = None,
    proxy: dict[str, Any] | None = None,
    **kwargs,
) -> TelegramService:
    """
    Get or create TelegramService singleton instance

    Args:
        api_id: Telegram API ID (required on first call)
        api_hash: Telegram API Hash (required on first call)
        proxy: Proxy configuration dict for Telethon
        **kwargs: Additional parameters for TelegramService

    Returns:
        TelegramService instance
    """
    global _telegram_service

    if _telegram_service is None:
        if api_id is None or api_hash is None:
            raise ValueError("api_id and api_hash required for first initialization")

        _telegram_service = TelegramService(
            api_id=api_id, api_hash=api_hash, proxy=proxy, **kwargs
        )

    return _telegram_service


async def cleanup_telegram_service():
    """Cleanup Telegram service on shutdown"""
    global _telegram_service

    if _telegram_service:
        await _telegram_service.disconnect()
        _telegram_service = None
        logger.info("Telegram service cleaned up")
