import os

from loguru import logger
from sqlalchemy import text

from config import Config
from database.database import get_session
from parsers.log import process_logs
from services.database import backup_service
from services.notifications.notifications import (
    has_remote_commits_with_messages,
    set_commit_notifications,
)
from services.quota.quota_scheduler import register_quota_scheduler_tasks
from services.system.metrics_service import MetricsService

_DENIED_LOGS_MAX_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB hard limit
_DENIED_LOGS_TARGET_BYTES = int(_DENIED_LOGS_MAX_BYTES * 0.65)  # free 35 % → keep 65 %


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

    @scheduler.task(
        "interval", id="trim_denied_logs", minutes=60, misfire_grace_time=900
    )
    def trim_denied_logs_task():
        """Keep denied_logs under 1 GB.

        When the table exceeds the limit, oldest rows are deleted until it
        sits at 650 MB (35% headroom), using a single DELETE with a subquery
        so no Python-level row iteration is needed.
        """

        session = None
        try:
            session = get_session()
            db_type = Config.DATABASE_TYPE

            # ── Measure current size ──────────────────────────────────────
            if db_type == "SQLITE":
                size = (
                    session.execute(
                        text(
                            "SELECT COALESCE(SUM(pgsize), 0)"
                            " FROM dbstat WHERE name = 'denied_logs'"
                        )
                    ).scalar()
                    or 0
                )
            elif db_type in ("MYSQL", "MARIADB"):
                size = (
                    session.execute(
                        text(
                            "SELECT COALESCE(data_length + index_length, 0)"
                            " FROM information_schema.tables"
                            " WHERE table_schema = DATABASE()"
                            "   AND table_name = 'denied_logs'"
                        )
                    ).scalar()
                    or 0
                )
            elif db_type in ("POSTGRES", "POSTGRESQL"):
                size = (
                    session.execute(
                        text("SELECT pg_total_relation_size('denied_logs')")
                    ).scalar()
                    or 0
                )
            else:
                return

            if size <= _DENIED_LOGS_MAX_BYTES:
                return  # nothing to do

            logger.warning(
                f"denied_logs size {size:,} B exceeds {_DENIED_LOGS_MAX_BYTES:,} B limit"
                " — trimming oldest rows"
            )

            # ── Estimate bytes-per-row and calculate how many to delete ──
            row_count = (
                session.execute(text("SELECT COUNT(*) FROM denied_logs")).scalar() or 0
            )

            if row_count == 0:
                return

            bytes_per_row = size / row_count
            bytes_to_free = size - _DENIED_LOGS_TARGET_BYTES
            rows_to_delete = max(1, int(bytes_to_free / bytes_per_row))

            # ── Delete oldest rows via subquery (works on all engines) ────
            session.execute(
                text(
                    "DELETE FROM denied_logs WHERE id IN ("
                    "  SELECT id FROM denied_logs"
                    "  ORDER BY created_at ASC"
                    "  LIMIT :n"
                    ")"
                ),
                {"n": rows_to_delete},
            )
            session.commit()

            logger.info(
                f"Trimmed {rows_to_delete:,} row(s) from denied_logs"
                f" (was {size:,} B, target {_DENIED_LOGS_TARGET_BYTES:,} B)"
            )

        except Exception:
            logger.exception("Error trimming denied_logs table")
            if session:
                session.rollback()
        finally:
            if session:
                session.close()
