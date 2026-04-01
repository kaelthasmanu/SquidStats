"""
Backup service for SquidStats databases.

Currently implemented:
  - SQLite

Planned (not yet implemented):
  - MySQL / MariaDB
  - PostgreSQL
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from config import Config

# ─── Constants ────────────────────────────────────────────────────────────────

_CONFIG_FILE = Path(os.path.dirname(os.path.abspath(__file__))) / "backup_config.json"
_MAX_RETENTION = 3

FREQUENCY_CHOICES = {
    "daily_weekly": "Diaria — máx. 3 por semana",
    "daily_monthly": "Diaria — máx. 3 por mes",
}


# ─── Config helpers ───────────────────────────────────────────────────────────


def _default_config() -> dict:
    return {
        "db_type": "sqlite",
        "frequency": "daily_weekly",
        "backup_dir": "/opt/SquidStats/backups",
        "enabled": False,
    }


def load_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE) as f:
                data = json.load(f)
            cfg = _default_config()
            cfg.update(data)
            return cfg
        except Exception as e:
            logger.warning(f"Could not read backup config, using defaults: {e}")
    return _default_config()


def save_config(cfg: dict) -> None:
    allowed_keys = {"db_type", "frequency", "backup_dir", "enabled"}
    safe = {k: v for k, v in cfg.items() if k in allowed_keys}
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_FILE, "w") as f:
        json.dump(safe, f, indent=2)


# ─── Backup directory helpers ─────────────────────────────────────────────────


def _backup_dir(cfg: dict) -> Path:
    p = Path(cfg.get("backup_dir", "/opt/SquidStats/backups"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _list_backup_files(backup_dir: Path) -> list[Path]:
    """Return backup files sorted newest-first."""
    files = sorted(
        backup_dir.glob("squidstats_backup_*.sqlite3"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return files


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
    bdir = _backup_dir(cfg)
    result = []
    for f in _list_backup_files(bdir):
        stat = f.stat()
        created = datetime.fromtimestamp(stat.st_mtime)
        # Detect type from filename suffix
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


# ─── Retention enforcement ────────────────────────────────────────────────────


def _enforce_retention(backup_dir: Path) -> None:
    """Delete oldest backups beyond _MAX_RETENTION."""
    files = _list_backup_files(backup_dir)
    excess = files[_MAX_RETENTION:]
    for f in excess:
        try:
            f.unlink()
            logger.info(f"Backup retention: removed old backup {f.name}")
        except Exception as e:
            logger.warning(f"Could not remove old backup {f.name}: {e}")


# ─── Period quota check ───────────────────────────────────────────────────────


def _count_backups_in_period(backup_dir: Path, frequency: str) -> int:
    """Count how many auto-backups exist within the current period window."""
    files = _list_backup_files(backup_dir)
    now = datetime.now()
    count = 0
    for f in files:
        if "_auto_" not in f.name:
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if frequency == "daily_weekly":
            # Same ISO week
            if mtime.isocalendar()[1] == now.isocalendar()[1] and mtime.year == now.year:
                count += 1
        else:  # daily_monthly
            if mtime.month == now.month and mtime.year == now.year:
                count += 1
    return count


# ─── SQLite backup ────────────────────────────────────────────────────────────


def _sqlite_backup(backup_dir: Path, tag: str) -> Path:
    """Perform an online SQLite backup using sqlite3.Connection.backup()."""
    db_url = Config.DATABASE_URL
    parsed = urlparse(db_url)

    # urlparse: sqlite:///path  →  path='' netloc='', or path='/abs'
    db_path = parsed.path
    if not db_path or db_path == "/":
        # Handle sqlite:///relative or sqlite:///opt/…
        db_path = db_url.replace("sqlite:///", "")

    db_path = Path(db_path)
    if not db_path.is_absolute():
        # Relative to the project root
        project_root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
        db_path = project_root / db_path

    if not db_path.exists():
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

    logger.info(f"SQLite backup created: {dest.name} ({_human_size(dest.stat().st_size)})")
    return dest


# ─── MySQL / MariaDB backup (not yet implemented) ─────────────────────────────


def _mysql_backup(backup_dir: Path, tag: str) -> Path:
    raise NotImplementedError(
        "MySQL/MariaDB backup is not yet implemented. "
        "Planned: use mysqldump via subprocess."
    )


# ─── PostgreSQL backup (not yet implemented) ──────────────────────────────────


def _postgresql_backup(backup_dir: Path, tag: str) -> Path:
    raise NotImplementedError(
        "PostgreSQL backup is not yet implemented. "
        "Planned: use pg_dump via subprocess."
    )


# ─── Public API ───────────────────────────────────────────────────────────────


def run_backup(is_auto: bool = False) -> dict:
    """
    Execute a database backup according to the current configuration.

    Returns a dict with keys: status ('success'|'error'), message, filename (on success).
    """
    cfg = load_config()
    db_type = cfg.get("db_type", "sqlite").lower()
    frequency = cfg.get("frequency", "daily_weekly")
    bdir = _backup_dir(cfg)
    tag = "auto" if is_auto else "manual"

    # For auto backups: respect the per-period quota before running
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
    # Validate filename to prevent path traversal
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return {"status": "error", "message": "Nombre de archivo inválido"}

    cfg = load_config()
    bdir = _backup_dir(cfg)
    target = bdir / filename

    if not target.exists():
        return {"status": "error", "message": "La salva no existe"}

    # Ensure the target is strictly inside the backup directory
    try:
        target.resolve().relative_to(bdir.resolve())
    except ValueError:
        return {"status": "error", "message": "Acceso denegado"}

    target.unlink()
    logger.info(f"Backup deleted: {filename}")
    return {"status": "success", "message": f"Salva eliminada: {filename}"}


def get_backup_file_path(filename: str):
    """Return the absolute Path for a backup file, or None if invalid/missing."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None

    cfg = load_config()
    bdir = _backup_dir(cfg)
    target = bdir / filename

    if not target.exists():
        return None

    try:
        target.resolve().relative_to(bdir.resolve())
    except ValueError:
        return None

    return target
