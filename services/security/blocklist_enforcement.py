"""
Blocklist enforcement service.

Contains all business logic for enabling/disabling Squid blocklists,
including file management, ACL manipulation, URL validation, and
enforcement state queries.  Previously these were private helpers
inside the admin blueprint.
"""

import hashlib
import os
import re
import stat
from urllib.parse import urlparse

from loguru import logger

from database.database import get_session
from database.models.models import BlacklistDomain
from services.squid.acls_service import (
    BLOCKLIST_PREFIX,
    _get_blocklists_dir,
    _sanitize_filename,
    _write_domains_file,
)
from services.squid.http_access_service import (
    add_http_deny_blocklist,
    remove_http_deny_blocklist,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCKLIST_ACL_NAME = "squidstats_blocklist"


# ---------------------------------------------------------------------------
# URL / filename validation helpers
# ---------------------------------------------------------------------------


def validate_source_url(source_url: str | None) -> bool:
    """Validate that *source_url* is a well-formed URL.

    ``None`` is allowed (represents the custom/manual list).
    """
    if not source_url:
        return True

    parsed = urlparse(source_url)
    if not (parsed.scheme and parsed.netloc):
        return False
    if ".." in source_url or source_url.startswith("/") or "\\" in source_url:
        return False
    if any(c in source_url for c in ["\x00", "\n", "\r", "\t"]):
        return False
    if len(source_url) > 2048:
        return False
    return True


def is_allowed_blocklist_filename(filename: str) -> bool:
    """Allow only expected generated blocklist filenames."""
    if not filename:
        return False
    if os.path.basename(filename) != filename:
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    pattern = rf"^{re.escape(BLOCKLIST_PREFIX)}(?:custom|[a-f0-9]{{64}})\.txt$"
    return bool(re.fullmatch(pattern, filename))


def build_blocklist_filename(source_url: str | None) -> str:
    """Build a deterministic safe filename for a blocklist source URL."""
    if source_url is None:
        filename = f"{BLOCKLIST_PREFIX}custom.txt"
    else:
        if not validate_source_url(source_url):
            raise ValueError("Invalid source URL")
        digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest().lower()
        filename = f"{BLOCKLIST_PREFIX}{digest}.txt"

    if not is_allowed_blocklist_filename(filename):
        raise ValueError("Invalid blocklist filename")
    return filename


def resolve_safe_blocklist_path(base_dir: str, filename: str) -> str | None:
    """Resolve and validate a blocklist file path to prevent path traversal.

    Returns the safe path or ``None`` if traversal is detected.
    """
    if not is_allowed_blocklist_filename(filename):
        return None

    base_dir = os.path.realpath(base_dir)
    candidate = os.path.realpath(os.path.join(base_dir, filename))

    try:
        if os.path.commonpath([base_dir, candidate]) != base_dir:
            return None
    except ValueError:
        return None
    return candidate


# ---------------------------------------------------------------------------
# Enforcement state queries
# ---------------------------------------------------------------------------


def get_enforced_blocklist_urls(cm) -> set[str]:
    """Return the set of source_url values currently enforced as Squid ACLs.

    Custom lists are represented by the sentinel ``__custom__``.
    """
    enforced: set[str] = set()
    content = _read_acl_content(cm)
    if not content:
        return enforced

    url_to_filename = _build_url_to_filename_map()

    for line in content.split("\n"):
        stripped = line.strip()
        if not _is_blocklist_acl_line(stripped):
            continue
        start = stripped.find('"')
        end = stripped.rfind('"')
        if start != -1 and end > start:
            filepath = stripped[start + 1 : end]
            fname = os.path.basename(filepath)
            if fname == f"{BLOCKLIST_PREFIX}custom.txt":
                enforced.add("__custom__")
            else:
                source_url = url_to_filename.get(fname)
                if source_url:
                    enforced.add(source_url)
    return enforced


def get_enforced_blocklist_paths(cm) -> dict[str, str]:
    """Return validated enforced blocklist paths keyed by filename."""
    enforced_paths: dict[str, str] = {}
    blocklists_dir = _get_blocklists_dir(cm)
    content = _read_acl_content(cm)
    if not content:
        return enforced_paths

    for line in content.split("\n"):
        stripped = line.strip()
        if not _is_blocklist_acl_line(stripped):
            continue
        match = re.search(r"""dstdomain\s+["']([^"']+)["']""", stripped)
        if not match:
            continue
        filepath = match.group(1)
        filename = os.path.basename(filepath)
        safe_path = resolve_safe_blocklist_path(blocklists_dir, filename)
        if safe_path:
            enforced_paths[filename] = safe_path
    return enforced_paths


# ---------------------------------------------------------------------------
# Enable / disable single blocklist
# ---------------------------------------------------------------------------


def enable_single_blocklist(source_url: str | None, cm) -> tuple[bool, str]:
    """Enable Squid enforcement for a single blocklist (by source_url).

    Writes the domain file, adds the ACL directive, and ensures the
    ``http_access deny`` rule exists.
    """
    if source_url is not None and not validate_source_url(source_url):
        return False, "URL de fuente inválida"

    label = source_url if source_url else "custom"
    domains = _fetch_domains_for_source(source_url)
    if domains is None:
        return False, "Error al consultar dominios"
    if not domains:
        return False, f"No hay dominios activos para '{label}'"

    try:
        filename = build_blocklist_filename(source_url)
    except ValueError:
        return False, "URL de fuente inválida"

    blocklists_dir = _get_blocklists_dir(cm)
    safe_path = resolve_safe_blocklist_path(blocklists_dir, filename)
    if not safe_path:
        logger.error("Path traversal blocked for source: %s", label)
        return False, f"Nombre de archivo inválido para: '{label}'"

    ok, written_count = _write_domains_file(safe_path, domains, blocklists_dir)
    if not ok:
        return False, f"Error escribiendo archivo para '{label}'"

    acl_line = f'acl {BLOCKLIST_ACL_NAME} dstdomain "{safe_path}"'
    comment_line = f"# Blocklist: {label} ({written_count} dominios)"

    try:
        _upsert_acl_line(cm, acl_line, comment_line)
    except Exception:
        logger.exception("Error agregando ACL para blocklist individual")
        return False, "Error al agregar ACL"

    ok, msg = add_http_deny_blocklist(BLOCKLIST_ACL_NAME, cm)
    if not ok:
        return False, msg

    return True, f"Blocklist '{label}' activada con {len(domains)} dominios"


def disable_single_blocklist(source_url: str | None, cm) -> tuple[bool, str]:
    """Disable Squid enforcement for a single blocklist.

    Removes the ACL line, deletes the domain file, and if no blocklist
    ACLs remain, removes the ``http_access deny`` rule.
    """
    if source_url is not None:
        if not isinstance(source_url, str):
            return False, "Formato de URL inválido"
        if not validate_source_url(source_url):
            return False, "URL de fuente inválida"

    label = source_url if source_url else "custom"

    try:
        candidate_filename = build_blocklist_filename(source_url)
    except ValueError:
        return False, "URL de fuente inválida"

    enforced_paths = get_enforced_blocklist_paths(cm)
    safe_path = enforced_paths.get(candidate_filename)
    if not safe_path:
        return False, f"Blocklist '{label}' no está activada"

    acl_line = f'acl {BLOCKLIST_ACL_NAME} dstdomain "{safe_path}"'

    try:
        _remove_acl_line(cm, acl_line)
    except Exception:
        logger.exception("Error eliminando ACL de blocklist individual")
        return False, "Error al eliminar ACL"

    if os.path.isfile(safe_path):
        try:
            st = os.lstat(safe_path)
            if not stat.S_ISREG(st.st_mode):
                logger.error(f"Archivo no regular: {safe_path}")
                return False, "Archivo no regular"
            os.remove(safe_path)
        except OSError:
            logger.exception(f"Error eliminando archivo: {safe_path}")

    remaining = get_enforced_blocklist_urls(cm)
    if not remaining:
        remove_http_deny_blocklist(BLOCKLIST_ACL_NAME, cm)

    return True, f"Blocklist '{label}' desactivada"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_acl_content(cm) -> str | None:
    """Read ACL content respecting modular vs monolithic config."""
    if cm.is_modular:
        return cm.read_modular_config("100_acls.conf")
    return cm.config_content


def _is_blocklist_acl_line(stripped: str) -> bool:
    """Check if a stripped config line is a blocklist ACL directive."""
    return (
        stripped.startswith(f"acl {BLOCKLIST_ACL_NAME} ")
        and "dstdomain" in stripped
        and BLOCKLIST_PREFIX in stripped
    )


def _build_url_to_filename_map() -> dict[str, str]:
    """Pre-fetch all source URLs from DB and map filenames -> source_url."""
    session = get_session()
    try:
        url_to_filename: dict[str, str] = {}
        urls = (
            session.query(BlacklistDomain.source_url)
            .filter(BlacklistDomain.source_url.isnot(None))
            .distinct()
            .all()
        )
        for (url,) in urls:
            try:
                url_to_filename[build_blocklist_filename(url)] = url
            except ValueError:
                logger.warning("Skipping invalid blacklist source_url in DB mapping")
            url_to_filename[_sanitize_filename(url)] = url
        return url_to_filename
    finally:
        session.close()


def _fetch_domains_for_source(source_url: str | None) -> list[str] | None:
    """Query active domains for a given source_url (or custom if None)."""
    session = get_session()
    try:
        if source_url:
            rows = (
                session.query(BlacklistDomain.domain)
                .filter(
                    BlacklistDomain.active == 1,
                    BlacklistDomain.source_url == source_url,
                )
                .order_by(BlacklistDomain.domain)
                .all()
            )
        else:
            rows = (
                session.query(BlacklistDomain.domain)
                .filter(
                    BlacklistDomain.active == 1,
                    BlacklistDomain.source_url.is_(None),
                )
                .order_by(BlacklistDomain.domain)
                .all()
            )
        return [d[0] for d in rows]
    except Exception:
        logger.exception("Error consultando dominios para activar blocklist")
        return None
    finally:
        session.close()


def _upsert_acl_line(cm, acl_line: str, comment_line: str):
    """Add or replace a blocklist ACL line in config (modular or monolithic)."""
    if cm.is_modular:
        acl_content = cm.read_modular_config("100_acls.conf")
        if acl_content is None:
            raise RuntimeError("No se pudo leer la config modular")
        lines = _filter_acl_lines(acl_content.split("\n"), acl_line, comment_line)
        lines.append(comment_line)
        lines.append(acl_line)
        if not cm.save_modular_config("100_acls.conf", "\n".join(lines)):
            raise RuntimeError("Error guardando ACL en config modular")
    else:
        lines = _filter_acl_lines(cm.config_content.split("\n"), acl_line, comment_line)
        acl_section_end = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("acl "):
                acl_section_end = i
        if acl_section_end != -1:
            lines.insert(acl_section_end + 1, comment_line)
            lines.insert(acl_section_end + 2, acl_line)
        else:
            lines.append(comment_line)
            lines.append(acl_line)
        cm.save_config("\n".join(lines))


def _remove_acl_line(cm, acl_line: str):
    """Remove a blocklist ACL line from config (modular or monolithic)."""
    if cm.is_modular:
        acl_content = cm.read_modular_config("100_acls.conf")
        if acl_content is not None:
            new_lines = _strip_acl_and_comment(acl_content.split("\n"), acl_line)
            cm.save_modular_config("100_acls.conf", "\n".join(new_lines))

    # Always update monolithic config as well
    lines = cm.config_content.split("\n")
    new_lines = _strip_acl_and_comment(lines, acl_line)
    cm.save_config("\n".join(new_lines))


def _filter_acl_lines(lines: list[str], acl_line: str, comment_line: str) -> list[str]:
    """Remove existing occurrences of an ACL line and its comment."""
    lines = [
        ln
        for ln in lines
        if not (ln.strip() == acl_line or ln.strip() == acl_line.replace('"', "'"))
    ]
    lines = [ln for ln in lines if not ln.strip() == comment_line]
    return lines


def _strip_acl_and_comment(lines: list[str], acl_line: str) -> list[str]:
    """Strip an ACL line and the ``# Blocklist:`` comment above it."""
    new_lines: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped == acl_line or stripped == acl_line.replace('"', "'"):
            if new_lines and new_lines[-1].strip().startswith("# Blocklist:"):
                new_lines.pop()
            continue
        new_lines.append(ln)
    return new_lines
