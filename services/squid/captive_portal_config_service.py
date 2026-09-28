"""Writes/removes the captive-portal directives in Squid's configuration.

Mirrors the block-marker approach used by the Kerberos module
(:mod:`services.squid.kerberos_config_service`) but stays intentionally
small: a single self-contained block is inserted right before the first
plain ``http_access allow`` rule, so that pre-existing safety denies
(``deny !Safe_ports``, ``deny CONNECT !SSL_ports``, manager exceptions...)
always run first.
"""

import sys
import os
from pathlib import Path
from urllib.parse import urlparse

from flask_babel import gettext as _
from loguru import logger

_BLOCK_START = "# BEGIN SquidStats Captive Portal"
_BLOCK_END = "# END SquidStats Captive Portal"

_EXTERNAL_ACL_NAME = "squidstats_captive_portal"
_VALID_ACL_NAME = "squidstats_captive_portal_valid"
_DOMAIN_ACL_NAME = "squidstats_captive_portal_domain"

_HTTP_ACCESS_MODULE_FILENAME = "120_http_access.conf"
_WRITE_MODE_ENV = "SQUIDSTATS_SQUID_CONFIG_WRITE_MODE"
_HELPER_PYTHON_ENV = "SQUIDSTATS_HELPER_PYTHON"
_HELPER_PATH_ENV = "SQUIDSTATS_HELPER_PATH"

HELPER_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "helper" / "captive_portal_helper.py"
)


def _portal_host(portal_public_url: str) -> str | None:
    if not portal_public_url:
        return None
    parsed = urlparse(portal_public_url)
    return parsed.hostname


def render_block(
    *,
    login_url: str,
    portal_public_url: str,
    acl_ttl_seconds: int,
    acl_negative_ttl_seconds: int,
) -> str:
    """Build the Squid directive block for the captive portal."""
    python_exe = os.getenv(_HELPER_PYTHON_ENV, sys.executable).strip()
    helper_path = os.getenv(_HELPER_PATH_ENV, str(HELPER_SCRIPT_PATH)).strip()
    lines = [
        _BLOCK_START,
        (
            f"external_acl_type {_EXTERNAL_ACL_NAME} "
            f"ttl={int(acl_ttl_seconds)} negative_ttl={int(acl_negative_ttl_seconds)} "
            f"%SRC {python_exe} {helper_path}"
        ),
        f"acl {_VALID_ACL_NAME} external {_EXTERNAL_ACL_NAME}",
    ]

    portal_host = _portal_host(portal_public_url)
    if portal_host:
        lines.append(f'acl {_DOMAIN_ACL_NAME} dstdomain "{portal_host}"')

    lines.append(f"deny_info 302:{login_url} {_VALID_ACL_NAME}")

    if portal_host:
        lines.append(f"http_access allow {_DOMAIN_ACL_NAME}")

    lines.append(f"http_access deny !{_VALID_ACL_NAME}")
    lines.append(_BLOCK_END)
    return "\n".join(lines)


def _find_insert_before_first_allow(lines: list[str]) -> int:
    """Insert after narrow manager policy but before general allow rules."""
    for i, line in enumerate(lines):
        parts = line.strip().split("#", 1)[0].split()
        if len(parts) >= 3 and parts[:2] == ["http_access", "allow"]:
            acl_names = {part.casefold() for part in parts[2:]}
            if acl_names == {"manager", "localhost"}:
                continue
            return i
    for i, line in enumerate(lines):
        if line.strip() == "http_access deny all":
            return i
    return len(lines)


def _strip_existing_block(lines: list[str]) -> list[str]:
    result = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == _BLOCK_START:
            in_block = True
            continue
        if stripped == _BLOCK_END:
            in_block = False
            continue
        if not in_block:
            result.append(line)
    return result


def _apply_to_content(content: str, block: str | None) -> str:
    lines = content.split("\n")
    had_managed_block = any(line.strip() == _BLOCK_START for line in lines)
    lines = _strip_existing_block(lines)
    if block is None:
        return "\n".join(lines)
    if not had_managed_block and block in content:
        return content
    insert_idx = _find_insert_before_first_allow(lines)
    block_lines = block.split("\n")
    lines[insert_idx:insert_idx] = block_lines
    return "\n".join(lines)


def _write(cm, block: str | None) -> tuple[bool, str]:
    try:
        if os.getenv(_WRITE_MODE_ENV, "managed").strip().casefold() != "managed":
            return False, _(
                "Este despliegue usa modo manual para squid.conf. "
                "Copia la vista previa y aplícala mediante el procedimiento administrativo controlado."
            )
        if cm.is_modular:
            content = cm.read_modular_config(_HTTP_ACCESS_MODULE_FILENAME) or ""
            if block is None and _BLOCK_START not in content:
                return True, _("La configuración del portal cautivo ya estaba deshabilitada")
            new_content = _apply_to_content(content, block)
            if cm.save_modular_config(_HTTP_ACCESS_MODULE_FILENAME, new_content):
                return True, _("Configuración de portal cautivo actualizada")
            return False, _("Error al escribir la configuración modular")

        if block is None and _BLOCK_START not in cm.config_content:
            return True, _("La configuración del portal cautivo ya estaba deshabilitada")
        new_content = _apply_to_content(cm.config_content, block)
        if cm.save_config(new_content):
            return True, _("Configuración de portal cautivo actualizada")
        return False, _("Error al escribir squid.conf")
    except Exception:
        logger.exception("Error applying the captive portal Squid configuration")
        return False, _("Error interno al aplicar la configuración de portal cautivo")


def enable_captive_portal(
    cm,
    *,
    login_url: str,
    portal_public_url: str,
    acl_ttl_seconds: int,
    acl_negative_ttl_seconds: int,
) -> tuple[bool, str]:
    """Write the captive portal directives into Squid's configuration."""
    block = render_block(
        login_url=login_url,
        portal_public_url=portal_public_url,
        acl_ttl_seconds=acl_ttl_seconds,
        acl_negative_ttl_seconds=acl_negative_ttl_seconds,
    )
    return _write(cm, block)


def disable_captive_portal(cm) -> tuple[bool, str]:
    """Remove the captive portal directives from Squid's configuration."""
    return _write(cm, None)
