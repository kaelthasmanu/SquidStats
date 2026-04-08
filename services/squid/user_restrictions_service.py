"""
User restrictions service.

Provides block/unblock and throttle/unthrottle operations for active proxy
users. Each operation persists to the database and updates the corresponding
Squid config file so that the restriction survives restarts.

Block mechanism:
  - Writes active blocked IPs to: <config_dir>/squidstats_restrictions/squidstats_blocked_ips.txt
  - ACL: acl squidstats_blocked src "<file>"
  - HTTP access: http_access deny squidstats_blocked  (inserted before first allow)

Throttle mechanism (per delay pool):
  - Writes active throttled IPs to: <config_dir>/squidstats_restrictions/squidstats_throttle_pool_<N>.txt
  - ACL: acl squidstats_throttle_<N> src "<file>"
  - Delay access: delay_access <N> allow squidstats_throttle_<N>  (inserted before deny all)
"""

import ipaddress
import os
import re

from loguru import logger

from database.models.models import BlockedUser, ThrottledUser
from services.squid.http_access_service import add_http_deny_blocklist

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCKED_ACL_NAME = "squidstats_blocked"
BLOCKED_IPS_FILENAME = "squidstats_blocked_ips.txt"

THROTTLE_ACL_PREFIX = "squidstats_throttle_"
THROTTLE_IPS_PREFIX = "squidstats_throttle_pool_"
RESTRICTIONS_DIR_NAME = "squidstats_restrictions"

# Allowed filename pattern for restrictions files (path traversal prevention)
_SAFE_FILENAME_RE = re.compile(r"^squidstats_[a-z0-9_]+\.txt$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_ip(ip: str) -> bool:
    """Return True only if *ip* is a valid IPv4 or IPv6 address."""
    if not ip or len(ip) > 45:
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def _validate_filename(filename: str) -> bool:
    return bool(_SAFE_FILENAME_RE.fullmatch(filename))


def _get_restrictions_dir(cm) -> str:
    """Return (and create if needed) the restrictions subdirectory."""
    restrictions_dir = os.path.join(cm.config_dir, RESTRICTIONS_DIR_NAME)
    os.makedirs(restrictions_dir, exist_ok=True)
    return restrictions_dir


def _safe_path(directory: str, filename: str) -> str | None:
    """Resolve path under directory, rejecting traversal attempts."""
    if not _validate_filename(filename):
        logger.error("Invalid restrictions filename: %s", filename)
        return None
    safe_dir = os.path.realpath(directory)
    candidate = os.path.realpath(os.path.join(directory, filename))
    if not candidate.startswith(safe_dir + os.sep):
        logger.error("Path traversal blocked: %s is outside %s", candidate, safe_dir)
        return None
    return candidate


def _write_ip_file(filepath: str, ips: list[str], expected_dir: str) -> bool:
    """Write a list of IPs to a flat file (one per line), with path-traversal protection."""
    safe_dir = os.path.realpath(expected_dir)
    safe_path = os.path.realpath(filepath)
    if not safe_path.startswith(safe_dir + os.sep):
        logger.error("Path traversal blocked writing IP file: %s", filepath)
        return False
    try:
        with open(safe_path, "w", encoding="utf-8") as f:
            for ip in ips:
                f.write(ip + "\n")
        return True
    except Exception:
        logger.exception("Error writing IP file: %s", filepath)
        return False


def _blocked_ips_filepath(cm) -> str:
    return os.path.join(_get_restrictions_dir(cm), BLOCKED_IPS_FILENAME)


def _throttled_ips_filepath(cm, pool_number: int) -> str:
    return os.path.join(
        _get_restrictions_dir(cm), f"{THROTTLE_IPS_PREFIX}{pool_number}.txt"
    )


# ---------------------------------------------------------------------------
# ACL helpers
# ---------------------------------------------------------------------------


def _add_acl_src_file(acl_name: str, filepath: str, cm) -> bool:
    """Add `acl <acl_name> src "<filepath>"` idempotently."""
    acl_line = f'acl {acl_name} src "{filepath}"'
    comment = f"# SquidStats managed: {acl_name}"
    try:
        if cm.is_modular:
            content = cm.read_modular_config("100_acls.conf")
            if content is not None:
                if acl_line in content:
                    return True
                lines = content.split("\n")
                lines.append(comment)
                lines.append(acl_line)
                return bool(cm.save_modular_config("100_acls.conf", "\n".join(lines)))

        if acl_line in cm.config_content:
            return True
        lines = cm.config_content.split("\n")
        lines.append(comment)
        lines.append(acl_line)
        return bool(cm.save_config("\n".join(lines)))
    except Exception:
        logger.exception("Error adding ACL src: %s", acl_name)
        return False


def _remove_acl_src(acl_name: str, cm) -> bool:
    """Remove the ACL src directive for *acl_name*."""
    comment = f"# SquidStats managed: {acl_name}"
    try:
        if cm.is_modular:
            content = cm.read_modular_config("100_acls.conf")
            if content is not None:
                lines = content.split("\n")
                new_lines = _filter_acl_lines(lines, acl_name, comment)
                return bool(
                    cm.save_modular_config("100_acls.conf", "\n".join(new_lines))
                )

        lines = cm.config_content.split("\n")
        new_lines = _filter_acl_lines(lines, acl_name, comment)
        return bool(cm.save_config("\n".join(new_lines)))
    except Exception:
        logger.exception("Error removing ACL src: %s", acl_name)
        return False


def _filter_acl_lines(lines: list[str], acl_name: str, comment: str) -> list[str]:
    """Strip the ACL line and its preceding comment from *lines*."""
    result = []
    skip_comment = False
    for line in lines:
        stripped = line.strip()
        if stripped == comment:
            skip_comment = True
            continue
        if skip_comment and stripped.startswith(f"acl {acl_name} src"):
            skip_comment = False
            continue
        skip_comment = False
        result.append(line)
    return result


# ---------------------------------------------------------------------------
# Delay-access helpers
# ---------------------------------------------------------------------------


def _add_delay_access(pool_number: int, acl_name: str, cm) -> bool:
    """Add `delay_access <N> allow <acl_name>` before any existing deny all for pool N."""
    rule = f"delay_access {pool_number} allow {acl_name}"
    deny_all = f"delay_access {pool_number} deny all"
    comment = f"# SquidStats managed: throttle pool {pool_number}"

    try:
        if cm.is_modular:
            content = cm.read_modular_config("110_delay_pools.conf")
            if content is not None:
                if rule in content:
                    return True
                lines = content.split("\n")
                insert_idx = _find_delay_insert_index(lines, pool_number, deny_all)
                lines.insert(insert_idx, rule)
                lines.insert(insert_idx, comment)
                return bool(
                    cm.save_modular_config("110_delay_pools.conf", "\n".join(lines))
                )

        if rule in cm.config_content:
            return True
        lines = cm.config_content.split("\n")
        insert_idx = _find_delay_insert_index(lines, pool_number, deny_all)
        lines.insert(insert_idx, rule)
        lines.insert(insert_idx, comment)
        return bool(cm.save_config("\n".join(lines)))
    except Exception:
        logger.exception("Error adding delay_access for pool %s", pool_number)
        return False


def _find_delay_insert_index(lines: list[str], pool_number: int, deny_all: str) -> int:
    """Find the index to insert the new delay_access rule.

    Prefers inserting before the pool's existing `deny all`.
    Falls back to inserting after the pool's `delay_parameters` line.
    Falls back to end of file.
    """
    after_params = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == deny_all:
            return i
        if (
            stripped.startswith(f"delay_parameters {pool_number} ")
            and after_params == len(lines)
        ):
            after_params = i + 1
    return after_params


# ---------------------------------------------------------------------------
# Sync helpers (file reconstruction from DB)
# ---------------------------------------------------------------------------


def _sync_blocked_file(db, cm) -> bool:
    active_ips = [r.ip for r in db.query(BlockedUser).filter_by(active=1).all()]
    filepath = _blocked_ips_filepath(cm)
    restrictions_dir = _get_restrictions_dir(cm)
    return _write_ip_file(filepath, active_ips, restrictions_dir)


def _sync_throttled_file(db, cm, pool_number: int) -> bool:
    active_ips = [
        r.ip
        for r in db.query(ThrottledUser)
        .filter_by(pool_number=pool_number, active=1)
        .all()
    ]
    filepath = _throttled_ips_filepath(cm, pool_number)
    restrictions_dir = _get_restrictions_dir(cm)
    return _write_ip_file(filepath, active_ips, restrictions_dir)


# ---------------------------------------------------------------------------
# Public API: Block / Unblock
# ---------------------------------------------------------------------------


def block_user(username: str, ip: str, db, cm) -> tuple[bool, str]:
    """Block *ip* in Squid and persist to DB.

    Idempotent ACL/http_access additions ensure the Squid directives are
    only written once regardless of how many users are blocked.
    """
    if not _validate_ip(ip):
        return False, "Dirección IP inválida"

    existing = db.query(BlockedUser).filter_by(ip=ip, active=1).first()
    if existing:
        return False, f"La IP {ip} ya está bloqueada"

    record = BlockedUser(username=username, ip=ip, active=1)
    try:
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error saving BlockedUser to DB")
        return False, "Error al guardar en la base de datos"

    if not _sync_blocked_file(db, cm):
        db.delete(record)
        db.commit()
        return False, "Error al escribir el archivo de IPs bloqueadas"

    filepath = _blocked_ips_filepath(cm)
    if not _add_acl_src_file(BLOCKED_ACL_NAME, filepath, cm):
        logger.warning("Could not add squidstats_blocked ACL; DB entry saved")
    if not add_http_deny_blocklist(BLOCKED_ACL_NAME, cm):
        logger.warning("Could not add http_access deny squidstats_blocked; DB entry saved")

    return True, f"Usuario {username} ({ip}) bloqueado"


def unblock_user(username: str, ip: str, db, cm) -> tuple[bool, str]:
    """Remove the block for *ip*."""
    if not _validate_ip(ip):
        return False, "Dirección IP inválida"

    record = db.query(BlockedUser).filter_by(ip=ip, active=1).first()
    if not record:
        return False, f"No se encontró bloqueo activo para IP {ip}"

    record.active = 0
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error updating BlockedUser in DB")
        return False, "Error al actualizar la base de datos"

    _sync_blocked_file(db, cm)
    return True, f"Usuario {username} ({ip}) desbloqueado"


# ---------------------------------------------------------------------------
# Public API: Throttle / Unthrottle
# ---------------------------------------------------------------------------


def throttle_user(username: str, ip: str, pool_number: int, db, cm) -> tuple[bool, str]:
    """Assign *ip* to *pool_number* to apply bandwidth throttling.

    Requires the delay pool to already exist in the Squid configuration.
    """
    if not _validate_ip(ip):
        return False, "Dirección IP inválida"

    pools = cm.get_delay_pools()
    pool_numbers = {int(p["pool_number"]) for p in pools if "pool_number" in p}
    if pool_number not in pool_numbers:
        return False, f"El delay pool #{pool_number} no existe en la configuración"

    existing = db.query(ThrottledUser).filter_by(ip=ip, active=1).first()
    if existing:
        return False, f"La IP {ip} ya tiene velocidad reducida (pool #{existing.pool_number})"

    record = ThrottledUser(username=username, ip=ip, pool_number=pool_number, active=1)
    try:
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error saving ThrottledUser to DB")
        return False, "Error al guardar en la base de datos"

    if not _sync_throttled_file(db, cm, pool_number):
        db.delete(record)
        db.commit()
        return False, "Error al escribir el archivo de IPs con velocidad reducida"

    acl_name = f"{THROTTLE_ACL_PREFIX}{pool_number}"
    filepath = _throttled_ips_filepath(cm, pool_number)
    if not _add_acl_src_file(acl_name, filepath, cm):
        logger.warning("Could not add throttle ACL; DB entry saved")
    if not _add_delay_access(pool_number, acl_name, cm):
        logger.warning("Could not add delay_access rule; DB entry saved")

    return True, f"Velocidad reducida para {username} ({ip}) en pool #{pool_number}"


def unthrottle_user(username: str, ip: str, db, cm) -> tuple[bool, str]:
    """Remove the throttle for *ip*."""
    if not _validate_ip(ip):
        return False, "Dirección IP inválida"

    record = db.query(ThrottledUser).filter_by(ip=ip, active=1).first()
    if not record:
        return False, f"No se encontró throttle activo para IP {ip}"

    pool_number = record.pool_number
    record.active = 0
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error updating ThrottledUser in DB")
        return False, "Error al actualizar la base de datos"

    _sync_throttled_file(db, cm, pool_number)
    return True, f"Velocidad restaurada para {username} ({ip})"


# ---------------------------------------------------------------------------
# Startup sync
# ---------------------------------------------------------------------------


def sync_restrictions(db, cm) -> None:
    """Rebuild restriction files from DB on startup.

    Ensures Squid config ACLs and files are consistent with DB records even
    after a server restart or manual file deletion.
    """
    # Blocked users
    _sync_blocked_file(db, cm)
    active_blocked = db.query(BlockedUser).filter_by(active=1).count()
    if active_blocked > 0:
        filepath = _blocked_ips_filepath(cm)
        _add_acl_src_file(BLOCKED_ACL_NAME, filepath, cm)
        add_http_deny_blocklist(BLOCKED_ACL_NAME, cm)

    # Throttled users (per pool)
    rows = db.query(ThrottledUser.pool_number).filter_by(active=1).distinct().all()
    for (pool_number,) in rows:
        _sync_throttled_file(db, cm, pool_number)
        acl_name = f"{THROTTLE_ACL_PREFIX}{pool_number}"
        filepath = _throttled_ips_filepath(cm, pool_number)
        _add_acl_src_file(acl_name, filepath, cm)
        _add_delay_access(pool_number, acl_name, cm)

    logger.info("User restrictions synchronized to Squid config")


# ---------------------------------------------------------------------------
# Status queries
# ---------------------------------------------------------------------------


def get_user_status(ip: str, db) -> dict:
    """Return current block/throttle status for *ip*."""
    blocked = db.query(BlockedUser).filter_by(ip=ip, active=1).first()
    throttled = db.query(ThrottledUser).filter_by(ip=ip, active=1).first()
    return {
        "ip": ip,
        "blocked": blocked is not None,
        "throttled": throttled is not None,
        "pool_number": throttled.pool_number if throttled else None,
    }
