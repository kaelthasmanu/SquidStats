import hashlib
import os
import subprocess
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func

from database.database import Notification, get_session

# Global variable for Socket.IO
socketio = None


def set_socketio_instance(sio):
    global socketio
    socketio = sio


def _generate_message_hash(message: str, source: str, notification_type: str) -> str:
    """Generate SHA256 hash for deduplication"""
    content = f"{source}:{notification_type}:{message}"
    return hashlib.sha256(content.encode()).hexdigest()


def _check_duplicate_notification(
    db, message_hash: str, hours: int = 24
) -> Notification:
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


def get_commit_notifications():
    """Keep for compatibility with existing code"""
    db = get_session()
    try:
        git_notifications = (
            db.query(Notification).filter(Notification.source == "git").all()
        )

        return {
            "has_updates": len(git_notifications) > 0,
            "commits": [n.message.replace("Commit: ", "") for n in git_notifications],
        }
    finally:
        db.close()


def add_notification(
    notification_type: str,
    message: str,
    icon: str = None,
    source: str = "system",
    deduplicate_hours: int = 1,
):
    """Adds a notification to the database and emits via Socket.IO if configured

    Args:
        notification_type: Type of notification ('info', 'warning', 'error', 'success')
        message: Notification message
        icon: FontAwesome icon class (optional)
        source: Source of the notification ('squid', 'system', 'security', 'users', 'git')
        deduplicate_hours: Hours to check for duplicate notifications (default: 1)

    Returns:
        Dictionary with notification data or None if it was a duplicate
    """
    db = get_session()
    try:
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
            db.commit()

            # Create dict before closing session
            notification_dict = _notification_to_dict(existing)

            # Emit update via Socket.IO
            if socketio:
                unread_count = (
                    db.query(func.count(Notification.id))
                    .filter(Notification.read == 0)
                    .scalar()
                )

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
        db.commit()
        db.refresh(notification)

        # Create dict before cleanup
        notification_dict = _notification_to_dict(notification)

        # Clean old notifications (keep last 100)
        _cleanup_old_notifications(db, keep_count=100)

        # Emit via Socket.IO if configured
        if socketio:
            unread_count = (
                db.query(func.count(Notification.id))
                .filter(Notification.read == 0)
                .scalar()
            )

            socketio.emit(
                "new_notification",
                {
                    "notification": notification_dict,
                    "unread_count": unread_count,
                },
            )

        return notification_dict

    finally:
        db.close()


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


def _cleanup_old_notifications(db, keep_count: int = 100):
    """Remove old notifications, keeping only the most recent ones"""
    total_count = db.query(func.count(Notification.id)).scalar()

    if total_count > keep_count:
        # Get IDs of notifications to keep
        keep_ids = (
            db.query(Notification.id)
            .order_by(desc(Notification.created_at))
            .limit(keep_count)
            .all()
        )

        keep_ids = [id_tuple[0] for id_tuple in keep_ids]

        # Delete old notifications
        db.query(Notification).filter(Notification.id.notin_(keep_ids)).delete(
            synchronize_session=False
        )

        db.commit()


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
    db = get_session()
    try:
        # Get total count
        total_notifications = db.query(func.count(Notification.id)).scalar()

        # Get unread count
        unread_count = (
            db.query(func.count(Notification.id))
            .filter(Notification.read == 0)
            .scalar()
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
            "unread_count": unread_count,
            "notifications": notifications_list,
            "pagination": {
                "current_page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "total_notifications": total_notifications,
                "has_prev": page > 1,
                "has_next": page < total_pages,
            },
        }
    finally:
        db.close()


def mark_notifications_read(notification_ids: list[int]):
    """Marks notifications as read in database"""
    db = get_session()
    try:
        db.query(Notification).filter(Notification.id.in_(notification_ids)).update(
            {"read": 1, "updated_at": datetime.now()}, synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def delete_notification(notification_id: int):
    """Delete a specific notification from database"""
    db = get_session()
    try:
        db.query(Notification).filter(Notification.id == notification_id).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def delete_all_notifications():
    """Delete all notifications from database"""
    db = get_session()
    try:
        db.query(Notification).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def check_squid_log_health():
    """Checks Squid logs health"""
    try:
        log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")

        if os.path.exists(log_file):
            # Check if log file is growing
            stat_info = os.stat(log_file)
            file_size_mb = stat_info.st_size / (1024 * 1024)

            if file_size_mb > 500:  # More than 500MB
                add_notification(
                    "warning",
                    f"Log de Squid muy grande: {file_size_mb:.1f}MB",
                    "fa-file-alt",
                    "squid",
                )

            # Check last modification (not updated in more than 24 hours)
            last_modified = datetime.fromtimestamp(stat_info.st_mtime)
            time_diff = datetime.now() - last_modified
            if time_diff.total_seconds() > 86400:  # 24 hours
                add_notification(
                    "warning",
                    "Log de Squid no actualizado por más de 24 horas",
                    "fa-clock",
                    "squid",
                )

        else:
            add_notification(
                "error",
                f"Archivo de log de Squid no encontrado: {log_file}",
                "fa-file-exclamation",
                "squid",
            )

    except Exception as e:
        print(f"Error checking Squid log health: {e}")


def check_system_health():
    """Checks general system health"""
    try:
        # Check disk usage
        disk_usage = os.statvfs("/")
        free_disk = (disk_usage.f_bavail * disk_usage.f_frsize) / (1024**3)  # GB free

        if free_disk < 1:  # Less than 1GB free
            add_notification(
                "error",
                f"Espacio en disco crítico: {free_disk:.1f}GB libres",
                "fa-hdd",
                "system",
            )
        elif free_disk < 5:  # Less than 5GB free
            add_notification(
                "warning",
                f"Espacio en disco bajo: {free_disk:.1f}GB libres",
                "fa-hdd",
                "system",
            )

    except Exception as e:
        print(f"Error checking system health: {e}")


# Function for commits
def has_remote_commits_with_messages(
    repo_path: str, branch: str = "main"
) -> tuple[bool, list[str]]:
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise ValueError(f"No es un repositorio Git válido: {repo_path}")
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
        print(f"Error al ejecutar comandos git: {e.stderr}")
        return False, []


# Thread for periodic checks
def start_notification_monitor():
    """Starts the notification monitor in background with graceful shutdown support"""
    import signal

    stop_event = threading.Event()

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        stop_event.set()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    def monitor_loop():
        check_count = 0
        cycle_interval = 60  # 1 minute between cycles for better granularity

        while not stop_event.is_set():
            try:
                # Check commits every 30 minutes (every 30 cycles)
                if check_count % 30 == 0:
                    current_file_dir = os.path.dirname(os.path.abspath(__file__))
                    repo_path = os.path.dirname(current_file_dir)  # Go up one level
                    if os.path.exists(repo_path):
                        has_updates, messages = has_remote_commits_with_messages(
                            repo_path
                        )
                        set_commit_notifications(has_updates, messages)

                if check_count % 5 == 0:
                    check_system_health()

                if check_count % 10 == 0:
                    check_squid_log_health()

                if check_count % 3 == 0:
                    check_security_events()

                if check_count % 15 == 0:
                    check_user_activity()

                check_count += 1
                if check_count > 1000:  # Prevent overflow
                    check_count = 0

            except Exception as e:
                print(f"Error in notification monitor: {e}")

            stop_event.wait(timeout=cycle_interval)

    thread = threading.Thread(
        target=monitor_loop, daemon=True, name="NotificationMonitor"
    )
    thread.start()

    return stop_event  # Return the event for potential external control


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
        from database.database import get_session
        from services.auditoria_service import (
            find_suspicious_activity,
            get_denied_requests,
            get_failed_auth_attempts,
        )

        db = get_session()

        # 1. Failed authentication attempts
        failed_auth_count = get_failed_auth_attempts(db, hours=1)
        if failed_auth_count > 15:
            add_notification(
                "warning",
                f"{failed_auth_count} intentos de autenticación fallidos en la última hora",
                "fa-shield-alt",
                "security",
            )

        # 2. Denied requests
        denied_count = get_denied_requests(db, hours=1)
        if denied_count > 20:
            add_notification(
                "warning",
                f"{denied_count} solicitudes denegadas en la última hora",
                "fa-ban",
                "security",
            )

        # 3. Suspicious IPs (many requests in short time)
        suspicious_ips = find_suspicious_activity(db, threshold=100, hours=1)
        for ip, count in suspicious_ips:
            if count > 200:  # More than 200 requests in 1 hour
                add_notification(
                    "warning",
                    f"Actividad sospechosa desde IP {ip}: {count} solicitudes/hora",
                    "fa-user-secret",
                    "security",
                )
            elif count > 500:  # More than 500 requests - critical
                add_notification(
                    "error",
                    f"Actividad crítica desde IP {ip}: {count} solicitudes/hora",
                    "fa-exclamation-triangle",
                    "security",
                )

        db.close()

    except Exception as e:
        print(f"Error checking security events: {e}")


def check_user_activity():
    """Checks user activity from the database"""
    try:
        from database.database import get_session
        from services.auditoria_service import (
            get_active_users_count,
            get_high_usage_users,
        )

        db = get_session()

        # 1. Active users in the last hour
        active_users = get_active_users_count(db, hours=1)

        if active_users > 50:
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

        for user, usage_mb in high_usage_users[:3]:  # Top 3
            if usage_mb > 1000:  # More than 1GB
                add_notification(
                    "warning",
                    f"El usuario {user} consumió {usage_mb:.0f}MB en 24h",
                    "fa-chart-line",
                    "users",
                )
            elif usage_mb > 500:  # More than 500MB
                add_notification(
                    "info",
                    f"El usuario {user} consumió {usage_mb:.0f}MB en 24h",
                    "fa-user",
                    "users",
                )

        db.close()

    except Exception as e:
        print(f"Error checking user activity: {e}")
