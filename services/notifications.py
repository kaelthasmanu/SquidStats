import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Any

# Enhanced notifications storage
notifications_store = {"notifications": [], "unread_count": 0, "last_check": None}

# Global variable for Socket.IO
socketio = None


def set_socketio_instance(sio):
    global socketio
    socketio = sio


def set_commit_notifications(has_updates, messages):
    """Keep for compatibility"""
    # Convert commits to system notifications
    if has_updates and messages:
        for msg in messages:
            add_notification("info", f"Commit: {msg}", "fa-code-branch", "git")


def get_commit_notifications():
    """Keep for compatibility with existing code"""
    return {
        "has_updates": len(
            [
                n
                for n in notifications_store["notifications"]
                if n.get("source") == "git"
            ]
        )
        > 0,
        "commits": [
            n["message"].replace("Commit: ", "")
            for n in notifications_store["notifications"]
            if n.get("source") == "git"
        ],
    }


def add_notification(
    notification_type: str, message: str, icon: str = None, source: str = "system"
):
    """Adds a notification to the system and emits via Socket.IO if configured"""
    notification = {
        "id": len(notifications_store["notifications"]) + 1,
        "type": notification_type,  # 'info', 'warning', 'error', 'success'
        "message": message,
        "icon": icon or get_default_icon(notification_type),
        "timestamp": datetime.now().isoformat(),
        "time": "Hace unos momentos",
        "read": False,
        "source": source,
    }

    # Add to the beginning of the list
    notifications_store["notifications"].insert(0, notification)

    # Increment unread counter
    if not notification["read"]:
        notifications_store["unread_count"] += 1

    # Keep maximum 50 notifications
    if len(notifications_store["notifications"]) > 50:
        # Remove oldest ones, but keep unread if possible
        old_notifications = notifications_store["notifications"][50:]
        for old_notif in old_notifications:
            if not old_notif["read"]:
                notifications_store["unread_count"] -= 1
        notifications_store["notifications"] = notifications_store["notifications"][:50]

    # Emit via Socket.IO if configured
    if socketio:
        socketio.emit(
            "new_notification",
            {
                "notification": notification,
                "unread_count": notifications_store["unread_count"],
            },
        )

    return notification


def get_default_icon(notification_type):
    icons = {
        "info": "fa-info-circle",
        "warning": "fa-exclamation-triangle",
        "error": "fa-times-circle",
        "success": "fa-check-circle",
    }
    return icons.get(notification_type, "fa-bell")


def get_all_notifications(limit: int = 10) -> dict[str, Any]:
    """Gets all system notifications"""
    return {
        "unread_count": notifications_store["unread_count"],
        "notifications": notifications_store["notifications"][:limit],
    }


def mark_notifications_read(notification_ids: list[int]):
    """Marks notifications as read"""
    for notification in notifications_store["notifications"]:
        if notification["id"] in notification_ids and not notification["read"]:
            notification["read"] = True
            notifications_store["unread_count"] -= 1


def check_squid_service():
    """Checks Squid service status and generates notifications"""
    try:
        # Check if Squid is running
        result = subprocess.run(
            ["systemctl", "is-active", "squid"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            add_notification(
                "error",
                "Squid service is not running",
                "fa-exclamation-triangle",
                "squid",
            )
        else:
            # Check recent Squid error logs
            log_check = subprocess.run(
                ["journalctl", "-u", "squid", "--since", "1 hour ago", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if (
                "error" in log_check.stdout.lower()
                or "failed" in log_check.stdout.lower()
            ):
                add_notification(
                    "warning",
                    "Errors detected in Squid logs",
                    "fa-exclamation-triangle",
                    "squid",
                )

    except subprocess.TimeoutExpired:
        add_notification(
            "warning", "Timeout checking Squid status", "fa-clock", "squid"
        )
    except Exception as e:
        print(f"Error checking Squid service: {e}")


def check_squid_log_health():
    """Checks Squid logs health"""
    try:
        log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")

        if os.path.exists(log_file):
            # Check if log file is growing
            stat_info = os.stat(log_file)
            file_size_mb = stat_info.st_size / (1024 * 1024)

            if file_size_mb > 100:  # More than 100MB
                add_notification(
                    "warning",
                    f"Squid log very large: {file_size_mb:.1f}MB",
                    "fa-file-alt",
                    "squid",
                )

            # Check last modification (not updated in more than 5 minutes)
            last_modified = datetime.fromtimestamp(stat_info.st_mtime)
            time_diff = datetime.now() - last_modified
            if time_diff.total_seconds() > 300:  # 5 minutes
                add_notification(
                    "warning",
                    "Squid log not updated for more than 5 minutes",
                    "fa-clock",
                    "squid",
                )

        else:
            add_notification(
                "error",
                f"Squid log file not found: {log_file}",
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
                f"Critical disk space: {free_disk:.1f}GB free",
                "fa-hdd",
                "system",
            )
        elif free_disk < 5:  # Less than 5GB free
            add_notification(
                "warning", f"Low disk space: {free_disk:.1f}GB free", "fa-hdd", "system"
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
    """Inicia el monitor de notificaciones en segundo plano"""

    def monitor_loop():
        check_count = 0
        while True:
            try:
                # Check commits every 30 minutes (every 15 cycles)
                if check_count % 15 == 0:
                    current_file_dir = os.path.dirname(os.path.abspath(__file__))
                    repo_path = os.path.dirname(current_file_dir)  # Go up one level
                    if os.path.exists(repo_path):
                        has_updates, messages = has_remote_commits_with_messages(
                            repo_path
                        )
                        set_commit_notifications(has_updates, messages)

                # CRITICAL checks every 2 minutes (always)
                check_squid_service()
                check_squid_log_health()
                check_system_health()

                # SECURITY checks every 5 minutes (every 2-3 cycles)
                if check_count % 3 == 0:
                    check_security_events()

                # USER checks every 10 minutes (every 5 cycles)
                if check_count % 5 == 0:
                    check_user_activity()

                check_count += 1
                if check_count > 1000:  # Prevent overflow
                    check_count = 0

            except Exception as e:
                print(f"Error in notification monitor: {e}")

            time.sleep(120)  # Wait 2 minutes between cycles

    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()


# Specific functions for Squid that can be called from other parts
def notify_squid_restart_success():
    """Notify successful Squid restart"""
    add_notification("success", "Squid restarted successfully", "fa-sync-alt", "squid")


def notify_squid_restart_failed(error_message: str = ""):
    """Notify failed Squid restart"""
    message = "Error restarting Squid"
    if error_message:
        message += f": {error_message}"
    add_notification("error", message, "fa-exclamation-triangle", "squid")


def notify_squid_config_error(error_message: str):
    """Notify Squid configuration error"""
    add_notification(
        "error", f"Squid configuration error: {error_message}", "fa-cog", "squid"
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
                f"{failed_auth_count} failed authentication attempts in the last hour",
                "fa-shield-alt",
                "security",
            )

        # 2. Denied requests
        denied_count = get_denied_requests(db, hours=1)
        if denied_count > 20:
            add_notification(
                "warning",
                f"{denied_count} denied requests in the last hour",
                "fa-ban",
                "security",
            )

        # 3. Suspicious IPs (many requests in short time)
        suspicious_ips = find_suspicious_activity(db, threshold=100, hours=1)
        for ip, count in suspicious_ips:
            if count > 200:  # More than 200 requests in 1 hour
                add_notification(
                    "warning",
                    f"Suspicious activity from IP {ip}: {count} requests/hour",
                    "fa-user-secret",
                    "security",
                )
            elif count > 500:  # More than 500 requests - critical
                add_notification(
                    "error",
                    f"Critical activity from IP {ip}: {count} requests/hour",
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
                f"High activity: {active_users} users connected in the last hour",
                "fa-users",
                "users",
            )

        elif active_users == 0:
            add_notification(
                "warning", "No active users in the last hour", "fa-users", "users"
            )

        # 2. Users with high data consumption
        high_usage_users = get_high_usage_users(db, hours=24, threshold_mb=100)

        for user, usage_mb in high_usage_users[:3]:  # Top 3
            if usage_mb > 1000:  # More than 1GB
                add_notification(
                    "warning",
                    f"User {user} consumed {usage_mb:.0f}MB in 24h",
                    "fa-chart-line",
                    "users",
                )
            elif usage_mb > 500:  # More than 500MB
                add_notification(
                    "info",
                    f"User {user} consumed {usage_mb:.0f}MB in 24h",
                    "fa-user",
                    "users",
                )

        db.close()

    except Exception as e:
        print(f"Error checking user activity: {e}")
