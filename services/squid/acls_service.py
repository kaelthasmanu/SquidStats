import hashlib
import os
import re

from loguru import logger

from database.database import get_session
from database.models.models import BlacklistDomain

BLOCKLIST_DIR_NAME = "blocklists"
BLOCKLIST_PREFIX = "blocklist_"

# ---------------------------------------------------------------------------
# Domain validation regex (RFC 1123 compatible)
# ---------------------------------------------------------------------------
_VALID_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}$",
    re.IGNORECASE,
)


def sanitize_domain_entry(raw: str) -> str | None:
    """Convert a raw blocklist entry to a clean domain for Squid ``dstdomain``.

    Handles multiple blocklist formats:

    **AdGuard / Adblock Plus (ABP)**:
        ``||example.com^``  →  ``example.com``
        ``||example.com^$third-party``  →  ``example.com``
        ``@@||example.com^``  →  ``None``  (exception / whitelist)

    **Hosts file**:
        ``0.0.0.0 example.com``  →  ``example.com``
        ``127.0.0.1 example.com``  →  ``example.com``

    **Plain domain**:
        ``example.com``  →  ``example.com``

    Lines that are comments, metadata, cosmetic filters, regex rules, or
    contain wildcards are skipped (returns ``None``).

    Returns:
        A clean lowercase domain string, or ``None`` if the line should be
        skipped.
    """
    line = raw.strip()

    # Empty or comment lines
    if not line or line.startswith(("!", "#", "[", "//")):
        return None

    # ABP exception rules (whitelist) — skip
    if line.startswith("@@"):
        return None

    # ABP cosmetic / element hiding filters — skip
    if "##" in line or "#@#" in line or "#?#" in line:
        return None

    # ABP/AdGuard domain rules:  ||domain.com^  or  ||domain.com^$options
    if line.startswith("||"):
        domain = line[2:]  # strip ||
        # Remove trailing ^ and anything after it ($options, etc.)
        domain = domain.split("^")[0]
        # Remove any remaining $ options if no ^ was present
        domain = domain.split("$")[0]
        domain = domain.strip(".")
    else:
        # Skip lines with ABP wildcards or regex
        if "*" in line or line.startswith("/") or "|" in line:
            return None

        # Skip lines with $ modifier without || prefix (e.g., advanced ABP rules)
        if "$" in line and "=" in line:
            return None

        # Hosts file format: "0.0.0.0 example.com" or "127.0.0.1 example.com"
        if " " in line or "\t" in line:
            parts = line.split()
            # Take the last non-comment part
            domain = None
            for part in parts:
                if part.startswith("#"):
                    break
                domain = part
            if domain is None:
                return None
        else:
            domain = line

    # Final cleanup
    domain = domain.lower().strip(".")

    # Remove port if present (e.g., "example.com:443")
    if ":" in domain:
        domain = domain.rsplit(":", 1)[0]

    # Must look like a valid domain
    if not domain or not _VALID_DOMAIN_RE.match(domain):
        return None

    # Reject IP addresses stored as domains
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", domain):
        return None

    return domain


def sanitize_domain_list(raw_domains: list[str]) -> list[str]:
    """Sanitize a list of raw domain entries for Squid compatibility.

    Applies :func:`sanitize_domain_entry` to each entry and returns only
    valid, unique domains in sorted order.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in raw_domains:
        domain = sanitize_domain_entry(raw)
        if domain and domain not in seen:
            seen.add(domain)
            cleaned.append(domain)
    cleaned.sort()
    return cleaned


def add_acl(
    name: str, acl_type: str, values: list, options: list, comment: str, config_manager
) -> tuple[bool, str]:
    if not name or not acl_type or not values:
        return False, "Debe proporcionar nombre, tipo y al menos un valor para la ACL"

    acl_parts = ["acl", name]
    if options:
        acl_parts.extend(options)
    acl_parts.append(acl_type)
    acl_parts.extend(values)
    new_acl = " ".join(acl_parts)

    try:
        if config_manager.is_modular:
            acl_content = config_manager.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                if comment:
                    lines.append(f"# {comment}")
                lines.append(new_acl)
                new_content = "\n".join(lines)
                if config_manager.save_modular_config("100_acls.conf", new_content):
                    return True, f"ACL '{name}' agregada exitosamente"
                else:
                    return False, "Error al guardar la ACL en modular"

        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        acl_section_end = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("acl "):
                acl_section_end = i

        if acl_section_end != -1:
            if comment:
                lines.insert(acl_section_end + 1, f"# {comment}")
                lines.insert(acl_section_end + 2, new_acl)
            else:
                lines.insert(acl_section_end + 1, new_acl)
        else:
            if comment:
                lines.append(f"# {comment}")
            lines.append(new_acl)

        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return True, f"ACL '{name}' agregada exitosamente"
    except Exception:
        logger.exception("Error agregando ACL")
        return False, "Error interno al agregar ACL"


def edit_acl(
    acl_index: int,
    new_name: str,
    acl_type: str,
    values: list,
    options: list,
    comment: str,
    config_manager,
) -> tuple[bool, str]:
    try:
        acls = config_manager.get_acls()
        if not (0 <= acl_index < len(acls)):
            return False, "ACL no encontrada"

        target_acl = acls[acl_index]
        target_line = target_acl["line_number"] - 1

        acl_parts = ["acl", new_name]
        if options:
            acl_parts.extend(options)
        acl_parts.append(acl_type)
        acl_parts.extend(values)
        new_acl_line = " ".join(acl_parts)

        if config_manager.is_modular:
            acl_content = config_manager.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                if 0 <= target_line < len(lines):
                    has_comment = target_line > 0 and lines[
                        target_line - 1
                    ].strip().startswith("#")
                    lines[target_line] = new_acl_line
                    if has_comment:
                        if comment:
                            lines[target_line - 1] = f"# {comment}"
                        else:
                            lines.pop(target_line - 1)
                    else:
                        if comment:
                            lines.insert(target_line, f"# {comment}")
                    new_content = "\n".join(lines)
                    if config_manager.save_modular_config("100_acls.conf", new_content):
                        return True, f"ACL '{new_name}' actualizada exitosamente"
                    else:
                        return False, "Error guardando ACL modular"

        # Fallback to main config
        lines = config_manager.config_content.split("\n")
        if 0 <= target_line < len(lines):
            lines[target_line] = new_acl_line
            if target_line > 0 and lines[target_line - 1].strip().startswith("#"):
                if comment:
                    lines[target_line - 1] = f"# {comment}"
                else:
                    lines.pop(target_line - 1)
            else:
                if comment:
                    lines.insert(target_line, f"# {comment}")
            new_content = "\n".join(lines)
            config_manager.save_config(new_content)
            return True, f"ACL '{new_name}' actualizada exitosamente"
        return False, "Línea de ACL no encontrada"
    except Exception:
        logger.exception("Error editando ACL")
        return False, "Error interno al editar ACL"


def delete_acl(acl_index: int, config_manager) -> tuple[bool, str]:
    try:
        acls = config_manager.get_acls()
        if not (0 <= acl_index < len(acls)):
            return False, "ACL no encontrada"

        acl_to_delete = acls[acl_index]
        target_line = acl_to_delete["line_number"] - 1

        if config_manager.is_modular:
            acl_content = config_manager.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                comment_to_remove = None
                if target_line > 0 and lines[target_line - 1].strip().startswith("#"):
                    comment_to_remove = target_line - 1
                new_lines = []
                for i, line in enumerate(lines):
                    if i == target_line:
                        continue
                    if comment_to_remove is not None and i == comment_to_remove:
                        continue
                    new_lines.append(line)
                new_content = "\n".join(new_lines)
                if config_manager.save_modular_config("100_acls.conf", new_content):
                    return True, f"ACL '{acl_to_delete['name']}' eliminada exitosamente"
                else:
                    return False, "Error al eliminar ACL modular"

        lines = config_manager.config_content.split("\n")
        comment_to_remove = None
        if target_line > 0 and lines[target_line - 1].strip().startswith("#"):
            comment_to_remove = target_line - 1
        new_lines = []
        for i, line in enumerate(lines):
            if i == target_line:
                continue
            if comment_to_remove is not None and i == comment_to_remove:
                continue
            new_lines.append(line)
        new_content = "\n".join(new_lines)
        config_manager.save_config(new_content)
        return True, f"ACL '{acl_to_delete['name']}' eliminada exitosamente"
    except Exception:
        logger.exception("Error eliminando ACL")
        return False, "Error interno al eliminar ACL"


def _sanitize_filename(source_url: str) -> str:
    """Generate a safe filename from a source URL.

    Uses a short hash + a sanitised portion of the URL to keep filenames
    unique and human-readable.
    """
    url_hash = hashlib.md5(source_url.encode()).hexdigest()[:8]
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", source_url.split("//")[-1])[:60]
    return f"{BLOCKLIST_PREFIX}{clean}_{url_hash}.txt"


def _get_blocklists_dir(config_manager) -> str:
    """Return (and create if needed) the blocklists subdirectory."""
    blocklists_dir = os.path.join(config_manager.config_dir, BLOCKLIST_DIR_NAME)
    os.makedirs(blocklists_dir, exist_ok=True)
    return blocklists_dir


def _write_domains_file(filepath: str, domains: list[str]) -> tuple[bool, int]:
    """Write a list of domains to a flat file for Squid ``dstdomain``.

    Domains are sanitized through :func:`sanitize_domain_list` to ensure
    AdGuard/ABP format entries are converted to plain domains.

    Returns:
        ``(success, written_count)`` tuple.
    """
    try:
        clean = sanitize_domain_list(domains)
        if not clean:
            logger.warning(
                f"No valid domains remaining after sanitization for {filepath}"
            )
            return False, 0
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(clean) + "\n")
        return True, len(clean)
    except Exception:
        logger.exception(f"Error escribiendo archivo de blocklist: {filepath}")
        return False, 0


def _remove_old_blocklist_acls(lines: list[str], acl_name: str) -> list[str]:
    """Remove existing blocklist ACL lines and their comments for *acl_name*."""
    filtered: list[str] = []
    skip_comment = False
    for _i, line in enumerate(lines):
        stripped = line.strip()
        is_blocklist_acl = (
            stripped.startswith(f"acl {acl_name} ")
            and "dstdomain" in stripped
            and BLOCKLIST_PREFIX in stripped
        )
        if is_blocklist_acl:
            # Also remove the comment immediately above if it's ours
            if filtered and filtered[-1].strip().startswith("# Blocklist"):
                filtered.pop()
            continue
        # Remove standalone blocklist comment lines that precede a removed ACL
        if skip_comment:
            skip_comment = False
            continue
        filtered.append(line)
    return filtered


def _build_acl_lines(acl_name: str, file_paths: list[tuple[str, str, int]]) -> list[str]:
    """Build comment + acl directive lines for each blocklist file.

    *file_paths* is a list of ``(label, filepath, domain_count)`` tuples.
    """
    new_lines: list[str] = []
    for label, path, count in file_paths:
        new_lines.append(f"# Blocklist: {label} ({count} dominios)")
        new_lines.append(f'acl {acl_name} dstdomain "{path}"')
    return new_lines


def add_acl_blocklist(
    acl_name: str, config_manager
) -> tuple[bool, str]:
    """Create dstdomain ACLs backed by files with active blacklist domains.

    One file is created **per source list** (``source_url``).  Domains that
    have no ``source_url`` (e.g. custom/manual entries) are grouped into a
    single ``blocklist_custom.txt`` file.

    In Squid, multiple ``acl`` directives with the same name are merged, so
    all files end up being evaluated as a single logical ACL.

    Supports both modular (``100_acls.conf``) and monolithic squid.conf.

    Args:
        acl_name: Name for the ACL (e.g. ``blocklist``).
        config_manager: A :class:`SquidConfigManager` instance.

    Returns:
        ``(success, message)`` tuple.
    """
    if not acl_name:
        return False, "Debe proporcionar un nombre para la ACL de blocklist"

    # ------------------------------------------------------------------
    # 1. Fetch active domains grouped by source_url
    # ------------------------------------------------------------------
    session = get_session()
    try:
        rows = (
            session.query(BlacklistDomain.domain, BlacklistDomain.source_url)
            .filter(BlacklistDomain.active == 1)
            .order_by(BlacklistDomain.source_url, BlacklistDomain.domain)
            .all()
        )
    except Exception:
        logger.exception("Error obteniendo dominios de blacklist desde la DB")
        return False, "Error al obtener dominios de la base de datos"
    finally:
        session.close()

    if not rows:
        return False, "No hay dominios activos en la blacklist para agregar"

    # Group domains by source_url (None goes to "custom")
    groups: dict[str | None, list[str]] = {}
    for domain, source_url in rows:
        groups.setdefault(source_url, []).append(domain)

    # ------------------------------------------------------------------
    # 2. Write one file per source list
    # ------------------------------------------------------------------
    blocklists_dir = _get_blocklists_dir(config_manager)

    # file_info: list of (label, filepath, count) for building ACL lines
    file_info: list[tuple[str, str, int]] = []
    total_domains = 0

    for source_url, domains in groups.items():
        if source_url:
            filename = _sanitize_filename(source_url)
            label = source_url
        else:
            filename = f"{BLOCKLIST_PREFIX}custom.txt"
            label = "custom"

        filepath = os.path.join(blocklists_dir, filename)
        ok, written_count = _write_domains_file(filepath, domains)
        if not ok:
            return False, f"Error al escribir archivo de blocklist para: {label}"

        file_info.append((label, filepath, written_count))
        total_domains += written_count
        logger.info(
            f"Blocklist '{label}' escrita en {filepath} con {written_count} dominios "
            f"({len(domains)} entradas originales)"
        )

    # ------------------------------------------------------------------
    # 3. Update Squid config with ACL directives
    # ------------------------------------------------------------------
    new_acl_lines = _build_acl_lines(acl_name, file_info)

    try:
        if config_manager.is_modular:
            acl_content = config_manager.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                lines = _remove_old_blocklist_acls(lines, acl_name)
                lines.extend(new_acl_lines)
                new_content = "\n".join(lines)
                if config_manager.save_modular_config("100_acls.conf", new_content):
                    return (
                        True,
                        f"ACL blocklist '{acl_name}' creada con {total_domains} dominios "
                        f"en {len(file_info)} lista(s)",
                    )
                else:
                    return False, "Error al guardar la ACL blocklist en config modular"

        # Fallback: monolithic squid.conf
        lines = config_manager.config_content.split("\n")
        lines = _remove_old_blocklist_acls(lines, acl_name)

        acl_section_end = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("acl "):
                acl_section_end = i

        if acl_section_end != -1:
            for offset, acl_line in enumerate(new_acl_lines):
                lines.insert(acl_section_end + 1 + offset, acl_line)
        else:
            lines.extend(new_acl_lines)

        new_content = "\n".join(lines)
        config_manager.save_config(new_content)
        return (
            True,
            f"ACL blocklist '{acl_name}' creada con {total_domains} dominios "
            f"en {len(file_info)} lista(s)",
        )
    except Exception:
        logger.exception("Error agregando ACL blocklist")
        return False, "Error interno al agregar ACL blocklist"


def remove_acl_blocklist(
    acl_name: str, config_manager
) -> tuple[bool, str]:
    """Remove all blocklist ACL directives and their domain files.

    1. Remove all ``acl <acl_name> dstdomain …blocklist_…`` lines from Squid
       config (modular or monolithic).
    2. Delete every ``blocklist_*.txt`` file from the blocklists directory.

    Args:
        acl_name: Name of the blocklist ACL to remove.
        config_manager: A :class:`SquidConfigManager` instance.

    Returns:
        ``(success, message)`` tuple.
    """
    if not acl_name:
        return False, "Debe proporcionar el nombre de la ACL de blocklist"

    errors: list[str] = []

    # ------------------------------------------------------------------
    # 1. Remove ACL directives from Squid config
    # ------------------------------------------------------------------
    try:
        if config_manager.is_modular:
            acl_content = config_manager.read_modular_config("100_acls.conf")
            if acl_content is not None:
                lines = acl_content.split("\n")
                cleaned = _remove_old_blocklist_acls(lines, acl_name)
                new_content = "\n".join(cleaned)
                if not config_manager.save_modular_config("100_acls.conf", new_content):
                    errors.append("Error guardando config modular de ACLs")
            # Even if modular, also clean main config as a safety measure

        # Clean main config too
        lines = config_manager.config_content.split("\n")
        cleaned = _remove_old_blocklist_acls(lines, acl_name)
        new_content = "\n".join(cleaned)
        config_manager.save_config(new_content)
    except Exception:
        logger.exception("Error eliminando ACLs de blocklist de la config")
        errors.append("Error eliminando ACLs de la configuración de Squid")

    # ------------------------------------------------------------------
    # 2. Delete domain files
    # ------------------------------------------------------------------
    blocklists_dir = os.path.join(config_manager.config_dir, BLOCKLIST_DIR_NAME)
    deleted_files = 0
    if os.path.isdir(blocklists_dir):
        try:
            for fname in os.listdir(blocklists_dir):
                if fname.startswith(BLOCKLIST_PREFIX) and fname.endswith(".txt"):
                    fpath = os.path.join(blocklists_dir, fname)
                    try:
                        os.remove(fpath)
                        deleted_files += 1
                    except OSError:
                        logger.exception(f"Error eliminando archivo: {fpath}")
                        errors.append(f"No se pudo eliminar {fname}")
        except OSError:
            logger.exception(f"Error listando directorio: {blocklists_dir}")
            errors.append("Error leyendo directorio de blocklists")

    if errors:
        return False, "; ".join(errors)

    return (
        True,
        f"ACL blocklist '{acl_name}' eliminada ({deleted_files} archivo(s) removido(s))",
    )
