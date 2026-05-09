"""
Backup service for SquidStats databases.

Currently implemented:
  - SQLite

Planned (not yet implemented):
  - MySQL / MariaDB
  - PostgreSQL
"""

import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask_babel import gettext as _
from loguru import logger

from config import Config
from database.database import get_session
from database.models.models import BackupConfig

# Constants

_MAX_RETENTION = 3
_DEFAULT_BACKUP_DIR = "/opt/SquidStats/backups"

FREQUENCY_CHOICES = {
    "daily_weekly": "Diaria — máx. 3 por semana",
    "daily_monthly": "Diaria — máx. 3 por mes",
}

_BACKUP_FILENAME_RE = re.compile(
    r"^squidstats_backup_[A-Za-z0-9_]+_[0-9]{8}_[0-9]{6}\.(sqlite3|sql)$"
)


# Config helpers


def _default_config() -> dict:
    return {
        "db_type": "sqlite",
        "frequency": "daily_weekly",
        "backup_dir": _DEFAULT_BACKUP_DIR,
        "enabled": False,
    }


def load_config() -> dict:
    """Read backup configuration from the database. Returns defaults if no row exists."""
    session = get_session()
    try:
        row = session.query(BackupConfig).first()
        if row is None:
            return _default_config()
        return {
            "db_type": row.db_type,
            "frequency": row.frequency,
            "backup_dir": row.backup_dir,
            "enabled": bool(row.enabled),
        }
    except Exception as e:
        logger.warning(f"Could not read backup config from DB, using defaults: {e}")
        return _default_config()
    finally:
        session.close()


def save_config(cfg: dict) -> None:
    """Upsert backup configuration into the database (single-row table)."""
    allowed_keys = {"db_type", "frequency", "backup_dir", "enabled"}
    safe = {k: v for k, v in cfg.items() if k in allowed_keys}

    session = get_session()
    try:
        row = session.query(BackupConfig).first()
        if row is None:
            row = BackupConfig(
                db_type=safe.get("db_type", "sqlite"),
                frequency=safe.get("frequency", "daily_weekly"),
                backup_dir=safe.get("backup_dir", _DEFAULT_BACKUP_DIR),
                enabled=int(bool(safe.get("enabled", False))),
                created_at=datetime.now(),
            )
            session.add(row)
        else:
            if "db_type" in safe:
                row.db_type = safe["db_type"]
            if "frequency" in safe:
                row.frequency = safe["frequency"]
            if "backup_dir" in safe:
                row.backup_dir = safe["backup_dir"]
            if "enabled" in safe:
                row.enabled = int(bool(safe["enabled"]))
            row.updated_at = datetime.now()
        session.commit()
    except Exception as e:
        session.rollback()
        logger.exception(f"Error saving backup config: {e}")
        raise
    finally:
        session.close()


# Backup directory helpers


def _backup_dir(cfg: dict) -> Path:
    p = Path(cfg.get("backup_dir", _DEFAULT_BACKUP_DIR))
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        message = (
            f"No se puede acceder al directorio de salvas '{p}': {e}. "
            "Verifique que el directorio exista y que SquidStats tenga permisos."
        )
        logger.error(message)
        raise OSError(message) from e
    return p


def _list_backup_files(backup_dir: Path) -> list[Path]:
    """Return backup files sorted newest-first."""
    files = [
        *backup_dir.glob("squidstats_backup_*.sqlite3"),
        *backup_dir.glob("squidstats_backup_*.sql"),
    ]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def _normalize_backup_filename(filename: str) -> Path | None:
    """Validate and normalize a backup filename from untrusted input."""
    if not filename:
        return None

    candidate = Path(filename)
    if candidate.name != filename:
        return None

    if candidate.is_absolute():
        return None

    if ".." in filename:
        return None

    if not _BACKUP_FILENAME_RE.fullmatch(filename):
        return None

    return Path(candidate.name)


def _get_safe_backup_path(backup_dir: Path, filename: str) -> Path | None:
    """Return a safe backup path inside the configured backup directory."""
    normalized = _normalize_backup_filename(filename)
    if normalized is None:
        return None

    target = (backup_dir / normalized).resolve()
    try:
        target.relative_to(backup_dir.resolve())
    except ValueError:
        return None

    return target


def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def list_backups(cfg: dict | None = None) -> list[dict]:
    """Return a list of backup metadata dicts, newest first."""
    if cfg is None:
        cfg = load_config()

    try:
        bdir = _backup_dir(cfg)
    except Exception as e:
        logger.error(f"No se puede acceder al directorio de salvas: {e}")
        return []

    try:
        result = []
        for f in _list_backup_files(bdir):
            stat = f.stat()
            created = datetime.fromtimestamp(stat.st_mtime)
            btype = "auto" if "_auto_" in f.name else "manual"
            result.append(
                {
                    "filename": f.name,
                    "created_at": created.strftime("%Y-%m-%d %H:%M"),
                    "size_bytes": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "type": btype,
                }
            )
        return result
    except Exception as e:
        logger.exception(f"Error listando salvas: {e}")
        return []


# Retention enforcement


def _enforce_retention(backup_dir: Path) -> None:
    """Delete oldest backups beyond _MAX_RETENTION."""
    files = _list_backup_files(backup_dir)
    for f in files[_MAX_RETENTION:]:
        try:
            f.unlink()
            logger.info(f"Backup retention: removed old backup {f.name}")
        except Exception as e:
            logger.warning(f"Could not remove old backup {f.name}: {e}")


# Period quota check


def _count_backups_in_period(backup_dir: Path, frequency: str) -> int:
    """Count how many auto-backups exist within the current period window."""
    now = datetime.now()
    count = 0
    for f in _list_backup_files(backup_dir):
        if "_auto_" not in f.name:
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if frequency == "daily_weekly":
            if (
                mtime.isocalendar()[1] == now.isocalendar()[1]
                and mtime.year == now.year
            ):
                count += 1
        else:  # daily_monthly
            if mtime.month == now.month and mtime.year == now.year:
                count += 1
    return count


# SQLite backup


def _sqlite_backup(backup_dir: Path, tag: str) -> Path:
    """Perform an online SQLite backup using sqlite3.Connection.backup()."""
    db_url = Config.DATABASE_URL
    parsed = urlparse(db_url)

    db_path = parsed.path

    # sqlite:///relative/path.db -> path is '/relative/path.db' but it should be project-relative
    if db_path.startswith("/") and not Path(db_path).exists():
        project_root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
        rel_path = db_path.lstrip("/")
        alt_path = project_root / rel_path
        if alt_path.exists():
            db_path = str(alt_path)

    if not db_path or db_path == "/":
        db_path = db_url.replace("sqlite:///", "")

    db_path = Path(db_path)
    if not db_path.is_absolute():
        project_root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
        db_path = project_root / db_path

    if not db_path.exists():
        # try fallback for sqlite:///filename.db
        try_path = (
            Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
            / db_path.name
        )
        if try_path.exists():
            db_path = try_path
        else:
            raise FileNotFoundError(f"SQLite database not found: {db_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"squidstats_backup_{tag}_{timestamp}.sqlite3"

    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    logger.info(
        f"SQLite backup created: {dest.name} ({_human_size(dest.stat().st_size)})"
    )
    return dest


# MySQL / MariaDB backup


def _mysql_backup(backup_dir: Path, tag: str) -> Path:
    """Backup using mysqldump. Requires mysqldump to be installed."""
    db_url = Config.DATABASE_URL
    parsed = urlparse(db_url)

    host = parsed.hostname or "localhost"
    port = str(parsed.port or 3306)
    user = parsed.username or "root"
    password = parsed.password or ""
    dbname = parsed.path.lstrip("/")

    if not dbname:
        raise ValueError("No database name found in DATABASE_URL")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"squidstats_backup_{tag}_{timestamp}.sql"

    cmd = [
        shutil.which("mysqldump") or "mysqldump",
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        "--single-transaction",
        "--routines",
        "--triggers",
        dbname,
    ]

    env = os.environ.copy()
    if password:
        env["MYSQL_PWD"] = password

    with open(dest, "w") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env)  # noqa: S603

    if result.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"mysqldump failed (exit {result.returncode}): {result.stderr.decode().strip()}"
        )

    logger.info(
        f"MySQL backup created: {dest.name} ({_human_size(dest.stat().st_size)})"
    )
    return dest


# PostgreSQL backup


def _postgresql_backup(backup_dir: Path, tag: str) -> Path:
    """Backup using pg_dump. Requires pg_dump to be installed."""
    db_url = Config.DATABASE_URL
    parsed = urlparse(db_url)

    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = parsed.username or "postgres"
    password = parsed.password or ""
    dbname = parsed.path.lstrip("/")

    if not dbname:
        raise ValueError("No database name found in DATABASE_URL")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"squidstats_backup_{tag}_{timestamp}.sql"

    cmd = [
        shutil.which("pg_dump") or "pg_dump",
        f"--host={host}",
        f"--port={port}",
        f"--username={user}",
        "--no-password",
        "--format=plain",
        dbname,
    ]

    env = os.environ.copy()
    env["PGPASSWORD"] = password

    with open(dest, "w") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env)  # noqa: S603

    if result.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"pg_dump failed (exit {result.returncode}): {result.stderr.decode().strip()}"
        )

    logger.info(
        f"PostgreSQL backup created: {dest.name} ({_human_size(dest.stat().st_size)})"
    )
    return dest


# Public API


def run_backup(is_auto: bool = False) -> dict:
    """Execute a database backup according to the current configuration.

    Returns a dict with keys: status ('success'|'error'|'skipped'), message,
    and filename on success.
    """
    cfg = load_config()
    db_type = cfg.get("db_type", "sqlite").lower()
    frequency = cfg.get("frequency", "daily_weekly")
    try:
        bdir = _backup_dir(cfg)
    except OSError as e:
        return {"status": "error", "message": str(e)}
    tag = "auto" if is_auto else "manual"

    if is_auto:
        current_in_period = _count_backups_in_period(bdir, frequency)
        if current_in_period >= _MAX_RETENTION:
            msg = (
                f"Quota reached: {current_in_period}/{_MAX_RETENTION} backups "
                f"already exist in the current period ({frequency})."
            )
            logger.info(msg)
            return {"status": "skipped", "message": msg}

    try:
        if db_type == "sqlite":
            dest = _sqlite_backup(bdir, tag)
        elif db_type in ("mysql", "mariadb"):
            dest = _mysql_backup(bdir, tag)
        elif db_type == "postgresql":
            dest = _postgresql_backup(bdir, tag)
        else:
            return {"status": "error", "message": f"Motor de BD desconocido: {db_type}"}
    except NotImplementedError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception("Backup failed")
        return {"status": "error", "message": f"Error al crear salva: {e}"}

    _enforce_retention(bdir)

    return {
        "status": "success",
        "message": f"Salva creada correctamente: {dest.name}",
        "filename": dest.name,
    }


def delete_backup(filename: str) -> dict:
    """Delete a specific backup file by name."""
    cfg = load_config()
    try:
        bdir = _backup_dir(cfg)
    except OSError as e:
        return {"status": "error", "message": str(e)}

    target = _get_safe_backup_path(bdir, filename)
    if target is None:
        return {"status": "error", "message": _("Nombre de archivo inválido")}

    if not target.exists():
        return {"status": "error", "message": _("La salva no existe")}

    target.unlink()
    logger.info(f"Backup deleted: {target.name}")
    return {"status": "success", "message": f"Salva eliminada: {target.name}"}


def get_backup_file_path(filename: str) -> Path | None:
    """Return the absolute Path for a backup file, or None if invalid/missing."""
    cfg = load_config()
    try:
        bdir = _backup_dir(cfg)
    except OSError:
        return None

    target = _get_safe_backup_path(bdir, filename)
    if target is None or not target.exists():
        return None

    return target
