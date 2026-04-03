import os

from loguru import logger

from parsers.log import process_logs
from services.database import backup_service
from services.notifications.notifications import (
    has_remote_commits_with_messages,
    set_commit_notifications,
)
from services.quota.quota_scheduler import register_quota_scheduler_tasks
from services.system.metrics_service import MetricsService


def register_scheduler_tasks(scheduler):
    """Registers global scheduler tasks for the app."""

    @scheduler.task(
        "interval", id="check_notifications", minutes=30, misfire_grace_time=1800
    )
    def check_notifications_task():
        repo_path = os.path.dirname(os.path.abspath(__file__))
        has_updates, messages = has_remote_commits_with_messages(repo_path)
        set_commit_notifications(has_updates, messages)

    @scheduler.task("interval", id="do_job_1", seconds=30, misfire_grace_time=900)
    def init_scheduler():
        log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
        logger.info(f"Scheduler for file log: {log_file}")

        if not os.path.exists(log_file):
            logger.error(f"Log file not found: {log_file}")
            return

        process_logs(log_file)

    @scheduler.task("interval", id="cleanup_metrics", hours=1, misfire_grace_time=3600)
    def cleanup_old_metrics():
        try:
            success = MetricsService.cleanup_old_metrics()
            if success:
                logger.info("Cleanup of old metrics completed successfully")
            else:
                logger.warning("Error during cleanup of old metrics")
        except Exception as e:
            logger.error(f"Error in metrics cleanup task: {e}")

    @scheduler.task("cron", id="auto_backup", hour=2, minute=0, misfire_grace_time=3600)
    def auto_backup_task():
        """Daily automatic backup at 02:00. Respects per-period quota."""
        cfg = backup_service.load_config()
        if not cfg.get("enabled", False):
            return
        result = backup_service.run_backup(is_auto=True)
        if result["status"] == "success":
            logger.info(f"Auto backup completed: {result.get('filename')}")
        elif result["status"] == "skipped":
            logger.info(f"Auto backup skipped: {result['message']}")
        else:
            logger.error(f"Auto backup failed: {result['message']}")

    # Register quota worker tasks along with global tasks.
    register_quota_scheduler_tasks(scheduler)
