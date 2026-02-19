import hashlib
import os
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

from database.database import Notification, get_session

# Import Telegram integration (optional - fails gracefully if not configured)
try:
    from services.telegram_integration import send_telegram_notification

    TELEGRAM_AVAILABLE = True
except Exception as e:
    logger.debug(f"Telegram integration not available: {e}")
    TELEGRAM_AVAILABLE = False
    send_telegram_notification = None

# Configuration constants
CLEANUP_KEEP_COUNT = 100
DEFAULT_DEDUPLICATE_HOURS = 1

# Notification thresholds
FAILED_AUTH_THRESHOLD = 15
DENIED_REQUESTS_THRESHOLD = 20
SUSPICIOUS_IP_THRESHOLD = 6000
CRITICAL_IP_THRESHOLD = 20000
MAX_IPS_TO_REPORT = 5

# User activity thresholds
HIGH_ACTIVITY_THRESHOLD = 100
HIGH_USAGE_GB_THRESHOLD = 20.0
MAX_USERS_TO_REPORT = 3

# System health thresholds
SQUID_LOG_SIZE_WARNING_MB = 500
SQUID_LOG_STALE_HOURS = 24
DISK_CRITICAL_GB = 1
DISK_WARNING_GB = 5

# Monitor intervals (in minutes)
CHECK_COMMITS_INTERVAL = 30
CHECK_SYSTEM_INTERVAL = 5
CHECK_SQUID_LOG_INTERVAL = 10
CHECK_SECURITY_INTERVAL = 3
CHECK_USER_ACTIVITY_INTERVAL = 15

# Global variable for Socket.IO
socketio = None

# Global stop event for notification monitor
_monitor_stop_event = None
_monitor_thread = None


def set_socketio_instance(sio):
    global socketio
    socketio = sio


@contextmanager
def get_db_session():
    """Context manager for database sessions"""
    db = get_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def stop_notification_monitor():
    """Stop the notification monitor thread"""
    global _monitor_stop_event, _monitor_thread

    if _monitor_stop_event:
        _monitor_stop_event.set()

    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_thread.join(timeout=5)
        logger.info("Notification monitor stopped")


def _generate_message_hash(message: str, source: str, notification_type: str) -> str:
    """Generate SHA256 hash for deduplication"""
    content = f"{source}:{notification_type}:{message}"
    return hashlib.sha256(content.encode()).hexdigest()


def _check_duplicate_notification(
    db: Session, message_hash: str, hours: int = 24
) -> Notification | None:
    """Check if a similar notification exists in the last N hours"""
    time_threshold = datetime.now() - timedelta(hours=hours)
    return (
        db.query(Notification)
        .filter(
            and_(
                Notification.message_hash == message_hash,
                Notification.created_at >= time_threshold,
            )
        )
        .first()
    )


def set_commit_notifications(has_updates, messages):
    """Keep for compatibility"""
    # Convert commits to system notifications
    if has_updates and messages:
        for msg in messages:
            add_notification("info", f"Commit: {msg}", "fa-code-branch", "git")


def get_commit_notifications() -> dict[str, Any]:
    """Keep for compatibility with existing code"""
    with get_db_session() as db:
        git_notifications = (
            db.query(Notification).filter(Notification.source == "git").all()
        )

        return {
            "has_updates": len(git_notifications) > 0,
            "commits": [n.message.replace("Commit: ", "") for n in git_notifications],
        }


def add_notification(
    notification_type: str,
    message: str,
    icon: str | None = None,
    source: str = "system",
    deduplicate_hours: int = DEFAULT_DEDUPLICATE_HOURS,
    send_telegram: bool = True,
) -> dict[str, Any] | None:
    """Adds a notification to the database and emits via Socket.IO if configured

    Args:
        notification_type: Type of notification ('info', 'warning', 'error', 'success')
        message: Notification message
        icon: FontAwesome icon class (optional)
        source: Source of the notification ('squid', 'system', 'security', 'users', 'git')
        deduplicate_hours: Hours to check for duplicate notifications
        send_telegram: Send notification to Telegram (default: True)

    Returns:
        Dictionary with notification data or None if it was a duplicate
    """
    with get_db_session() as db:
        message_hash = _generate_message_hash(message, source, notification_type)

        # Check for duplicates
        existing = _check_duplicate_notification(
            db, message_hash, hours=deduplicate_hours
        )

        if existing:
            # Update existing notification count and timestamp
            existing.count += 1
            existing.updated_at = datetime.now()
            existing.read = 0  # Mark as unread again

            # Create dict before closing session
            notification_dict = _notification_to_dict(existing)

            # Emit update via Socket.IO
            if socketio:
                unread_count = _get_unread_count(db)
                socketio.emit(
                    "notification_updated",
                    {
                        "notification": notification_dict,
                        "unread_count": unread_count,
                    },
                )

            return notification_dict

        # Create new notification
        notification = Notification(
            type=notification_type,
            message=message,
            message_hash=message_hash,
            icon=icon or get_default_icon(notification_type),
            source=source,
            read=0,
            count=1,
            created_at=datetime.now(),
        )

        db.add(notification)
        db.flush()  # Flush to get ID without committing
        db.refresh(notification)

        # Create dict before cleanup
        notification_dict = _notification_to_dict(notification)

        # Clean old notifications (keep last N)
        _cleanup_old_notifications(db, keep_count=CLEANUP_KEEP_COUNT)

        # Emit via Socket.IO if configured
        if socketio:
            unread_count = _get_unread_count(db)
            socketio.emit(
                "new_notification",
                {
                    "notification": notification_dict,
                    "unread_count": unread_count,
                },
            )

        # Send to Telegram if enabled and requested
        if send_telegram and TELEGRAM_AVAILABLE and send_telegram_notification:
            try:
                send_telegram_notification(
                    notification_type=notification_type, message=message, source=source
                )
            except Exception as e:
                logger.error(f"Failed to send Telegram notification: {e}")

        return notification_dict


def _notification_to_dict(notification: Notification) -> dict:
    """Convert Notification object to dictionary"""
    return {
        "id": notification.id,
        "type": notification.type,
        "message": notification.message,
        "icon": notification.icon,
        "timestamp": notification.created_at.isoformat(),
        "time": _format_time_ago(notification.created_at),
        "read": bool(notification.read),
        "source": notification.source,
        "count": notification.count,
    }


def _format_time_ago(timestamp: datetime) -> str:
    """Format timestamp as 'hace X tiempo'"""
    now = datetime.now()
    diff = now - timestamp

    minutes = int(diff.total_seconds() / 60)
    hours = int(diff.total_seconds() / 3600)
    days = int(diff.total_seconds() / 86400)

    if minutes < 1:
        return "Hace unos momentos"
    elif minutes < 60:
        return f"Hace {minutes} minuto{'s' if minutes > 1 else ''}"
    elif hours < 24:
        return f"Hace {hours} hora{'s' if hours > 1 else ''}"
    else:
        return f"Hace {days} día{'s' if days > 1 else ''}"


def _get_unread_count(db: Session) -> int:
    """Get count of unread notifications"""
    return db.query(func.count(Notification.id)).filter(Notification.read == 0).scalar()


def _cleanup_old_notifications(db: Session, keep_count: int = CLEANUP_KEEP_COUNT):
    """Remove old notifications, keeping only the most recent ones"""
    total_count = db.query(func.count(Notification.id)).scalar()

    if total_count > keep_count:
        # Get IDs of notifications to keep
        keep_ids_query = (
            db.query(Notification.id)
            .order_by(desc(Notification.created_at))
            .limit(keep_count)
            .subquery()
        )

        # Delete old notifications in one query
        deleted = (
            db.query(Notification)
            .filter(Notification.id.notin_(keep_ids_query))
            .delete(synchronize_session=False)
        )

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old notifications")


def get_default_icon(notification_type):
    icons = {
        "info": "fa-info-circle",
        "warning": "fa-exclamation-triangle",
        "error": "fa-times-circle",
        "success": "fa-check-circle",
    }
    return icons.get(notification_type, "fa-bell")


def get_all_notifications(
    limit: int = 10, page: int = 1, per_page: int = 20
) -> dict[str, Any]:
    """Gets all system notifications with pagination support from database"""
    with get_db_session() as db:
        # Get total count
        total_notifications = db.query(func.count(Notification.id)).scalar() or 0

        # Get unread count
        unread_count = (
            db.query(func.count(Notification.id))
            .filter(Notification.read == 0)
            .scalar()
            or 0
        )

        # Calculate pagination
        start_index = (page - 1) * per_page

        # Get paginated notifications
        notifications = (
            db.query(Notification)
            .order_by(desc(Notification.created_at))
            .offset(start_index)
            .limit(per_page)
            .all()
        )

        # Convert to dict
        notifications_list = [_notification_to_dict(n) for n in notifications]

        # Calculate pagination metadata
        total_pages = (
            (total_notifications + per_page - 1) // per_page
            if total_notifications > 0
            else 1
        )

        return {
            "unread_count": int(unread_count),
            "notifications": notifications_list,
            "pagination": {
                "current_page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "total_notifications": int(total_notifications),
                "has_prev": page > 1,
                "has_next": page < total_pages,
            },
        }


def mark_notifications_read(notification_ids: list[int]) -> int:
    with get_db_session() as db:
        updated = (
            db.query(Notification)
            .filter(Notification.id.in_(notification_ids))
            .update(
                {"read": 1, "updated_at": datetime.now()}, synchronize_session=False
            )
        )
        logger.info(f"Marked {updated} notifications as read")
        return updated


def delete_notification(notification_id: int) -> bool:
    with get_db_session() as db:
        deleted = (
            db.query(Notification)
            .filter(Notification.id == notification_id)
            .delete(synchronize_session=False)
        )

        if deleted:
            logger.info(f"Deleted notification {notification_id}")
        return deleted > 0


def delete_all_notifications() -> int:
    with get_db_session() as db:
        deleted = db.query(Notification).delete(synchronize_session=False)
        logger.info(f"Deleted all {deleted} notifications")
        return deleted


def check_squid_log_health():
    """Checks Squid logs health"""
    try:
        log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")

        if not os.path.exists(log_file):
            add_notification(
                "error",
                f"Archivo de log de Squid no encontrado: {log_file}",
                "fa-file-exclamation",
                "squid",
            )
            return

        stat_info = os.stat(log_file)
        file_size_mb = stat_info.st_size / (1024 * 1024)

        # Check file size
        if file_size_mb > SQUID_LOG_SIZE_WARNING_MB:
            add_notification(
                "warning",
                f"Log de Squid muy grande: {file_size_mb:.1f}MB",
                "fa-file-alt",
                "squid",
            )

        # Check last modification
        last_modified = datetime.fromtimestamp(stat_info.st_mtime)
        hours_since_update = (datetime.now() - last_modified).total_seconds() / 3600

        if hours_since_update > SQUID_LOG_STALE_HOURS:
            add_notification(
                "warning",
                f"Log de Squid no actualizado por más de {int(hours_since_update)}h",
                "fa-clock",
                "squid",
            )

    except OSError as e:
        logger.error(f"Error accessing Squid log file: {e}")
    except Exception as e:
        logger.error(f"Error checking Squid log health: {e}")


def check_system_health():
    """Checks general system health"""
    try:
        # Check disk usage
        disk_usage = os.statvfs("/")
        free_disk_gb = (disk_usage.f_bavail * disk_usage.f_frsize) / (1024**3)

        if free_disk_gb < DISK_CRITICAL_GB:
            add_notification(
                "error",
                f"Espacio en disco crítico: {free_disk_gb:.1f}GB libres",
                "fa-hdd",
                "system",
            )
        elif free_disk_gb < DISK_WARNING_GB:
            add_notification(
                "warning",
                f"Espacio en disco bajo: {free_disk_gb:.1f}GB libres",
                "fa-hdd",
                "system",
            )

    except OSError as e:
        logger.error(f"Error checking disk usage: {e}")
    except Exception as e:
        logger.error(f"Error checking system health: {e}")


# Function for commits
def has_remote_commits_with_messages(
    repo_path: str, branch: str = "main"
) -> tuple[bool, list[str]]:
    git_dir = os.path.join(repo_path, ".git")
    if not os.path.isdir(git_dir):
        logger.warning(f"Not a valid Git repository: {repo_path}")
        return False, []

    try:
        # Configurar proxy si existe la variable de entorno
        env = os.environ.copy()
        http_proxy = env.get("HTTP_PROXY", "")
        if http_proxy:
            env["http_proxy"] = http_proxy
            env["https_proxy"] = http_proxy

        subprocess.run(
            ["git", "fetch"],
            cwd=repo_path,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        result = subprocess.run(
            [
                "git",
                "rev-list",
                "--left-right",
                "--count",
                f"origin/{branch}...{branch}",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        ahead_behind = result.stdout.strip().split()
        remote_ahead = int(ahead_behind[0])

        if remote_ahead > 0:
            log_result = subprocess.run(
                ["git", "log", f"{branch}..origin/{branch}", "--pretty=format:%s"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            commit_messages = (
                log_result.stdout.strip().split("\n")
                if log_result.stdout.strip()
                else []
            )
            return True, commit_messages

        return False, []

    except subprocess.CalledProcessError as e:
        logger.error(f"Error executing git commands: {e.stderr}")
        return False, []
    except Exception as e:
        logger.error(f"Unexpected error checking git commits: {e}")
        return False, []


# Thread for periodic checks
def start_notification_monitor():
    """Starts the notification monitor in background with graceful shutdown support"""
    global _monitor_stop_event, _monitor_thread

    _monitor_stop_event = threading.Event()

    def monitor_loop():
        check_count = 0
        cycle_interval = 60  # 1 minute between cycles for better granularity

        logger.info("Notification monitor started")

        while not _monitor_stop_event.is_set():
            try:
                # Check commits every N minutes
                if check_count % CHECK_COMMITS_INTERVAL == 0:
                    current_file_dir = os.path.dirname(os.path.abspath(__file__))
                    repo_path = os.path.dirname(current_file_dir)
                    if os.path.exists(os.path.join(repo_path, ".git")):
                        has_updates, messages = has_remote_commits_with_messages(
                            repo_path
                        )
                        set_commit_notifications(has_updates, messages)

                # System health checks at different intervals
                if check_count % CHECK_SYSTEM_INTERVAL == 0:
                    check_system_health()

                if check_count % CHECK_SQUID_LOG_INTERVAL == 0:
                    check_squid_log_health()

                if check_count % CHECK_SECURITY_INTERVAL == 0:
                    check_security_events()

                if check_count % CHECK_USER_ACTIVITY_INTERVAL == 0:
                    check_user_activity()

                check_count = (check_count + 1) % 1000  # Reset to prevent overflow

            except Exception as e:
                logger.error(f"Error in notification monitor: {e}", exc_info=True)

            _monitor_stop_event.wait(timeout=cycle_interval)

    _monitor_thread = threading.Thread(
        target=monitor_loop, daemon=True, name="NotificationMonitor"
    )
    _monitor_thread.start()

    return _monitor_stop_event  # Return the event for potential external control


# Specific functions for Squid that can be called from other parts
def notify_squid_restart_success():
    """Notify successful Squid restart"""
    add_notification("success", "Squid reiniciado exitosamente", "fa-sync-alt", "squid")


def notify_squid_restart_failed(error_message: str = ""):
    """Notify failed Squid restart"""
    message = "Error al reiniciar Squid"
    if error_message:
        message += f": {error_message}"
    add_notification("error", message, "fa-exclamation-triangle", "squid")


def notify_squid_config_error(error_message: str):
    """Notify Squid configuration error"""
    add_notification(
        "error", f"Error de configuración de Squid: {error_message}", "fa-cog", "squid"
    )


def notify_squid_high_usage(warning_message: str):
    """Notify high Squid resource usage"""
    add_notification("warning", warning_message, "fa-chart-line", "squid")


def check_security_events():
    """Checks security events from the database"""
    try:
        from services.auditoria_service import (
            # find_suspicious_activity,
            get_denied_requests,
            get_failed_auth_attempts,
        )

        with get_db_session() as db:
            # 1. Failed authentication attempts
            failed_auth_count = get_failed_auth_attempts(db, hours=1)
            if failed_auth_count > FAILED_AUTH_THRESHOLD:
                add_notification(
                    "warning",
                    f"{failed_auth_count} intentos de autenticación fallidos en la última hora",
                    "fa-shield-alt",
                    "security",
                )

            # 2. Denied requests
            denied_count = get_denied_requests(db, hours=1)
            if denied_count > DENIED_REQUESTS_THRESHOLD:
                add_notification(
                    "warning",
                    f"{denied_count} solicitudes denegadas en la última hora",
                    "fa-ban",
                    "security",
                )

            # # 3. Suspicious IPs (many requests in short time)
            # suspicious_ips = find_suspicious_activity(db, threshold=100, hours=1)
            #
            # if not suspicious_ips:
            #     return
            #
            # # Limitar cantidad de notificaciones y ordenar por severidad
            # reported_count = 0
            # for ip, count in suspicious_ips:
            #     if reported_count >= MAX_IPS_TO_REPORT:
            #         # Si hay más IPs, notificar con resumen
            #         remaining = len(suspicious_ips) - MAX_IPS_TO_REPORT
            #         add_notification(
            #             "info",
            #             f"Hay {remaining} IP(s) adicionales con actividad sospechosa",
            #             "fa-info-circle",
            #             "security",
            #         )
            #         break
            #
            #     # Verificar nivel crítico primero
            #     if count > CRITICAL_IP_THRESHOLD:
            #         add_notification(
            #             "error",
            #             f"Actividad crítica desde IP {ip}: {count:,} solicitudes/hora",
            #             "fa-exclamation-triangle",
            #             "security",
            #         )
            #         reported_count += 1
            #     elif count > SUSPICIOUS_IP_THRESHOLD:
            #         add_notification(
            #             "warning",
            #             f"Actividad sospechosa desde IP {ip}: {count:,} solicitudes/hora",
            #             "fa-user-secret",
            #             "security",
            #         )
            #         reported_count += 1

    except ImportError as e:
        logger.error(f"Error importing auditoria_service modules: {e}")
    except Exception as e:
        logger.error(f"Error checking security events: {e}", exc_info=True)


def check_user_activity():
    """Checks user activity from the database"""
    try:
        from services.auditoria_service import (
            get_active_users_count,
            get_high_usage_users,
        )

        with get_db_session() as db:
            # 1. Active users in the last hour
            active_users = get_active_users_count(db, hours=1)

            if active_users > HIGH_ACTIVITY_THRESHOLD:
                add_notification(
                    "info",
                    f"Alta actividad: {active_users} usuarios conectados en la última hora",
                    "fa-users",
                    "users",
                )
            elif active_users == 0:
                add_notification(
                    "warning",
                    "No hay usuarios activos en la última hora",
                    "fa-users",
                    "users",
                )

            # 2. Users with high data consumption
            high_usage_users = get_high_usage_users(db, hours=24, threshold_mb=100)

            # Limitar a top N usuarios
            high_usage_gb = HIGH_USAGE_GB_THRESHOLD * 1024
            for user, usage_mb in high_usage_users[:MAX_USERS_TO_REPORT]:
                # Solo notificar si supera el umbral alto
                if usage_mb > high_usage_gb:
                    add_notification(
                        "warning",
                        f"El usuario {user} consumió {usage_mb:,.0f}MB en 24h",
                        "fa-chart-line",
                        "users",
                    )

    except ImportError as e:
        logger.error(f"Error importing auditoria_service modules: {e}")
    except Exception as e:
        logger.error(f"Error checking user activity: {e}", exc_info=True)
