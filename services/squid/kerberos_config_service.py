"""Managed Kerberos/SPNEGO configuration for Squid.

This module deliberately manages the Squid configuration, not the LDAP client
configuration used by SquidStats itself.  A Kerberos keytab is never uploaded,
stored, or returned by this module: an administrator provisions it on the
Squid host and this service only references its path.
"""

from __future__ import annotations

import fnmatch
import glob
import ipaddress
import json
import os
import pwd
import re
import shutil
import stat
import subprocess  # nosec B404 - commands below use fixed executable/arguments
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from loguru import logger

from utils.admin import squid_config_write_lock
from utils.custom_types import PREDEFINED_ACLS

AUTH_MODULE_FILENAME = "50_auth.conf"
ACL_MODULE_FILENAME = "100_acls.conf"
HTTP_ACCESS_MODULE_FILENAME = "120_http_access.conf"

MANAGED_AUTH_START = "# BEGIN SquidStats Kerberos authentication"
MANAGED_AUTH_END = "# END SquidStats Kerberos authentication"
MANAGED_ACCESS_START = "# BEGIN SquidStats Kerberos access rule"
MANAGED_ACCESS_END = "# END SquidStats Kerberos access rule"

# Markers used by the experimental implementation that was never merged into
# main.  Recognising them lets an administrator migrate away from its unsafe
# block (which mixed http_access into the auth module) without duplicate rules.
LEGACY_MANAGED_AUTH_START = "# SQUIDSTATS KERBEROS AUTH START"
LEGACY_MANAGED_AUTH_END = "# SQUIDSTATS KERBEROS AUTH END"

DEFAULT_HELPER_PATH = "/usr/lib/squid/negotiate_kerberos_auth"
DEFAULT_KEYTAB_PATH = "/var/run/squid/HTTP.keytab"
DEFAULT_ACL_NAME = "kerberos_auth"
DEFAULT_DOCKER_CONTAINER = "squid_proxy"
DEFAULT_DOCKER_CONFIG_PATH = "/etc/squid/squid.conf"
_MAX_INCLUDED_CONFIG_BYTES = 1024 * 1024

# The Debian unit deliberately uses ``manual``: ``ProtectSystem=full`` keeps
# /etc read-only for the unprivileged web process.  Keep the default managed
# for source, container, and legacy deployments; if an operator sets an
# unrecognised value, fail closed rather than presenting write controls that
# will fail under a hardened unit.
_SQUID_CONFIG_WRITE_MODE_ENV = "SQUIDSTATS_SQUID_CONFIG_WRITE_MODE"
_SQUID_CONFIG_WRITE_MODE_MANAGED = "managed"
_SQUID_CONFIG_WRITE_MODE_MANUAL = "manual"

# This is the quota feature's generated ACL/rule pair.  A ``proxy_auth`` ACL
# can itself make Squid look up credentials, so it must run after the
# Kerberos challenge (and the local Cache Manager exception) when both
# features are active.  Keep the handling deliberately narrow: arbitrary
# administrator-owned proxy_auth rules are not reordered here.
_QUOTA_PROXY_AUTH_ACL_NAME = "usuarios_bloqueados"
_QUOTA_PROXY_AUTH_DENY = "http_access deny usuarios_bloqueados"

_SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9._+/@:=,-]+$")
_PRINCIPAL_RE = re.compile(
    r"^HTTP/[A-Za-z0-9][A-Za-z0-9.-]*(?:@[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)
_ACL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RUNTIME_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]*$")
_SQUID_VERSION_RE = re.compile(r"Squid Cache:\s*Version\s+(\d+(?:\.\d+)*)", re.I)
_SQUID_DEFAULT_USER_RE = re.compile(
    r"--with-default-user(?:=|\s+)(?:'([^']+)'|\"([^\"]+)\"|([^\s'\"]+))"
)
_HTTP_ACCESS_RE = re.compile(r"^http_access\s+(allow|deny)\s+(.+)$", re.I)
_INCLUDE_RE = re.compile(r"^include\s+(.+)$", re.I)
_CACHE_EFFECTIVE_USER_RE = re.compile(r"^cache_effective_user\s+(\S+)", re.I)
_PORT_DIRECTIVE_RE = re.compile(r"^(?:http|https)_port\b", re.I)
_RESERVED_ACL_NAMES = {name.casefold() for name in PREDEFINED_ACLS}
_RUNTIME_PREFERENCES = frozenset({"auto", "local", "docker"})
_APPLY_LOCK = threading.RLock()


class KerberosConfigurationError(ValueError):
    """A configuration error safe to display to an administrator."""


def _squid_config_write_mode() -> str:
    """Return whether this deployment permits panel-managed Squid writes.

    The setting is an explicit deployment contract, rather than an unreliable
    attempt to infer systemd mount namespaces from the web process.  It is
    intentionally not a privilege grant: a package administrator must first
    deploy a narrowly scoped, audited write mechanism before opting in.
    """
    configured = os.getenv(_SQUID_CONFIG_WRITE_MODE_ENV, "").strip().casefold()
    if not configured or configured == _SQUID_CONFIG_WRITE_MODE_MANAGED:
        return _SQUID_CONFIG_WRITE_MODE_MANAGED
    return _SQUID_CONFIG_WRITE_MODE_MANUAL


def _manual_squid_write_message() -> str | None:
    """Explain the packaged read-only mode without suggesting unsafe grants."""
    if _squid_config_write_mode() != _SQUID_CONFIG_WRITE_MODE_MANUAL:
        return None
    return (
        "Este despliegue ejecuta SquidStats en modo manual para squid.conf. "
        "La unidad Debian incluida protege /etc/squid y no permite escrituras desde el panel. "
        "Puedes copiar la vista previa y aplicarla mediante el procedimiento administrativo "
        "controlado. No cambies este modo hasta disponer de un mecanismo privilegiado "
        "restringido y auditado."
    )


@dataclass(frozen=True)
class KerberosSettings:
    """Values accepted by the Kerberos configuration form/API."""

    enabled: bool = False
    helper_path: str = DEFAULT_HELPER_PATH
    keytab_path: str = DEFAULT_KEYTAB_PATH
    service_principal: str = ""
    children: int = 10
    startup: int = 5
    idle: int = 3
    keep_alive: bool = True
    strip_realm: bool = False
    acl_name: str = DEFAULT_ACL_NAME
    enforce_auth: bool = True
    replace_existing_negotiate: bool = False
    reload_squid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _ConfigTarget:
    """An in-memory editable Squid configuration target."""

    name: str
    path: Path
    original: str
    content: str
    existed: bool
    save: Callable[[str], bool]


@dataclass(frozen=True)
class _SquidRuntime:
    """A local Squid binary or a running Docker container with Squid."""

    kind: str
    executable: str
    container_name: str | None = None
    container_config_path: str | None = None


def default_settings() -> KerberosSettings:
    """Return safe form defaults without inventing a domain-specific SPN."""
    return KerberosSettings()


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "si", "sí"}


def _text(data: Mapping[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    return str(value if value is not None else default).strip()


def _integer(
    data: Mapping[str, Any], key: str, default: int, minimum: int, maximum: int
) -> int:
    raw_value = data.get(key, default)
    if raw_value is None or str(raw_value).strip() == "":
        return default
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError) as exc:
        raise KerberosConfigurationError(
            f"{key} debe ser un número entero entre {minimum} y {maximum}."
        ) from exc
    if not minimum <= value <= maximum:
        raise KerberosConfigurationError(
            f"{key} debe estar entre {minimum} y {maximum}."
        )
    return value


def _validate_path(value: str, field_name: str) -> str:
    if not value:
        raise KerberosConfigurationError(f"Debes indicar {field_name}.")
    if not _SAFE_PATH_RE.fullmatch(value):
        raise KerberosConfigurationError(
            f"{field_name} debe ser una ruta absoluta sin espacios ni caracteres "
            "que puedan alterar squid.conf."
        )
    return value


def _validate_principal(value: str) -> str:
    if not _PRINCIPAL_RE.fullmatch(value) or "\\" in value:
        raise KerberosConfigurationError(
            "El SPN debe tener el formato HTTP/proxy.ejemplo@REALM "
            "(o HTTP/proxy.ejemplo si Kerberos resuelve el realm predeterminado), "
            "sin barras de escape."
        )
    hostname = value.split("/", 1)[1].split("@", 1)[0]
    if "." not in hostname:
        raise KerberosConfigurationError(
            "El SPN debe usar el FQDN real que utilizan los clientes para el proxy."
        )
    return value


def _keytab_contains_principal(output: str, service_principal: str) -> bool:
    """Match a service principal in ``klist`` output without prefix matches.

    An explicit realm is preferred. The helper also permits ``HTTP/fqdn`` and
    resolves its default realm, so accept any keytab principal with exactly
    that service/host portion in that case.
    """
    principals = re.findall(
        r"HTTP/[A-Za-z0-9][A-Za-z0-9.-]*(?:@[A-Za-z0-9][A-Za-z0-9._-]*)?",
        output,
        flags=re.IGNORECASE,
    )
    expected_service_host, separator, expected_realm = service_principal.partition("@")
    for principal in principals:
        candidate_service_host, candidate_separator, candidate_realm = principal.partition(
            "@"
        )
        # DNS host names are case-insensitive, while a Kerberos realm is an
        # opaque, case-sensitive component.  Folding the complete principal
        # would turn ``@realm`` into a false match for ``@REALM``.
        if candidate_service_host.casefold() != expected_service_host.casefold():
            continue
        if not separator:
            return True
        if candidate_separator and candidate_realm == expected_realm:
            return True
    return False


def normalise_settings(data: Mapping[str, Any] | None) -> KerberosSettings:
    """Validate and normalise form or JSON data before it reaches squid.conf."""
    data = data or {}
    defaults = default_settings()
    enabled = _as_bool(data.get("enabled"), defaults.enabled)

    # A recovery/disable action must still work when an administrator has
    # cleared or mistyped another form field. None of those values is emitted
    # while the feature is disabled.
    if not enabled:
        return KerberosSettings(
            enabled=False,
            helper_path=_text(data, "helper_path", defaults.helper_path),
            keytab_path=_text(data, "keytab_path", defaults.keytab_path),
            service_principal=_text(
                data, "service_principal", defaults.service_principal
            ),
            children=defaults.children,
            startup=defaults.startup,
            idle=defaults.idle,
            keep_alive=_as_bool(data.get("keep_alive"), defaults.keep_alive),
            strip_realm=_as_bool(data.get("strip_realm"), defaults.strip_realm),
            acl_name=_text(data, "acl_name", defaults.acl_name),
            enforce_auth=_as_bool(data.get("enforce_auth"), defaults.enforce_auth),
            replace_existing_negotiate=_as_bool(
                data.get("replace_existing_negotiate"),
                defaults.replace_existing_negotiate,
            ),
            reload_squid=_as_bool(data.get("reload_squid"), defaults.reload_squid),
        )
    children = _integer(data, "children", defaults.children, 1, 128)
    startup = _integer(data, "startup", defaults.startup, 0, 128)
    idle = _integer(data, "idle", defaults.idle, 0, 128)
    if startup > children:
        raise KerberosConfigurationError("startup no puede ser mayor que children.")
    if idle > children:
        raise KerberosConfigurationError("idle no puede ser mayor que children.")

    settings = KerberosSettings(
        enabled=enabled,
        helper_path=_text(data, "helper_path", defaults.helper_path),
        keytab_path=_text(data, "keytab_path", defaults.keytab_path),
        service_principal=_text(data, "service_principal", defaults.service_principal),
        children=children,
        startup=startup,
        idle=idle,
        keep_alive=_as_bool(data.get("keep_alive"), defaults.keep_alive),
        strip_realm=_as_bool(data.get("strip_realm"), defaults.strip_realm),
        acl_name=_text(data, "acl_name", defaults.acl_name),
        enforce_auth=_as_bool(data.get("enforce_auth"), defaults.enforce_auth),
        replace_existing_negotiate=_as_bool(
            data.get("replace_existing_negotiate"),
            defaults.replace_existing_negotiate,
        ),
        reload_squid=_as_bool(data.get("reload_squid"), defaults.reload_squid),
    )

    helper_path = _validate_path(settings.helper_path, "la ruta del helper")
    keytab_path = _validate_path(settings.keytab_path, "la ruta del keytab")
    service_principal = _validate_principal(settings.service_principal)
    if not _ACL_NAME_RE.fullmatch(settings.acl_name):
        raise KerberosConfigurationError(
            "El nombre de ACL solo puede contener letras, números, guion y guion bajo."
        )
    if settings.acl_name.casefold() in _RESERVED_ACL_NAMES:
        raise KerberosConfigurationError(
            "El nombre de ACL no puede reemplazar una ACL predefinida de Squid."
        )
    return KerberosSettings(
        **{
            **settings.to_dict(),
            "helper_path": helper_path,
            "keytab_path": keytab_path,
            "service_principal": service_principal,
        }
    )


def _validated_settings(
    data: KerberosSettings | Mapping[str, Any] | None,
) -> KerberosSettings:
    """Validate settings even when an internal caller supplies a dataclass."""
    if isinstance(data, KerberosSettings):
        return normalise_settings(data.to_dict())
    return normalise_settings(data)


def _uncommented(line: str) -> str:
    """Return a directive without its trailing Squid comment."""
    return line.split("#", 1)[0].strip()


def _logical_squid_lines(content: str) -> list[str]:
    """Join Squid continuation lines before inspecting directives."""
    logical_lines: list[str] = []
    pending = ""
    for raw_line in content.splitlines():
        line = _uncommented(raw_line)
        if not line:
            continue
        if pending:
            line = f"{pending} {line.lstrip()}"
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            pending = stripped[:-1].rstrip()
            continue
        logical_lines.append(line)
        pending = ""
    if pending:
        logical_lines.append(pending)
    return logical_lines


def _logical_squid_line_locations(
    lines: list[str],
) -> list[tuple[int, int, str]]:
    """Return logical Squid directives with their physical line positions.

    Include directives are allowed to use a trailing backslash.  Writers need
    the original positions to insert safely, while policy checks need the
    joined directive, so inspecting ``splitlines`` alone can duplicate an
    already-active module.
    """
    locations: list[tuple[int, int, str]] = []
    pending = ""
    start_index: int | None = None
    for index, raw_line in enumerate(lines):
        line = _uncommented(raw_line)
        if not line:
            continue
        if pending:
            line = f"{pending} {line.lstrip()}"
        else:
            start_index = index
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            pending = stripped[:-1].rstrip()
            continue
        locations.append((start_index if start_index is not None else index, index, line))
        pending = ""
        start_index = None
    if pending:
        locations.append(
            (
                start_index if start_index is not None else len(lines) - 1,
                len(lines) - 1,
                pending,
            )
        )
    return locations


def _is_http_access_line(line: str) -> bool:
    return _HTTP_ACCESS_RE.fullmatch(_uncommented(line)) is not None


def _remove_complete_blocks(content: str, start: str, end: str) -> str:
    """Remove complete managed blocks and reject incomplete markers safely."""
    while True:
        start_index = content.find(start)
        if start_index < 0:
            return content
        end_index = content.find(end, start_index + len(start))
        if end_index < 0:
            raise KerberosConfigurationError(
                "Se encontró un bloque Kerberos incompleto; revísalo manualmente antes de continuar."
            )
        end_index += len(end)
        newline_index = content.find("\n", end_index)
        remove_end = len(content) if newline_index < 0 else newline_index + 1
        content = content[:start_index] + content[remove_end:]


def _assert_complete_managed_blocks(content: str) -> None:
    """Reject a hand-edited managed block that cannot be safely interpreted.

    The status page must stay available in this situation, but it must explain
    why applying another change is unsafe.  Checking this independently of
    removal also catches a broken marker when the block has no auth directive.
    """
    pairs = (
        (MANAGED_AUTH_START, MANAGED_AUTH_END),
        (MANAGED_ACCESS_START, MANAGED_ACCESS_END),
        (LEGACY_MANAGED_AUTH_START, LEGACY_MANAGED_AUTH_END),
    )
    for start, end in pairs:
        offset = 0
        while True:
            start_index = content.find(start, offset)
            if start_index < 0:
                break
            end_index = content.find(end, start_index + len(start))
            if end_index < 0:
                raise KerberosConfigurationError(
                    "Se encontró un bloque Kerberos incompleto; revísalo manualmente antes de continuar."
                )
            offset = end_index + len(end)


def _remove_managed_auth(content: str) -> str:
    content = _remove_complete_blocks(content, MANAGED_AUTH_START, MANAGED_AUTH_END)
    return _remove_complete_blocks(
        content, LEGACY_MANAGED_AUTH_START, LEGACY_MANAGED_AUTH_END
    )


def _remove_managed_access(content: str) -> str:
    return _remove_complete_blocks(content, MANAGED_ACCESS_START, MANAGED_ACCESS_END)


def _find_complete_block(content: str, start: str, end: str) -> str | None:
    start_index = content.find(start)
    if start_index < 0:
        return None
    end_index = content.find(end, start_index + len(start))
    if end_index < 0:
        return None
    return content[start_index : end_index + len(end)]


def _auth_block(settings: KerberosSettings) -> str:
    helper_arguments = [
        settings.helper_path,
        "-k",
        settings.keytab_path,
    ]
    if settings.strip_realm:
        helper_arguments.append("-r")
    helper_arguments.extend(["-s", settings.service_principal])
    helper = " ".join(helper_arguments)
    keep_alive = "on" if settings.keep_alive else "off"
    return "\n".join(
        [
            MANAGED_AUTH_START,
            "# SPNEGO/Kerberos authentication managed by SquidStats.",
            f"auth_param negotiate program {helper}",
            "auth_param negotiate children "
            f"{settings.children} startup={settings.startup} idle={settings.idle}",
            f"auth_param negotiate keep_alive {keep_alive}",
            f"acl {settings.acl_name} proxy_auth REQUIRED",
            MANAGED_AUTH_END,
            "",
        ]
    )


def _access_block(settings: KerberosSettings) -> str:
    return "\n".join(
        [
            MANAGED_ACCESS_START,
            "# Keep this after security denies and before client allow rules.",
            # A negated proxy_auth ACL is deliberate. Squid documents this
            # form because an `allow proxy_auth` rule alone may not challenge
            # a client that initially presents no credentials; a later
            # `allow localnet` could then grant anonymous access.
            f"http_access deny !{settings.acl_name}",
            MANAGED_ACCESS_END,
            "",
        ]
    )


def render_preview(settings: KerberosSettings | Mapping[str, Any]) -> str:
    """Render the directives that will be managed, without changing files."""
    settings = _validated_settings(settings)
    if not settings.enabled:
        return (
            "# Kerberos authentication is disabled; managed blocks will be removed.\n"
        )
    preview = _auth_block(settings)
    if settings.enforce_auth:
        preview += "\n" + _access_block(settings)
    return preview


def _insert_before_first_http_access(
    content: str, block: str, *, config_path: Path | None = None
) -> str:
    """Insert auth directives before every direct authentication consumer.

    Squid needs ``auth_param`` before an ``acl ... proxy_auth`` (and before
    external ACL types that ask for ``%LOGIN``), not merely before the first
    ``http_access`` line.  A quota ACL commonly appears near the top of a
    monolithic configuration, so placing the helper only at the access-policy
    boundary can leave an invalid configuration.  When an on-disk path is
    known, inspect direct includes recursively as well: the helper must be
    loaded before a parent fragment that defines such an ACL.
    """
    lines = content.splitlines(keepends=True)
    insertion_indices = [
        start_index
        for start_index, _end_index, logical_line in _logical_squid_line_locations(
            lines
        )
        if _is_http_access_line(logical_line)
        or _is_auth_dependent_directive(logical_line)
    ]
    if config_path is not None:
        insertion_indices.extend(
            _direct_auth_dependency_indices(content, config_path.parent)
        )
    if insertion_indices:
        index = min(insertion_indices)
        prefix = "" if index == 0 or lines[index - 1].endswith("\n\n") else "\n"
        lines.insert(index, prefix + block)
        return "".join(lines)
    if not content.strip():
        return block
    return content.rstrip() + "\n\n" + block


def _is_negotiate_directive(line: str) -> bool:
    parts = _uncommented(line).split()
    return (
        len(parts) >= 3
        and parts[0].casefold() == "auth_param"
        and parts[1].casefold() == "negotiate"
    )


def _negotiate_directive_lines(content: str) -> list[str]:
    """Return active Negotiate directives, including logical continuations."""
    return [
        line for line in _logical_squid_lines(content) if _is_negotiate_directive(line)
    ]


def _other_auth_program_schemes(content: str) -> set[str]:
    """Return active helper schemes other than Negotiate.

    Squid may offer several authentication schemes at once, but user agents
    can choose among them. This managed flow deliberately configures a single
    Kerberos/SPNEGO scheme instead of silently turning an NTLM/Basic fallback
    into an alternate way around the intended policy.
    """
    schemes: set[str] = set()
    for line in _logical_squid_lines(content):
        parts = line.split()
        if (
            len(parts) >= 4
            and parts[0].casefold() == "auth_param"
            and parts[2].casefold() == "program"
            and parts[1].casefold() != "negotiate"
        ):
            schemes.add(parts[1].casefold())
    return schemes


def _remove_conflicting_negotiate_directives(content: str) -> str:
    """Remove reviewed Negotiate directives, including continuation lines."""
    kept: list[str] = []
    lines = content.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        if _is_negotiate_directive(line):
            # A multiline helper declaration must be removed as one logical
            # directive. Leaving its next ``-k``/``-s`` line behind would make
            # the configuration invalid after a deliberate replacement.
            while index < len(lines):
                continued = _uncommented(lines[index]).rstrip().endswith("\\")
                index += 1
                if not continued:
                    break
            continue
        kept.append(line)
        index += 1
    return "".join(kept)


def _remove_acl(content: str, acl_name: str) -> str:
    acl_re = re.compile(
        rf"^acl\s+{re.escape(acl_name)}\s+(?:-\S+\s+)*proxy_auth\s+REQUIRED(?:\s|$)",
        re.I,
    )
    return "".join(
        line
        for line in content.splitlines(keepends=True)
        if not acl_re.match(_uncommented(line))
    )


def _has_acl_definition(content: str, acl_name: str) -> bool:
    """Return whether a non-comment ACL already owns this name."""
    return any(
        len(parts := _uncommented(line).split()) >= 2
        and parts[0].casefold() == "acl"
        and parts[1].casefold() == acl_name.casefold()
        for line in content.splitlines()
    )


def _remove_access_rule(content: str, acl_name: str) -> str:
    expected = {
        f"http_access deny !{acl_name}".casefold(),
        f"http_access allow {acl_name}".casefold(),
    }
    return "".join(
        line
        for line in content.splitlines(keepends=True)
        if _uncommented(line).casefold() not in expected
    )


def _has_proxy_auth_quota_acl(contents: list[str]) -> bool:
    """Return whether the active quota ACL uses authenticated identities.

    The quota feature also has an IP-based fallback with the same access-rule
    name.  Moving that fallback would change its established policy, whereas
    the proxy-auth form can start authentication before Kerberos gets its
    intended chance to challenge.  Only the latter is relevant here.
    """
    for content in contents:
        for line in _logical_squid_lines(content):
            parts = line.split()
            if (
                len(parts) >= 3
                and parts[0].casefold() == "acl"
                and parts[1].casefold() == _QUOTA_PROXY_AUTH_ACL_NAME
                and parts[2].casefold() == "proxy_auth"
            ):
                return True
    return False


def _take_proxy_auth_quota_deny(content: str, acl_contents: list[str]) -> tuple[str, str | None]:
    """Temporarily remove the generated quota denial before inserting auth.

    Returning the first physical rule preserves an administrator's harmless
    inline comment.  Duplicate generated rules are collapsed while the rule
    is restored, matching the quota sync's single-rule invariant.
    """
    if not _has_proxy_auth_quota_acl(acl_contents):
        return content, None

    quota_rule: str | None = None
    kept: list[str] = []
    for line in content.splitlines(keepends=True):
        if _uncommented(line).casefold() == _QUOTA_PROXY_AUTH_DENY:
            if quota_rule is None:
                quota_rule = line.rstrip("\r\n")
            continue
        kept.append(line)
    return "".join(kept), quota_rule


def _restore_proxy_auth_quota_deny(content: str, quota_rule: str) -> str:
    """Put the generated proxy-auth quota rule after the Kerberos challenge."""
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() != MANAGED_ACCESS_END:
            continue
        newline = "" if line.endswith("\n") else "\n"
        lines.insert(index + 1, f"{newline}{quota_rule}\n")
        return "".join(lines)
    raise KerberosConfigurationError(
        "No se pudo ubicar el bloque Kerberos para reordenar la regla de cuota."
    )


def _is_management_exception(acls: list[str]) -> bool:
    """Keep only an explicit Cache Manager exception ahead of auth.

    A standalone ``allow localhost`` grants normal proxy access from loopback,
    so it must not silently bypass the Kerberos challenge. The only exception
    retained ahead of the challenge is the conventional *local* Cache Manager
    rule, with positive ``manager`` and ``localhost`` ACLs.
    """
    # Negating ``manager`` changes the rule completely: ``allow !manager``
    # matches ordinary proxy traffic and would let it bypass the challenge.
    # Only the conventional, positive Cache Manager ACL (optionally limited
    # to positive ``localhost``) is safe to leave before Kerberos.
    normalised = {acl.casefold() for acl in acls}
    return normalised == {"manager", "localhost"}


def _active_acl_definitions(contents: list[str], name: str) -> list[tuple[str, list[str]]]:
    """Collect active definitions of an ACL name, including Squid options."""
    definitions: list[tuple[str, list[str]]] = []
    for content in contents:
        for line in _logical_squid_lines(content):
            parts = line.split()
            if (
                len(parts) < 3
                or parts[0].casefold() != "acl"
                or parts[1].casefold() != name.casefold()
            ):
                continue
            type_index = 2
            while type_index < len(parts) and parts[type_index].startswith("-"):
                type_index += 1
            if type_index >= len(parts):
                definitions.append(("", []))
            else:
                definitions.append(
                    (parts[type_index].casefold(), parts[type_index + 1 :])
                )
    return definitions


def _is_loopback_acl_value(value: str) -> bool:
    """Whether an ACL source value is an IP address/network limited to loopback."""
    try:
        return ipaddress.ip_network(value, strict=False).is_loopback
    except ValueError:
        return False


def _assert_management_exception_acls_safe(contents: list[str]) -> None:
    """Reject a broad ``manager localhost`` exception before auth.

    The rule is only safe when ``manager`` is restricted to cache-object
    requests and every explicitly declared ``localhost`` source is loopback.
    Missing definitions are left for Squid's syntax validation: an undefined
    ACL cannot authorize anonymous traffic, whereas a broad declaration can.
    """
    manager_definitions = _active_acl_definitions(contents, "manager")
    if manager_definitions and any(
        acl_type != "proto" or values != ["cache_object"]
        for acl_type, values in manager_definitions
    ):
        raise KerberosConfigurationError(
            "La ACL manager no está limitada a 'proto cache_object'; no es seguro "
            "dejar su excepción antes del desafío Kerberos."
        )

    localhost_definitions = _active_acl_definitions(contents, "localhost")
    if localhost_definitions and any(
        acl_type != "src"
        or not values
        or not all(_is_loopback_acl_value(value) for value in values)
        for acl_type, values in localhost_definitions
    ):
        raise KerberosConfigurationError(
            "La ACL localhost no está limitada a direcciones loopback; no es seguro "
            "dejar su excepción antes del desafío Kerberos."
        )


def _add_access_block(
    content: str,
    settings: KerberosSettings,
    *,
    acl_contents: list[str] | None = None,
) -> str:
    """Insert an authentication challenge without bypassing later denies.

    ``http_access deny !kerberos_auth`` is the documented way to reliably
    trigger an authentication challenge. It must be before the first normal
    client allow rule but after all security denies. Rather than silently
    altering an ambiguous policy, this routine refuses to insert the rule when
    a denial follows that point.
    """
    lines = content.splitlines(keepends=True)
    parsed: list[tuple[int, str, list[str]]] = []
    final_deny_index: int | None = None
    first_client_allow: int | None = None

    for index, line in enumerate(lines):
        match = _HTTP_ACCESS_RE.fullmatch(_uncommented(line))
        if not match:
            continue
        action = match.group(1).casefold()
        acls = match.group(2).split()
        parsed.append((index, action, acls))
        if action == "deny" and [item.casefold() for item in acls] == ["all"]:
            if final_deny_index is None:
                final_deny_index = index
            continue
        if (
            action == "allow"
            and index
            < (final_deny_index if final_deny_index is not None else len(lines))
            and not _is_management_exception(acls)
            and first_client_allow is None
        ):
            first_client_allow = index

    # final_deny_index was discovered while iterating, so establish the first
    # client allow again with the final boundary known.
    if final_deny_index is not None:
        first_client_allow = next(
            (
                index
                for index, action, acls in parsed
                if index < final_deny_index
                and action == "allow"
                and not _is_management_exception(acls)
            ),
            None,
        )

    if final_deny_index is None:
        raise KerberosConfigurationError(
            "No se encontró 'http_access deny all'; no es seguro insertar la regla Kerberos."
        )
    if any(index > final_deny_index for index, _action, _acls in parsed):
        raise KerberosConfigurationError(
            "'http_access deny all' no es la última regla de acceso; ordénala manualmente antes de activar Kerberos."
        )
    if first_client_allow is None:
        raise KerberosConfigurationError(
            "No se encontró una regla 'http_access allow' para clientes antes de 'deny all'; "
            "Kerberos podría autenticarlos pero no autorizarlos. Define primero tu política de acceso."
        )

    if any(
        action == "allow" and _is_management_exception(acls)
        for _index, action, acls in parsed
    ):
        _assert_management_exception_acls_safe(acl_contents or [content])

    insertion_index = first_client_allow
    later_denies = [
        index
        for index, action, acls in parsed
        if insertion_index < index < final_deny_index
        and action == "deny"
        and [item.casefold() for item in acls] != ["all"]
    ]
    if later_denies:
        raise KerberosConfigurationError(
            "La política http_access tiene denegaciones después del primer allow de clientes; "
            "ordénala manualmente antes de activar Kerberos para no omitir restricciones."
        )

    block = _access_block(settings)
    prefix = (
        ""
        if insertion_index == 0 or lines[insertion_index - 1].endswith("\n\n")
        else "\n"
    )
    lines.insert(insertion_index, prefix + block)
    return "".join(lines)


def _target_from_main(config_manager) -> _ConfigTarget:
    original = str(getattr(config_manager, "config_content", "") or "")
    config_path = Path(str(getattr(config_manager, "config_path", "squid.conf")))
    return _ConfigTarget(
        name="squid.conf",
        path=config_path,
        original=original,
        content=original,
        existed=True,
        save=config_manager.save_config,
    )


def _read_optional_module(
    config_manager, filename: str, *, require_readable: bool = False
) -> str | None:
    """Read a conventional module, distinguishing absence from read failure.

    ``SquidConfigManager.read_modular_config`` intentionally returns ``None``
    both for a missing file and for a failed read.  That is convenient for
    generic UI views, but unsafe for a configuration writer: directory write
    permission alone can otherwise replace an unreadable existing module.
    """
    config_dir = str(getattr(config_manager, "config_dir", "") or "")
    if config_dir:
        module_path = Path(config_dir) / filename
        try:
            module_stat = module_path.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            if require_readable:
                raise KerberosConfigurationError(
                    f"No se pudo inspeccionar el módulo estándar {filename}; "
                    "no se modificó ninguna configuración."
                ) from exc
            return None
        if not stat.S_ISREG(module_stat.st_mode):
            if require_readable:
                raise KerberosConfigurationError(
                    f"El módulo estándar {filename} no es un archivo regular; "
                    "no se modificó ninguna configuración."
                )
            return None

    try:
        content = config_manager.read_modular_config(filename)
    except Exception as exc:
        if require_readable:
            raise KerberosConfigurationError(
                f"No se pudo leer el módulo estándar {filename}; "
                "no se modificó ninguna configuración."
            ) from exc
        return None
    if content is None:
        if require_readable:
            raise KerberosConfigurationError(
                f"No se pudo leer el módulo estándar {filename}; "
                "no se modificó ninguna configuración."
            )
        return None
    if not isinstance(content, str):
        if require_readable:
            raise KerberosConfigurationError(
                f"El módulo estándar {filename} no contiene texto válido; "
                "no se modificó ninguna configuración."
            )
        return None
    return content


def _target_from_module(config_manager, filename: str) -> _ConfigTarget:
    config_dir = Path(str(getattr(config_manager, "config_dir", "")))
    existing = _read_optional_module(
        config_manager, filename, require_readable=True
    )
    original = existing if existing is not None else ""
    return _ConfigTarget(
        name=filename,
        path=config_dir / filename,
        original=original,
        content=original,
        existed=existing is not None,
        save=lambda content: config_manager.save_modular_config(filename, content),
    )


def _same_target(first: _ConfigTarget, second: _ConfigTarget) -> bool:
    return first.name == second.name and first.path == second.path


def _unique_targets(targets: list[_ConfigTarget]) -> list[_ConfigTarget]:
    unique: list[_ConfigTarget] = []
    for target in targets:
        if not any(_same_target(target, known) for known in unique):
            unique.append(target)
    return unique


def _active_http_access(content: str) -> bool:
    return any(
        _HTTP_ACCESS_RE.fullmatch(line) is not None
        for line in _logical_squid_lines(content)
    )


def _unexpected_included_http_access_sources(
    config_manager, expected_module_path: Path
) -> list[str]:
    """Return active rule sources outside the one this feature can manage.

    The generic ``is_modular`` flag also covers custom ``*.conf`` layouts.
    Adding a challenge to ``120_http_access.conf`` while an earlier custom
    fragment already allows clients would silently leave those clients
    unauthenticated.  We only write the conventional module, so reject such
    layouts instead of guessing at cross-file policy order.
    """
    expected_path = os.path.realpath(str(expected_module_path))
    return [
        path
        for path, content in _active_included_configuration_sources(config_manager)
        if os.path.realpath(path) != expected_path and _active_http_access(content)
    ]


def _access_target(
    config_manager,
    main: _ConfigTarget,
    modular: bool,
    module: _ConfigTarget | None = None,
) -> _ConfigTarget:
    if not modular:
        # An extensionless/custom include does not necessarily make the
        # generic configuration manager call the layout "modular".  Its
        # rules are nevertheless active at the include position, so adding
        # the challenge to squid.conf could leave an earlier allow rule able
        # to bypass Kerberos.  We do not know how to safely rewrite that
        # external policy source; require an administrator to consolidate it.
        unexpected_sources = _unexpected_included_http_access_sources(
            config_manager, main.path
        )
        if unexpected_sources:
            filenames = ", ".join(
                sorted({Path(path).name for path in unexpected_sources})
            )
            raise KerberosConfigurationError(
                "Se detectaron reglas http_access activas en archivos incluidos "
                f"fuera de squid.conf ({filenames}). Muévelas a squid.conf o "
                "termina de modularizar la política antes de activar Kerberos."
            )
        return main

    module = module or _target_from_module(config_manager, HTTP_ACCESS_MODULE_FILENAME)
    unexpected_sources = _unexpected_included_http_access_sources(
        config_manager, module.path
    )
    if unexpected_sources:
        filenames = ", ".join(sorted({Path(path).name for path in unexpected_sources}))
        raise KerberosConfigurationError(
            "Se detectaron reglas http_access activas fuera de squid.conf/"
            f"{HTTP_ACCESS_MODULE_FILENAME} ({filenames}). La política modular es ambigua; "
            "muévela a 120_http_access.conf antes de activar Kerberos."
        )
    main_has_rules = _active_http_access(main.content)
    module_has_rules = _active_http_access(module.content)
    module_is_active = any(
        os.path.realpath(path) == os.path.realpath(str(module.path))
        for path, _content in _active_included_configuration_sources(config_manager)
    )
    if main_has_rules and module_has_rules:
        raise KerberosConfigurationError(
            "Hay reglas http_access tanto en squid.conf como en 120_http_access.conf; "
            "la política es ambigua y no se modificó."
        )
    if main_has_rules and module_is_active:
        # Even an empty active 120 module is unsafe here: the generic HTTP
        # Access editor writes to that conventional file when it exists. A
        # later allow rule would be evaluated before the challenge kept in
        # squid.conf. Do not enable Kerberos in a layout that can become a
        # bypass through another first-party UI.
        raise KerberosConfigurationError(
            "120_http_access.conf está incluido antes de reglas en squid.conf. "
            "Aunque esté vacío, el editor HTTP Access podría añadir reglas antes del "
            "desafío Kerberos; mueve la política a un único origen antes de activar."
        )
    if main_has_rules:
        return main
    if module_has_rules and not module_is_active:
        raise KerberosConfigurationError(
            "120_http_access.conf contiene reglas pero no está incluido activamente; "
            "no es seguro activarlas al configurar Kerberos. Inclúyelo o mueve la política "
            "a squid.conf antes de continuar."
        )
    return module


def _include_path(line: str) -> str | None:
    match = _INCLUDE_RE.fullmatch(_uncommented(line))
    if not match:
        return None
    return match.group(1).strip().strip('"')


def _include_rank(include_path: str) -> int:
    match = re.match(r"^(\d+)_", Path(include_path).name)
    return int(match.group(1)) if match else 1000


def _resolved_include_path(include_path: str, config_directory: Path) -> str:
    raw_include_path = os.path.expanduser(include_path)
    return os.path.abspath(
        raw_include_path
        if os.path.isabs(raw_include_path)
        else str(config_directory / raw_include_path)
    )


def _include_matches_module(
    include_path: str, module_path: Path, config_directory: Path
) -> bool:
    desired = os.path.abspath(str(module_path))
    expanded = _resolved_include_path(include_path, config_directory)
    desired_real = os.path.realpath(desired)
    expanded_real = os.path.realpath(expanded)
    return (
        expanded == desired
        or fnmatch.fnmatch(desired, expanded)
        or expanded_real == desired_real
        or fnmatch.fnmatch(desired_real, expanded_real)
    )


def _is_auth_dependent_directive(line: str) -> bool:
    """Return whether an active directive needs authentication first.

    ``proxy_auth`` ACLs are registered against an authentication scheme while
    Squid parses its configuration.  An external ACL type with ``%LOGIN`` is
    similarly dependent on a proxy login.  Keeping these deliberately narrow
    avoids treating arbitrary ACL value lists as configuration dependencies.
    """
    parts = _uncommented(line).split()
    if not parts:
        return False
    lowered = [part.casefold() for part in parts]
    if lowered[0] == "acl":
        return any(part.startswith("proxy_auth") for part in lowered[2:])
    return lowered[0] == "external_acl_type" and "%login" in lowered[1:]


def _include_tree_requires_auth(
    content: str, directory: Path, seen: set[str], depth: int = 0
) -> bool:
    """Inspect one included source tree for proxy-auth configuration.

    This is intentionally fail-closed.  The caller is about to move the
    generated auth include in relation to the tree, so an unreadable or too
    deeply nested source cannot safely be treated as unrelated.
    """
    if any(_is_auth_dependent_directive(line) for line in _logical_squid_lines(content)):
        return True
    if depth >= 8:
        if any(_include_path(line) for line in _logical_squid_lines(content)):
            raise KerberosConfigurationError(
                "No se pudo verificar la profundidad de un include antes de la "
                "autenticación; revísalo manualmente antes de activar Kerberos."
            )
        return False

    for line in _logical_squid_lines(content):
        include_path = _include_path(line)
        if not include_path:
            continue
        pattern = _resolved_include_path(include_path, directory)
        try:
            candidates = sorted(glob.glob(pattern))
        except OSError as exc:
            raise KerberosConfigurationError(
                "No se pudo resolver un include antes de la autenticación; "
                "revísalo manualmente antes de activar Kerberos."
            ) from exc
        for candidate in candidates:
            canonical_path = os.path.realpath(candidate)
            if canonical_path in seen:
                continue
            try:
                source_stat = os.stat(canonical_path)
            except OSError as exc:
                raise KerberosConfigurationError(
                    "No se pudo inspeccionar un include antes de la autenticación; "
                    "no se modificó ninguna configuración."
                ) from exc
            if not stat.S_ISREG(source_stat.st_mode):
                raise KerberosConfigurationError(
                    "Un include antes de la autenticación no es un archivo regular; "
                    "no se modificó ninguna configuración."
                )
            if source_stat.st_size > _MAX_INCLUDED_CONFIG_BYTES:
                raise KerberosConfigurationError(
                    "Un include antes de la autenticación supera el límite de inspección; "
                    "revísalo manualmente antes de activar Kerberos."
                )
            seen.add(canonical_path)
            try:
                included_content = Path(canonical_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise KerberosConfigurationError(
                    "No se pudo leer un include antes de la autenticación; "
                    "no se modificó ninguna configuración."
                ) from exc
            if _include_tree_requires_auth(
                included_content, Path(canonical_path).parent, seen, depth + 1
            ):
                return True
    return False


def _direct_auth_dependency_indices(content: str, config_directory: Path) -> list[int]:
    """Return direct include locations that load proxy-auth dependencies."""
    lines = content.splitlines(keepends=True)
    indices: list[int] = []
    for start_index, _end_index, logical_line in _logical_squid_line_locations(lines):
        include_path = _include_path(logical_line)
        if not include_path:
            continue
        pattern = _resolved_include_path(include_path, config_directory)
        try:
            candidates = sorted(glob.glob(pattern))
        except OSError as exc:
            raise KerberosConfigurationError(
                "No se pudo resolver un include antes de la autenticación; "
                "revísalo manualmente antes de activar Kerberos."
            ) from exc
        for candidate in candidates:
            canonical_path = os.path.realpath(candidate)
            try:
                source_stat = os.stat(canonical_path)
            except OSError as exc:
                raise KerberosConfigurationError(
                    "No se pudo inspeccionar un include antes de la autenticación; "
                    "no se modificó ninguna configuración."
                ) from exc
            if not stat.S_ISREG(source_stat.st_mode):
                raise KerberosConfigurationError(
                    "Un include antes de la autenticación no es un archivo regular; "
                    "no se modificó ninguna configuración."
                )
            if source_stat.st_size > _MAX_INCLUDED_CONFIG_BYTES:
                raise KerberosConfigurationError(
                    "Un include antes de la autenticación supera el límite de inspección; "
                    "revísalo manualmente antes de activar Kerberos."
                )
            try:
                included_content = Path(canonical_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise KerberosConfigurationError(
                    "No se pudo leer un include antes de la autenticación; "
                    "no se modificó ninguna configuración."
                ) from exc
            if _include_tree_requires_auth(
                included_content,
                Path(canonical_path).parent,
                {canonical_path},
            ):
                indices.append(start_index)
                break
    return indices


def _active_included_configuration_sources(
    config_manager, *, inspection_errors: list[str] | None = None
) -> list[tuple[str, str]]:
    """Read active included configuration files without following cycles.

    Squid installations often use a wildcard include, but administrators may
    also split authentication, ports, or cache settings into custom files.
    Looking only at the standard filenames would miss active helpers and port
    modes in those layouts.  Files larger than one MiB are not read to avoid
    loading a value-list-sized file; callers that request inspection errors
    are told to review them manually before a write is allowed.
    """
    main_content = str(getattr(config_manager, "config_content", "") or "")
    main_path = Path(str(getattr(config_manager, "config_path", "squid.conf")))
    seen = {os.path.realpath(str(main_path))}
    sources: list[tuple[str, str]] = []

    def record_inspection_error(path: str, reason: str) -> None:
        if inspection_errors is None:
            return
        filename = Path(path).name or path
        inspection_errors.append(
            f"No se pudo inspeccionar el archivo incluido activo {filename} ({reason}). "
            "No se modificó ninguna configuración."
        )

    def visit(content: str, directory: Path, depth: int = 0) -> None:
        if depth >= 8:
            logger.warning("Maximum Squid include depth reached while checking Kerberos")
            if any(_include_path(line) for line in _logical_squid_lines(content)):
                record_inspection_error(
                    str(directory), "se alcanzó la profundidad máxima de includes"
                )
            return
        for line in _logical_squid_lines(content):
            include_path = _include_path(line)
            if not include_path:
                continue
            pattern = _resolved_include_path(include_path, directory)
            try:
                paths = sorted(glob.glob(pattern))
            except OSError:
                record_inspection_error(pattern, "no se pudo resolver el include")
                continue
            for candidate in paths:
                canonical_path = os.path.realpath(candidate)
                if canonical_path in seen:
                    continue
                try:
                    source_stat = os.stat(canonical_path)
                except OSError:
                    record_inspection_error(canonical_path, "no se pudo consultar")
                    continue
                if not stat.S_ISREG(source_stat.st_mode):
                    continue
                seen.add(canonical_path)
                if source_stat.st_size > _MAX_INCLUDED_CONFIG_BYTES:
                    record_inspection_error(
                        canonical_path,
                        f"supera el límite de {_MAX_INCLUDED_CONFIG_BYTES // 1024 // 1024} MiB",
                    )
                    continue
                try:
                    included_content = Path(canonical_path).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    record_inspection_error(canonical_path, "no se pudo leer como UTF-8")
                    continue
                sources.append((canonical_path, included_content))
                visit(included_content, Path(canonical_path).parent, depth + 1)

    visit(main_content, main_path.parent)
    return sources


def _configuration_source_inspection_errors(config_manager) -> list[str]:
    """Return blockers when an active or writable target cannot be inspected.

    Before doing a read-modify-write operation, the service must be able to
    see all active include fragments as well as its conventional output files.
    Otherwise a directory-level atomic replacement could erase unseen policy.
    """
    errors: list[str] = []
    _active_included_configuration_sources(config_manager, inspection_errors=errors)
    if bool(getattr(config_manager, "is_modular", False)):
        for filename in (
            AUTH_MODULE_FILENAME,
            ACL_MODULE_FILENAME,
            HTTP_ACCESS_MODULE_FILENAME,
        ):
            try:
                _read_optional_module(config_manager, filename, require_readable=True)
            except KerberosConfigurationError as exc:
                errors.append(str(exc))
    return list(dict.fromkeys(errors))


def _main_directly_includes_module(
    main: _ConfigTarget, module_path: Path
) -> bool:
    """Whether ``squid.conf`` itself loads a module (possibly via a glob)."""
    lines = main.content.splitlines(keepends=True)
    return any(
        (include_path := _include_path(logical_line))
        and _include_matches_module(include_path, module_path, main.path.parent)
        for _start, _end, logical_line in _logical_squid_line_locations(lines)
    )


def _reject_indirect_active_module(
    config_manager, main: _ConfigTarget, module: _ConfigTarget
) -> None:
    """Reject a module loaded only through a parent include.

    Editing its contents is safe, but inserting another direct include would
    load the helper or ACL twice.  Determining the order through arbitrary
    nested fragments is outside this narrowly managed workflow, so require a
    deliberate manual migration instead.
    """
    module_path = os.path.realpath(str(module.path))
    is_active = any(
        os.path.realpath(path) == module_path
        for path, _content in _active_included_configuration_sources(config_manager)
    )
    if is_active and not _main_directly_includes_module(main, module.path):
        raise KerberosConfigurationError(
            f"{module.name} se carga mediante un include indirecto. SquidStats no puede "
            "verificar su orden sin arriesgar una carga duplicada; mueve su include a "
            "squid.conf antes de activar Kerberos."
        )


def _ensure_include(
    content: str,
    module_path: Path,
    config_directory: Path | None = None,
    *,
    include_value: str | Path | None = None,
) -> str:
    """Ensure a generated modular file is loaded in numerical file order."""
    config_directory = config_directory or module_path.parent.parent
    lines = content.splitlines(keepends=True)
    include_entries: list[tuple[int, int]] = []
    for start_index, _end_index, logical_line in _logical_squid_line_locations(lines):
        path = _include_path(logical_line)
        if not path:
            continue
        if _include_matches_module(path, module_path, config_directory):
            return content
        include_entries.append((start_index, _include_rank(path)))

    desired_rank = _include_rank(str(module_path))
    insertion_index = len(lines)
    for index, rank in include_entries:
        if rank > desired_rank:
            insertion_index = index
            break
    if insertion_index == len(lines) and include_entries:
        insertion_index = include_entries[-1][0] + 1

    include_line = f"include {include_value if include_value is not None else module_path}\n"
    if insertion_index == len(lines):
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            include_line = "\n" + include_line
    lines.insert(insertion_index, include_line)
    return "".join(lines)


def _ensure_auth_include_before_access(
    content: str,
    module_path: Path,
    config_directory: Path,
    access_module_path: Path | None = None,
    acl_module_path: Path | None = None,
    *,
    include_value: str | Path | None = None,
) -> str:
    """Load an auth module before access rules and proxy-auth dependencies.

    A wildcard or explicit include after direct access rules, an ACL using
    ``proxy_auth``, or an ``external_acl_type`` that asks for ``%LOGIN``
    would define the authentication scheme too late. Adding another include
    in that situation could load the helper twice, so reject the ambiguous
    layout instead.
    """
    lines = content.splitlines(keepends=True)
    logical_locations = _logical_squid_line_locations(lines)
    matching_include_indices = [
        start_index
        for start_index, _end_index, logical_line in logical_locations
        if (include_path := _include_path(logical_line))
        and _include_matches_module(include_path, module_path, config_directory)
    ]
    access_indices = [
        start_index
        for start_index, _end_index, logical_line in logical_locations
        if _is_http_access_line(logical_line)
    ]
    for consumer_module_path in (access_module_path, acl_module_path):
        if consumer_module_path is None:
            continue
        access_indices.extend(
            start_index
            for start_index, _end_index, logical_line in logical_locations
            if (include_path := _include_path(logical_line))
            and _include_matches_module(
                include_path, consumer_module_path, config_directory
            )
        )
    dependency_indices = _direct_auth_dependency_indices(content, config_directory)
    consumer_indices = [*access_indices, *dependency_indices]
    first_consumer = min(consumer_indices) if consumer_indices else None
    if matching_include_indices:
        if first_consumer is not None and any(
            index > first_consumer for index in matching_include_indices
        ):
            raise KerberosConfigurationError(
                "El include de autenticación queda después de una regla o ACL que "
                "depende de autenticación. Muévelo antes de esas reglas o termina de "
                "modularizar la política antes de activar Kerberos."
            )
        return content
    if first_consumer is None:
        return _ensure_include(
            content,
            module_path,
            config_directory,
            include_value=include_value,
        )

    include_line = f"include {include_value if include_value is not None else module_path}\n"
    prefix = (
        ""
        if first_consumer == 0 or lines[first_consumer - 1].endswith("\n\n")
        else "\n"
    )
    lines.insert(first_consumer, prefix + include_line)
    return "".join(lines)


def _find_squid_binary() -> str | None:
    binary = shutil.which("squid")
    if binary:
        return binary
    for candidate in ("/usr/sbin/squid", "/usr/local/sbin/squid"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _configured_docker_container() -> str | None:
    """Return a safe Docker container name, if Docker validation is enabled."""
    container_name = os.getenv(
        "SQUID_DOCKER_CONTAINER", DEFAULT_DOCKER_CONTAINER
    ).strip()
    return container_name if _CONTAINER_NAME_RE.fullmatch(container_name) else None


def _configured_docker_config_path() -> str | None:
    """Return the in-container Squid config path, or None when unsafe."""
    configured_path = os.getenv("SQUID_CONTAINER_CONFIG_PATH", "").strip()
    if not configured_path:
        return DEFAULT_DOCKER_CONFIG_PATH
    return configured_path if _SAFE_PATH_RE.fullmatch(configured_path) else None


def _docker_runtime() -> _SquidRuntime | None:
    """Find the running Squid Docker container without relying on a shell."""
    docker_binary = shutil.which("docker")
    container_name = _configured_docker_container()
    if not docker_binary or not container_name:
        return None
    try:
        result = subprocess.run(  # nosec B603  # noqa: S603
            [
                docker_binary,
                "container",
                "inspect",
                "--format",
                "{{.State.Running}}",
                container_name,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or result.stdout.strip().casefold() != "true":
        return None

    return _SquidRuntime(
        kind="docker",
        executable=docker_binary,
        container_name=container_name,
        container_config_path=_configured_docker_config_path(),
    )


def _docker_mounts(
    runtime: _SquidRuntime,
) -> list[tuple[Path, PurePosixPath]] | None:
    """Return a single, sanitized snapshot of Docker mounts for *runtime*.

    ``None`` means inspection failed; an empty list means Docker answered but
    no usable mount was present.  Callers reuse a snapshot through one apply
    transaction so a changing mount table cannot produce inconsistent checks.
    """
    if runtime.kind != "docker" or not runtime.container_name:
        return None
    try:
        result = subprocess.run(  # nosec B603  # noqa: S603
            [runtime.executable, "container", "inspect", runtime.container_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        inspected = json.loads(result.stdout)
        raw_mounts = inspected[0].get("Mounts", []) if inspected else []
    except (TypeError, ValueError, IndexError, AttributeError):
        return None

    mounts: list[tuple[Path, PurePosixPath]] = []
    for mount in raw_mounts:
        source = mount.get("Source") if isinstance(mount, dict) else None
        destination = mount.get("Destination") if isinstance(mount, dict) else None
        if not isinstance(source, str) or not isinstance(destination, str):
            continue
        destination_path = PurePosixPath(destination)
        if not destination_path.is_absolute():
            continue
        mounts.append((Path(os.path.realpath(source)), destination_path))
    return mounts


def _docker_path_mapping_status(
    host_path: Path,
    mounts: list[tuple[Path, PurePosixPath]] | None,
    *,
    expected_container_path: str | None = None,
    mounts_checked: bool = True,
) -> dict[str, Any]:
    """Map a host config file to its visible path inside a Docker container.

    Docker permits overlapping mounts.  A host path matching a broad mount is
    not usable if a more-specific mount hides its resulting container path, so
    both namespaces are checked before reporting a mapping as valid.
    """
    status: dict[str, Any] = {
        "checked": mounts_checked and mounts is not None,
        "mapped": None,
        "container_path": None,
        "symlink": False,
    }
    if not mounts_checked or mounts is None:
        return status
    # SquidConfigManager resolves a final symlink before atomically replacing
    # its target.  Map that same real path rather than rejecting a valid
    # package-provided ``squid.conf`` symlink.
    status["symlink"] = host_path.is_symlink()

    resolved_host_path = Path(os.path.realpath(str(host_path)))
    host_matches: list[tuple[Path, PurePosixPath, Path]] = []
    for source, destination in mounts:
        try:
            relative_path = resolved_host_path.relative_to(source)
        except ValueError:
            continue
        host_matches.append((source, destination, relative_path))
    if not host_matches:
        status["mapped"] = False
        return status

    # The narrowest host source identifies the mount responsible for this
    # particular host path.
    source, destination, relative_path = max(
        host_matches, key=lambda match: len(match[0].parts)
    )
    mapped_path = destination / PurePosixPath(relative_path.as_posix())
    status["container_path"] = str(mapped_path)

    # A separate, more-specific mount at the container destination can hide
    # the path above.  In that case the file we edit is not what Squid sees.
    visible_mounts = []
    for visible_source, visible_destination in mounts:
        try:
            mapped_path.relative_to(visible_destination)
        except ValueError:
            continue
        visible_mounts.append((visible_source, visible_destination))
    if visible_mounts:
        visible_source, visible_destination = max(
            visible_mounts, key=lambda match: len(match[1].parts)
        )
        if visible_source != source or visible_destination != destination:
            status["mapped"] = False
            return status

    if expected_container_path is None:
        status["mapped"] = True
    else:
        status["mapped"] = (
            str(mapped_path) == str(PurePosixPath(expected_container_path))
        )
    return status


def _docker_config_mount_status(
    runtime: _SquidRuntime,
    config_path: Path,
    *,
    mounts: list[tuple[Path, PurePosixPath]] | None = None,
    mounts_checked: bool = False,
) -> dict[str, Any]:
    """Verify that the editable host main config maps to Squid's config path."""
    if not mounts_checked:
        mounts = _docker_mounts(runtime)
        mounts_checked = True
    status = _docker_path_mapping_status(
        config_path,
        mounts,
        expected_container_path=runtime.container_config_path,
        mounts_checked=mounts_checked,
    )
    status["container_config_path"] = runtime.container_config_path
    return status


def _docker_target_mapping_statuses(
    runtime: _SquidRuntime,
    targets: list[_ConfigTarget],
    main_path: Path,
    mounts: list[tuple[Path, PurePosixPath]] | None,
    *,
    mounts_checked: bool,
) -> dict[str, dict[str, Any]]:
    """Return mount status for every in-memory target using one snapshot."""
    main_realpath = os.path.realpath(str(main_path))
    return {
        str(target.path): _docker_path_mapping_status(
            target.path,
            mounts,
            expected_container_path=(
                runtime.container_config_path
                if os.path.realpath(str(target.path)) == main_realpath
                else None
            ),
            mounts_checked=mounts_checked,
        )
        for target in _unique_targets(targets)
    }


def _require_mapped_docker_targets(
    targets: list[_ConfigTarget],
    mapping_statuses: Mapping[str, Mapping[str, Any]],
    *,
    main_target: _ConfigTarget,
) -> None:
    """Refuse writes for changed config files that Docker cannot see safely."""
    changed_names = [
        target.name
        for target in _unique_targets(targets)
        if target.content != target.original
    ]
    unmapped = [
        target.name
        for target in _unique_targets(targets)
        if target.name in changed_names
        and mapping_statuses.get(str(target.path), {}).get("mapped") is not True
    ]
    # A changed included module is only meaningful if the daemon also loads
    # the exact main config that we validated for this transaction.
    if changed_names and (
        mapping_statuses.get(str(main_target.path), {}).get("mapped") is not True
    ):
        unmapped.append(main_target.name)
    if unmapped:
        raise KerberosConfigurationError(
            "No se pudo comprobar que los archivos que cambiarán estén montados en Docker "
            f"({', '.join(dict.fromkeys(unmapped))}). Revisa SQUID_CONTAINER_CONFIG_PATH y los volúmenes."
        )


def _docker_container_path_for_target(
    target: _ConfigTarget, mapping_statuses: Mapping[str, Mapping[str, Any]]
) -> Path:
    """Return the validated in-container path used in generated includes."""
    status = mapping_statuses.get(str(target.path), {})
    container_path = status.get("container_path")
    if status.get("mapped") is not True or not isinstance(container_path, str):
        raise KerberosConfigurationError(
            f"No se pudo determinar la ruta Docker del módulo {target.name}."
        )
    return Path(container_path)


def _docker_relative_include_value(
    main_target: _ConfigTarget,
    target: _ConfigTarget,
    mapping_statuses: Mapping[str, Mapping[str, Any]],
) -> str:
    """Return an include path that resolves to *target* in both namespaces.

    The editable configuration is on the host, while Squid parses the same
    text in the container.  Writing an absolute container path makes a later
    host-side ``SquidConfigManager`` select a nonexistent module directory.
    A relative include is safe only when both mount layouts preserve the same
    path from ``squid.conf`` to the module; otherwise fail before writing.
    """
    main_status = mapping_statuses.get(str(main_target.path), {})
    target_status = mapping_statuses.get(str(target.path), {})
    main_container_path = main_status.get("container_path")
    target_container_path = target_status.get("container_path")
    if (
        main_status.get("mapped") is not True
        or target_status.get("mapped") is not True
        or not isinstance(main_container_path, str)
        or not isinstance(target_container_path, str)
    ):
        raise KerberosConfigurationError(
            f"No se pudo determinar una ruta Docker segura para el módulo {target.name}."
        )

    host_main_directory = Path(os.path.realpath(str(main_target.path))).parent
    host_target_path = Path(os.path.realpath(str(target.path)))
    host_relative = os.path.relpath(host_target_path, host_main_directory).replace(
        os.sep, "/"
    )
    try:
        container_relative = str(
            PurePosixPath(target_container_path).relative_to(
                PurePosixPath(main_container_path).parent
            )
        )
    except ValueError as exc:
        raise KerberosConfigurationError(
            "Los volúmenes Docker no conservan una ruta relativa segura entre squid.conf y "
            f"{target.name}. Configura un include activo manualmente antes de continuar."
        ) from exc
    if host_relative != container_relative:
        raise KerberosConfigurationError(
            "Los volúmenes Docker no conservan la misma ruta relativa entre squid.conf y "
            f"{target.name}. Configura un include activo manualmente antes de continuar."
        )
    return host_relative


def _runtime_preference() -> str | None:
    """Return a valid runtime preference, without silently accepting typos."""
    preference = os.getenv("SQUID_RUNTIME", "auto").strip().casefold()
    return preference if preference in _RUNTIME_PREFERENCES else None


def _find_squid_runtime() -> _SquidRuntime | None:
    """Choose the runtime that owns the configured Squid instance.

    ``auto`` is deliberately conservative: when both a local binary and a
    Docker container are available, choosing the local one could validate and
    reload the wrong proxy. Administrators must select ``local`` or ``docker``
    explicitly in that case.
    """
    preference = _runtime_preference()
    if preference is None:
        logger.warning("Invalid SQUID_RUNTIME value; expected auto, local, or docker")
        return None

    local_runtime = None
    docker_runtime = None
    if preference in {"auto", "local"}:
        squid_binary = _find_squid_binary()
        if squid_binary:
            local_runtime = _SquidRuntime(kind="local", executable=squid_binary)
    if preference in {"auto", "docker"}:
        docker_runtime = _docker_runtime()

    if preference == "auto" and local_runtime and docker_runtime:
        logger.warning(
            "Both local and Docker Squid runtimes are available; set SQUID_RUNTIME explicitly"
        )
        return None
    return local_runtime or docker_runtime


def _runtime_selection_error() -> str | None:
    """Explain a runtime selection failure that cannot be inferred from None."""
    preference = _runtime_preference()
    if preference is None:
        return "SQUID_RUNTIME debe ser auto, local o docker."
    if preference == "local":
        if not _find_squid_binary():
            return "SQUID_RUNTIME=local está configurado, pero no se encontró Squid local."
        return None
    if preference == "docker":
        if not _docker_runtime():
            return (
                "SQUID_RUNTIME=docker está configurado, pero no se encontró el "
                "contenedor Squid en ejecución."
            )
        return None
    if _find_squid_binary() and _docker_runtime():
        return (
            "Se detectaron Squid local y Docker; define SQUID_RUNTIME=local o "
            "SQUID_RUNTIME=docker para no validar la instancia equivocada."
        )
    return None


def _squid_runtime_command(
    runtime: _SquidRuntime, action: str, config_path: str | Path
) -> list[str]:
    if runtime.kind == "local":
        return [runtime.executable, "-f", str(config_path), "-k", action]

    command = [runtime.executable, "exec", str(runtime.container_name), "squid"]
    if runtime.container_config_path:
        command.extend(["-f", runtime.container_config_path])
    command.extend(["-k", action])
    return command


def _runtime_description(runtime: _SquidRuntime | None) -> dict[str, Any]:
    if runtime is None:
        return {"available": False, "kind": None, "container": None}
    return {
        "available": True,
        "kind": runtime.kind,
        "container": runtime.container_name,
    }


def _default_squid_user(version_output: str) -> str | None:
    """Extract Squid's configured build-time user when it is safely known."""
    match = _SQUID_DEFAULT_USER_RE.search(version_output)
    if match is None:
        return None
    candidate = next((value for value in match.groups() if value), None)
    return candidate if candidate and _RUNTIME_USER_RE.fullmatch(candidate) else None


def _squid_version_status(runtime: _SquidRuntime | None) -> dict[str, Any]:
    """Return a minimal, non-sensitive Squid version capability status.

    ``auth_param`` is the directive required by this feature and was removed
    in Squid v8.  Parsing after a write remains the final authority, but this
    early check avoids writing a known-incompatible configuration.
    """
    status: dict[str, Any] = {
        "checked": False,
        "version": None,
        "supports_auth_param": None,
        "default_user": None,
    }
    if runtime is None:
        return status
    try:
        if runtime.kind == "docker":
            result = _docker_exec(runtime, ["squid", "-v"])
        else:
            result = subprocess.run(  # nosec B603  # noqa: S603
                [runtime.executable, "-v"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired):
        return status
    if result is None or result.returncode != 0:
        return status

    status["checked"] = True
    version_output = f"{result.stdout}\n{result.stderr}"
    status["default_user"] = _default_squid_user(version_output)
    version_match = _SQUID_VERSION_RE.search(version_output)
    if not version_match:
        return status
    version = version_match.group(1)
    status["version"] = version
    status["supports_auth_param"] = int(version.split(".", 1)[0]) < 8
    return status


def validate_squid_configuration(
    config_path: str | Path, runtime: _SquidRuntime | None = None
) -> dict[str, Any]:
    """Run a syntax parse against the local or configured Docker runtime."""
    runtime = runtime or _find_squid_runtime()
    runtime_error = _runtime_selection_error() if runtime is None else None
    if runtime is None:
        return {
            "available": False,
            "valid": None,
            "message": runtime_error
            or "No se encontró un runtime Squid local ni Docker.",
        }
    try:
        result = subprocess.run(  # nosec B603  # noqa: S603
            _squid_runtime_command(runtime, "parse", config_path),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Unable to parse Squid configuration: {}", exc)
        return {
            "available": True,
            "valid": False,
            "message": "No se pudo validar Squid.",
        }

    if result.returncode == 0:
        return {"available": True, "valid": True, "message": "Configuración validada."}
    logger.error(
        "Squid parse failed for {}: {}\n{}",
        config_path,
        result.stdout,
        result.stderr,
    )
    return {
        "available": True,
        "valid": False,
        "message": "Squid rechazó la configuración.",
    }


def reconfigure_squid(
    config_path: str | Path, runtime: _SquidRuntime | None = None
) -> tuple[bool, str]:
    """Ask a local or Docker Squid runtime to reload a parsed configuration."""
    runtime = runtime or _find_squid_runtime()
    if runtime is None:
        return False, "No se encontró un runtime Squid para recargar la configuración."
    try:
        result = subprocess.run(  # nosec B603  # noqa: S603
            _squid_runtime_command(runtime, "reconfigure", config_path),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Unable to reconfigure Squid: {}", exc)
        return False, "No se pudo recargar Squid."
    if result.returncode == 0:
        return True, "Squid recargado."
    logger.error(
        "Squid reconfigure failed for {}: {}\n{}",
        config_path,
        result.stdout,
        result.stderr,
    )
    return False, "Squid no pudo recargar la configuración."


def _user_has_unix_file_access(
    path: Path,
    username: str | None,
    owner_bit: int,
    group_bit: int,
    other_bit: int,
) -> bool | None:
    """Estimate whether a Squid account can access a file and traverse parents.

    This deliberately does not impersonate the service account or read a
    keytab. POSIX ACLs are not introspected, so a ``False`` is a conservative
    mode/group result rather than a replacement for ``sudo -u squid``.
    """
    if not username:
        return None
    try:
        account = (
            pwd.getpwuid(int(username))
            if username.isdecimal()
            else pwd.getpwnam(username)
        )
    except (KeyError, OSError, OverflowError, ValueError):
        return None

    groups = {account.pw_gid}
    try:
        groups.update(os.getgrouplist(username, account.pw_gid))
    except (AttributeError, OSError):
        pass

    def has_permission(
        file_stat: os.stat_result, owner_bit: int, group_bit: int, other_bit: int
    ) -> bool:
        if account.pw_uid == 0:
            return True
        if file_stat.st_uid == account.pw_uid:
            return bool(file_stat.st_mode & owner_bit)
        if file_stat.st_gid in groups:
            return bool(file_stat.st_mode & group_bit)
        return bool(file_stat.st_mode & other_bit)

    try:
        file_stat = path.stat()
        if not has_permission(file_stat, owner_bit, group_bit, other_bit):
            return False
        directory = path.parent
        while directory != directory.parent:
            if not has_permission(
                directory.stat(), stat.S_IXUSR, stat.S_IXGRP, stat.S_IXOTH
            ):
                return False
            directory = directory.parent
    except OSError:
        return False
    return True


def _user_has_unix_read_access(path: Path, username: str | None) -> bool | None:
    """Estimate whether a configured Squid user can traverse/read *path*."""
    return _user_has_unix_file_access(
        path, username, stat.S_IRUSR, stat.S_IRGRP, stat.S_IROTH
    )


def _user_has_unix_execute_access(path: Path, username: str | None) -> bool | None:
    """Estimate whether a configured Squid user can execute *path*."""
    return _user_has_unix_file_access(
        path, username, stat.S_IXUSR, stat.S_IXGRP, stat.S_IXOTH
    )


def _docker_exec(
    runtime: _SquidRuntime, arguments: list[str], *, user: str | None = None
) -> subprocess.CompletedProcess[str] | None:
    """Execute a fixed Docker command without returning its potentially sensitive output."""
    if runtime.kind != "docker" or not runtime.container_name:
        return None
    command = [runtime.executable, "exec"]
    if user and _RUNTIME_USER_RE.fullmatch(user):
        command.extend(["--user", user])
    command.extend([runtime.container_name, *arguments])
    try:
        return subprocess.run(  # nosec B603  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _docker_test(
    runtime: _SquidRuntime, option: str, path: str, *, user: str | None = None
) -> bool | None:
    """Return a Docker runtime file-test result, or None when it could not run."""
    result = _docker_exec(runtime, ["test", option, path], user=user)
    if result is None:
        return None
    return result.returncode == 0


def _mode_from_stat_output(output: str) -> int | None:
    """Parse the permission mode emitted by ``stat -c %a`` safely."""
    match = re.fullmatch(r"\s*([0-7]{3,4})\s*", output)
    return int(match.group(1), 8) if match else None


def _keytab_status(
    keytab_path: str,
    service_principal: str,
    squid_user: str | None = None,
    runtime: _SquidRuntime | None = None,
) -> dict[str, Any]:
    path = Path(keytab_path)
    status: dict[str, Any] = {
        "path": str(path),
        "check_available": True,
        "exists": False,
        "regular_file": False,
        "application_readable": False,
        "runtime_default_readable": None,
        "mode": None,
        "permissions_checked": False,
        "world_readable": False,
        "group_writable": False,
        "world_writable": False,
        "squid_user": squid_user,
        "squid_user_readable": None,
        "checked_in_runtime": bool(runtime and runtime.kind == "docker"),
        "spn_checked": False,
        "spn_present": None,
    }
    if runtime and runtime.kind == "docker":
        exists = _docker_test(runtime, "-e", keytab_path)
        regular_file = _docker_test(runtime, "-f", keytab_path)
        readable = _docker_test(runtime, "-r", keytab_path)
        checks = (exists, regular_file, readable)
        status.update(
            {
                "check_available": all(result is not None for result in checks),
                "exists": exists is True,
                "regular_file": regular_file is True,
                # This check uses Docker's default exec user (commonly root),
                # so it must not be presented as Squid's effective access.
                "runtime_default_readable": readable is True,
                "application_readable": None,
            }
        )
        if not status["check_available"]:
            return status
        if status["regular_file"]:
            mode_result = _docker_exec(runtime, ["stat", "-c", "%a", keytab_path])
            if mode_result and mode_result.returncode == 0:
                mode = _mode_from_stat_output(mode_result.stdout)
                if mode is not None:
                    status["permissions_checked"] = True
                    status["mode"] = f"{mode:04o}"
                    status["world_readable"] = bool(mode & stat.S_IROTH)
                    status["group_writable"] = bool(mode & stat.S_IWGRP)
                    status["world_writable"] = bool(mode & stat.S_IWOTH)
        if squid_user:
            if not _RUNTIME_USER_RE.fullmatch(squid_user):
                status["check_available"] = False
                return status
            squid_user_readable = _docker_test(
                runtime, "-r", keytab_path, user=squid_user
            )
            status["squid_user_readable"] = squid_user_readable
            if squid_user_readable is None:
                status["check_available"] = False
                return status
            # The helper is started by Squid's effective user, not necessarily
            # by Docker's default exec user (often root).
            status["application_readable"] = squid_user_readable is True
        if not status["regular_file"] or not status["application_readable"]:
            return status
        result = _docker_exec(
            runtime, ["klist", "-k", keytab_path], user=squid_user
        )
        if result and result.returncode == 0:
            status["spn_checked"] = True
            output = f"{result.stdout}\n{result.stderr}"
            status["spn_present"] = _keytab_contains_principal(
                output, service_principal
            )
        return status

    try:
        file_stat = path.stat()
    except OSError:
        return status

    status.update(
        {
            "exists": True,
            "regular_file": stat.S_ISREG(file_stat.st_mode),
            "application_readable": os.access(path, os.R_OK),
            "mode": f"{stat.S_IMODE(file_stat.st_mode):04o}",
            "permissions_checked": True,
            "world_readable": bool(file_stat.st_mode & stat.S_IROTH),
            "group_writable": bool(file_stat.st_mode & stat.S_IWGRP),
            "world_writable": bool(file_stat.st_mode & stat.S_IWOTH),
        }
    )
    status["squid_user_readable"] = _user_has_unix_read_access(path, squid_user)
    if (
        not status["regular_file"]
        or not status["application_readable"]
        or not service_principal
    ):
        return status

    klist = shutil.which("klist")
    if not klist:
        return status
    try:
        result = subprocess.run(  # nosec B603  # noqa: S603
            [klist, "-k", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return status
    if result.returncode == 0:
        status["spn_checked"] = True
        output = f"{result.stdout}\n{result.stderr}"
        status["spn_present"] = _keytab_contains_principal(output, service_principal)
    return status


def _helper_status(
    helper_path: str,
    runtime: _SquidRuntime | None = None,
    squid_user: str | None = None,
) -> dict[str, Any]:
    """Check helper execution from the perspective of Squid's account."""
    if runtime and runtime.kind == "docker":
        if squid_user and not _RUNTIME_USER_RE.fullmatch(squid_user):
            return {
                "path": helper_path,
                "check_available": False,
                "exists": False,
                "executable": False,
                "checked_in_runtime": True,
                "squid_user": squid_user,
                "squid_user_executable": None,
            }
        user = squid_user
        exists = _docker_test(runtime, "-f", helper_path, user=user)
        executable = _docker_test(runtime, "-x", helper_path, user=user)
        return {
            "path": helper_path,
            "check_available": exists is not None and executable is not None,
            "exists": exists is True,
            "executable": executable is True,
            "checked_in_runtime": True,
            "squid_user": squid_user,
            "squid_user_executable": executable if user else None,
        }
    path = Path(helper_path)
    application_executable = path.is_file() and os.access(path, os.X_OK)
    squid_user_executable = _user_has_unix_execute_access(path, squid_user)
    return {
        "path": str(path),
        "check_available": True,
        "exists": path.is_file(),
        "executable": (
            squid_user_executable
            if squid_user_executable is not None
            else application_executable
        ),
        "application_executable": application_executable,
        "squid_user": squid_user,
        "squid_user_executable": squid_user_executable,
        "checked_in_runtime": False,
    }


def _proxy_mode_status(config_manager) -> dict[str, Any]:
    main_content = str(getattr(config_manager, "config_content", "") or "")
    included_sources = _active_included_configuration_sources(config_manager)
    content_sources = [main_content, *(content for _path, content in included_sources)]
    # Keep compatibility with lightweight/legacy managers that know they are
    # modular but do not expose their active include lines to this service.
    if bool(getattr(config_manager, "is_modular", False)) and not included_sources:
        ports_content = _read_optional_module(config_manager, "00_ports.conf")
        if ports_content is not None:
            content_sources.append(ports_content)

    ports = [
        line.casefold()
        for content in content_sources
        for line in _logical_squid_lines(content)
        if _PORT_DIRECTIVE_RE.match(line)
    ]
    intercepted = [
        line
        for line in ports
        if re.search(r"(?:^|\s)(?:intercept|transparent|tproxy)(?:\s|$)", line)
    ]
    # ``accel`` turns a listener into reverse/accelerator mode.  It is not an
    # explicit forward proxy even though it lacks the interception keywords;
    # Negotiate's Proxy-Authorization exchange cannot be used there.
    accelerated = [
        line
        for line in ports
        if re.search(r"(?:^|\s)accel(?:\s|$)", line)
    ]
    # Connection-oriented authentication is how Negotiate/Kerberos works on
    # a forward-proxy listener. Squid documents connection-auth=off as
    # disabling forwarding of those exchanges, so a listener with that option
    # cannot be counted as usable for this feature.
    connection_auth_disabled = [
        line
        for line in ports
        if re.search(r"(?:^|\s)connection-auth\s*=\s*off(?:\s|$)", line)
    ]
    incompatible = [
        line
        for line in ports
        if line in intercepted
        or line in accelerated
        or line in connection_auth_disabled
    ]
    explicit = [line for line in ports if line not in incompatible]
    return {
        "ports_found": bool(ports),
        "explicit_proxy_available": bool(explicit) if ports else None,
        "intercept_ports": len(intercepted),
        "reverse_proxy_ports": len(accelerated),
        "connection_auth_disabled_ports": len(connection_auth_disabled),
        "incompatible_ports": len(incompatible),
    }


def _find_cache_effective_user(config_manager) -> str | None:
    included_sources = _active_included_configuration_sources(config_manager)
    contents = [
        str(getattr(config_manager, "config_content", "") or ""),
        *(content for _path, content in included_sources),
    ]
    if bool(getattr(config_manager, "is_modular", False)) and not included_sources:
        for filename in ("10_misc.conf", "30_cache.conf", "00_ports.conf"):
            content = _read_optional_module(config_manager, filename)
            if content:
                contents.append(content)
    for content in contents:
        for line in _logical_squid_lines(content):
            match = _CACHE_EFFECTIVE_USER_RE.match(line)
            if match:
                return match.group(1)
    return None


def _has_unmanaged_negotiate(content: str) -> bool:
    cleaned = _remove_managed_auth(content)
    return bool(_negotiate_directive_lines(cleaned))


def get_preflight(
    config_manager,
    settings: KerberosSettings | Mapping[str, Any],
    runtime: _SquidRuntime | None = None,
    *,
    docker_mounts: list[tuple[Path, PurePosixPath]] | None = None,
    docker_mounts_checked: bool = False,
) -> dict[str, Any]:
    """Inspect prerequisites without exposing keytab bytes or command output."""
    settings = _validated_settings(settings)

    manager_valid = bool(getattr(config_manager, "is_valid", False))
    config_path = Path(str(getattr(config_manager, "config_path", "squid.conf")))
    errors = (
        list(getattr(config_manager, "errors", []) or []) if not manager_valid else []
    )
    if manager_valid:
        errors.extend(_configuration_source_inspection_errors(config_manager))
    warnings: list[str] = []
    runtime = runtime or _find_squid_runtime()
    runtime_error = _runtime_selection_error() if runtime is None else None
    squid_version = _squid_version_status(runtime)
    if runtime is not None and runtime.kind == "docker" and not docker_mounts_checked:
        docker_mounts = _docker_mounts(runtime)
        docker_mounts_checked = True
    docker_config = (
        _docker_config_mount_status(
            runtime,
            config_path,
            mounts=docker_mounts,
            mounts_checked=docker_mounts_checked,
        )
        if runtime is not None and runtime.kind == "docker"
        else None
    )
    configured_squid_user = _find_cache_effective_user(config_manager)
    squid_user = configured_squid_user or squid_version.get("default_user")
    squid_user_source = (
        "cache_effective_user"
        if configured_squid_user
        else "build_default"
        if squid_user
        else None
    )
    helper = (
        _helper_status(settings.helper_path, runtime, squid_user)
        if settings.enabled
        else None
    )
    keytab = (
        _keytab_status(
            settings.keytab_path,
            settings.service_principal,
            squid_user,
            runtime,
        )
        if settings.enabled
        else None
    )
    proxy_mode = _proxy_mode_status(config_manager)

    manual_write_message = _manual_squid_write_message()
    config_writable = (
        manager_valid
        and manual_write_message is None
        and os.access(config_path, os.W_OK)
    )
    if manual_write_message:
        errors.append(manual_write_message)
    elif manager_valid and not config_writable:
        errors.append(
            "SquidStats no tiene permiso para escribir el squid.conf configurado."
        )
    if (
        manual_write_message is None
        and bool(getattr(config_manager, "is_modular", False))
    ):
        config_dir = Path(str(getattr(config_manager, "config_dir", "")))
        if not config_dir.is_dir() or not os.access(config_dir, os.W_OK):
            errors.append(
                "SquidStats no tiene permiso para escribir el directorio de configuración modular."
            )

    if settings.enabled:
        if runtime_error:
            errors.append(runtime_error)
        if settings.reload_squid and runtime is None:
            if not runtime_error:
                errors.append(
                    "No se encontró un runtime Squid local ni Docker para validar y recargar. "
                    "Desmarca la recarga solo si harás ambas operaciones manualmente."
                )
        if runtime is not None and runtime.kind == "docker":
            if not runtime.container_config_path:
                errors.append(
                    "SQUID_CONTAINER_CONFIG_PATH no es una ruta absoluta segura dentro del contenedor."
                )
            elif docker_config is None or docker_config["mapped"] is not True:
                errors.append(
                    "No se pudo comprobar que el squid.conf que edita SquidStats esté montado como "
                    "el archivo cargado por el contenedor Docker. Revisa SQUID_CONTAINER_CONFIG_PATH y el volumen."
                )
        if not squid_user:
            errors.append(
                "No se pudo determinar el usuario efectivo de Squid. Declara cache_effective_user "
                "o usa un runtime que informe su usuario predeterminado antes de aplicar, para "
                "comprobar el acceso real al keytab."
            )
        if squid_version["supports_auth_param"] is False:
            errors.append(
                "La versión de Squid detectada no admite auth_param; Kerberos/SPNEGO debe configurarse con un método compatible con Squid v8."
            )
        if not helper["check_available"]:
            errors.append("No se pudo comprobar el helper Kerberos en el runtime.")
        elif not helper["exists"]:
            errors.append("No se encontró el helper Kerberos indicado.")
        elif not helper["executable"]:
            errors.append("El helper Kerberos no tiene permiso de ejecución.")
        if not keytab["check_available"]:
            errors.append("No se pudo comprobar el keytab en el runtime de Squid.")
        elif not keytab["exists"]:
            errors.append("No se encontró el keytab indicado.")
        elif not keytab["regular_file"]:
            errors.append("La ruta del keytab no es un archivo regular.")
        elif runtime is not None and runtime.kind == "docker" and not keytab.get(
            "permissions_checked", False
        ):
            errors.append(
                "No se pudieron comprobar los permisos del keytab dentro del contenedor Docker."
            )
        elif not keytab["application_readable"] and not keytab["checked_in_runtime"]:
            warnings.append(
                "SquidStats no puede leer el keytab; verifica que el usuario efectivo de Squid sí pueda hacerlo."
            )
        elif keytab["application_readable"] is False:
            warnings.append(
                "El usuario efectivo de Squid no pudo leer el keytab dentro del runtime Docker; verifica el montaje y sus permisos."
            )
        elif keytab["application_readable"] is None:
            warnings.append(
                "No se pudo verificar el acceso del usuario efectivo de Squid al keytab dentro del runtime Docker."
            )
        if (
            runtime is not None
            and runtime.kind == "docker"
            and keytab["squid_user"]
            and keytab["squid_user_readable"] is False
        ):
            errors.append(
                "El usuario efectivo de Squid no puede leer el keytab dentro del contenedor. "
                "Corrige el montaje, propietario o grupo antes de aplicar."
            )
        elif keytab["squid_user"] and keytab["squid_user_readable"] is False:
            errors.append(
                "Los permisos Unix actuales no permiten leer el keytab al usuario efectivo de Squid. "
                "Corrige propietario, grupo, ACLs o directorios padre antes de aplicar."
            )
        elif (
            keytab["squid_user"]
            and keytab["exists"]
            and keytab["regular_file"]
            and keytab["squid_user_readable"] is None
        ):
            errors.append(
                "No se pudo verificar que el usuario efectivo de Squid exista y pueda leer el "
                "keytab. Corrige cache_effective_user o los permisos antes de aplicar."
            )
        elif squid_user_source == "build_default":
            warnings.append(
                "cache_effective_user no se declaró; se usó el usuario predeterminado "
                f"compilado de Squid ({squid_user}) para la comprobación. Confírmalo o "
                "decláralo explícitamente."
            )
        if keytab.get("world_readable"):
            errors.append(
                "El keytab es legible por todos los usuarios; restringe sus permisos antes de aplicar."
            )
        if keytab.get("group_writable") or keytab.get("world_writable"):
            errors.append(
                "El keytab es modificable por usuarios que no son su propietario; restringe "
                "los permisos de escritura antes de aplicar."
            )
        if keytab["spn_checked"] and not keytab["spn_present"]:
            errors.append("El keytab no contiene el SPN configurado.")
        elif not keytab["spn_checked"]:
            warnings.append(
                "No se pudo comprobar el SPN con klist; verifica el keytab en el runtime de Squid."
            )
        if proxy_mode["incompatible_ports"]:
            errors.append(
                "Kerberos/Negotiate no puede coexistir con puertos intercept, transparent, tproxy, accel "
                "(reverse proxy) ni connection-auth=off; sepáralos o elimina ese modo antes de aplicar."
            )
        elif proxy_mode["explicit_proxy_available"] is False:
            errors.append(
                "Kerberos/Negotiate requiere un proxy explícito; intercept, transparent, tproxy, accel y connection-auth=off no son compatibles."
            )
        elif proxy_mode["explicit_proxy_available"] is None:
            warnings.append(
                "No se encontraron puertos http_port/https_port para comprobar si el proxy es explícito."
            )

    return {
        "ready": not errors,
        "errors": errors,
        "warnings": warnings,
        "config": {
            "path": str(config_path),
            "writable": config_writable,
            "write_mode": _squid_config_write_mode(),
            "modular": bool(getattr(config_manager, "is_modular", False)),
        },
        "helper": helper,
        "keytab": keytab,
        "proxy_mode": proxy_mode,
        "squid_user": squid_user,
        "squid_user_source": squid_user_source,
        "runtime": _runtime_description(runtime),
        "docker_config": docker_config,
        "squid_version": squid_version,
        "squid_binary_available": runtime is not None,
    }


def _parse_auth_content(content: str) -> tuple[KerberosSettings, bool, bool]:
    """Return settings, whether Kerberos was found, and marker ownership."""
    managed_block = _find_complete_block(content, MANAGED_AUTH_START, MANAGED_AUTH_END)
    legacy_block = _find_complete_block(
        content, LEGACY_MANAGED_AUTH_START, LEGACY_MANAGED_AUTH_END
    )
    candidate = managed_block or legacy_block or content
    managed = managed_block is not None
    settings = default_settings()
    found = False

    for line in _logical_squid_lines(candidate):
        parts = line.split()
        lowered = [part.casefold() for part in parts]
        if len(parts) >= 4 and lowered[:3] == ["auth_param", "negotiate", "program"]:
            found = True
            helper_path = parts[3]
            keytab_path = settings.keytab_path
            service_principal = settings.service_principal
            strip_realm = "-r" in parts[4:]
            for index, item in enumerate(parts[4:], start=4):
                if item == "-k" and index + 1 < len(parts):
                    keytab_path = parts[index + 1]
                if item == "-s" and index + 1 < len(parts):
                    service_principal = parts[index + 1]
            settings = KerberosSettings(
                **{
                    **settings.to_dict(),
                    "enabled": True,
                    "helper_path": helper_path,
                    "keytab_path": keytab_path,
                    "service_principal": service_principal,
                    "strip_realm": strip_realm,
                }
            )
        elif len(parts) >= 4 and lowered[:3] == ["auth_param", "negotiate", "children"]:
            values = {
                item.split("=", 1)[0]: item.split("=", 1)[1]
                for item in parts[4:]
                if "=" in item
            }
            try:
                settings = KerberosSettings(
                    **{
                        **settings.to_dict(),
                        "children": int(parts[3]),
                        "startup": int(values.get("startup", settings.startup)),
                        "idle": int(values.get("idle", settings.idle)),
                    }
                )
            except ValueError:
                pass
        elif len(parts) >= 4 and lowered[:3] == [
            "auth_param",
            "negotiate",
            "keep_alive",
        ]:
            settings = KerberosSettings(
                **{
                    **settings.to_dict(),
                    "keep_alive": parts[3].casefold() == "on",
                }
            )
        elif (
            len(parts) >= 4
            and lowered[0] == "acl"
            and lowered[-2:] == ["proxy_auth", "required"]
        ):
            settings = KerberosSettings(**{**settings.to_dict(), "acl_name": parts[1]})

    return settings, found, managed


def _has_access_rule(content: str, acl_name: str) -> bool:
    expected = {
        f"http_access deny !{acl_name}".casefold(),
        # Recognise a manually maintained older form for status display. It
        # is not generated because it does not reliably force a challenge.
        f"http_access allow {acl_name}".casefold(),
    }
    return any(
        _uncommented(line).casefold() in expected for line in content.splitlines()
    )


def load_configuration(config_manager) -> dict[str, Any]:
    """Read current Squid Kerberos settings for the frontend without secrets."""
    main = _target_from_main(config_manager)
    modular = bool(getattr(config_manager, "is_modular", False))
    candidates: list[tuple[str, str]] = [("squid.conf", main.content)]
    access_contents = [main.content]
    included_sources = _active_included_configuration_sources(config_manager)
    active_paths = {os.path.realpath(path) for path, _content in included_sources}
    inactive_conventional_sources: list[str] = []
    auth: _ConfigTarget | None = None
    if modular:
        auth = _target_from_module(config_manager, AUTH_MODULE_FILENAME)
        access = _target_from_module(config_manager, HTTP_ACCESS_MODULE_FILENAME)
        if os.path.realpath(str(auth.path)) in active_paths:
            candidates.append((AUTH_MODULE_FILENAME, auth.content))
        elif auth.content and (
            _negotiate_directive_lines(auth.content)
            or MANAGED_AUTH_START in auth.content
            or LEGACY_MANAGED_AUTH_START in auth.content
        ):
            # Do not report inactive files as live Kerberos configuration.
            # Keep their presence visible so an administrator can decide
            # whether to remove them or include them deliberately.
            inactive_conventional_sources.append(AUTH_MODULE_FILENAME)
        if os.path.realpath(str(access.path)) in active_paths:
            access_contents.append(access.content)
        elif access.content and MANAGED_ACCESS_START in access.content:
            inactive_conventional_sources.append(HTTP_ACCESS_MODULE_FILENAME)

    managed_candidate_paths = {
        os.path.realpath(str(main.path)),
        *(
            [os.path.realpath(str(auth.path))]
            if auth is not None
            else []
        ),
    }
    external_candidates = [
        (path, content)
        for path, content in included_sources
        if os.path.realpath(path) not in managed_candidate_paths
    ]
    # Preserve the conventional files as the preferred source, but show an
    # active helper from a custom include instead of presenting the UI as
    # "not configured".  Such a source is deliberately not writable by this
    # managed flow; apply_configuration will require manual migration first.
    candidates.extend(external_candidates)
    candidate_contents = [content for _source, content in candidates]
    access_contents.extend(content for _source, content in included_sources)

    for _source, content in candidates:
        _assert_complete_managed_blocks(content)
    for content in access_contents:
        _assert_complete_managed_blocks(content)

    selected_source = "squid.conf"
    settings = default_settings()
    detected = False
    managed = False
    for source, content in candidates:
        parsed, found, owns_block = _parse_auth_content(content)
        if found:
            settings = parsed
            selected_source = source
            detected = True
            managed = owns_block and source in {
                "squid.conf",
                AUTH_MODULE_FILENAME,
            }
            break

    if detected:
        access_managed = any(
            MANAGED_ACCESS_START in content for content in access_contents
        )
        access_present = any(
            _has_access_rule(content, settings.acl_name) for content in access_contents
        )
        settings = KerberosSettings(
            **{
                **settings.to_dict(),
                "enforce_auth": access_managed or access_present,
                "reload_squid": True,
            }
        )

    return {
        "settings": settings.to_dict(),
        "detected": detected,
        "managed": managed,
        "source": selected_source,
        "unmanaged_negotiate": any(
            _has_unmanaged_negotiate(content) for content in candidate_contents
        )
        or any(
            _negotiate_directive_lines(content)
            for _path, content in external_candidates
        ),
        "other_auth_schemes": sorted(
            {
                scheme
                for content in [*candidate_contents, *(content for _path, content in included_sources)]
                for scheme in _other_auth_program_schemes(content)
            }
        ),
        "inactive_conventional_sources": inactive_conventional_sources,
    }


def get_status(config_manager) -> dict[str, Any]:
    """Return UI data and non-sensitive server-side prerequisite status."""
    load_error = None
    try:
        configuration = load_configuration(config_manager)
    except KerberosConfigurationError as exc:
        # Do not let a partially hand-edited marker hide the recovery UI.
        # Applying a change remains blocked by the same marker check until an
        # administrator repairs it manually.
        load_error = str(exc)
        configuration = {
            "settings": default_settings().to_dict(),
            "detected": False,
            "managed": False,
            "source": "squid.conf",
            "unmanaged_negotiate": False,
            "other_auth_schemes": [],
            "inactive_conventional_sources": [],
        }
    try:
        settings = normalise_settings(configuration["settings"])
        preview = render_preview(settings)
        preflight = get_preflight(config_manager, settings)
        configuration_error = load_error
        if load_error:
            preflight["ready"] = False
            preflight["errors"].insert(0, load_error)
    except KerberosConfigurationError as exc:
        # A hand-edited, incomplete configuration should remain visible in the
        # form instead of turning the administration page into a 500 error.
        settings = KerberosSettings(**configuration["settings"])
        preview = "# La configuración existente tiene valores inválidos; corrígelos antes de aplicar.\n"
        runtime = _find_squid_runtime()
        squid_version = _squid_version_status(runtime)
        manual_write_message = _manual_squid_write_message()
        preflight = {
            "ready": False,
            "errors": [
                str(exc),
                *([manual_write_message] if manual_write_message else []),
            ],
            "warnings": [],
            "config": {
                "path": str(getattr(config_manager, "config_path", "squid.conf")),
                "writable": bool(getattr(config_manager, "is_valid", False))
                and manual_write_message is None
                and os.access(str(getattr(config_manager, "config_path", "")), os.W_OK),
                "write_mode": _squid_config_write_mode(),
                "modular": bool(getattr(config_manager, "is_modular", False)),
            },
            "helper": None,
            "keytab": None,
            "proxy_mode": _proxy_mode_status(config_manager),
            "squid_user": _find_cache_effective_user(config_manager),
            "squid_user_source": None,
            "runtime": _runtime_description(runtime),
            "docker_config": None,
            "squid_version": squid_version,
            "squid_binary_available": runtime is not None,
        }
        configuration_error = str(exc)
    return {
        **configuration,
        "preflight": preflight,
        "preview": preview,
        "configuration_error": configuration_error,
    }


def _write_targets(targets: list[_ConfigTarget]) -> list[_ConfigTarget]:
    written: list[_ConfigTarget] = []
    for target in _unique_targets(targets):
        if target.content == target.original:
            continue
        try:
            saved = target.save(target.content)
        except Exception as exc:
            rollback_failures = _rollback_targets([*written, target])
            result = _rollback_result_message(
                f"No se pudo guardar {target.name}.", rollback_failures
            )
            raise KerberosConfigurationError(
                result
            ) from exc
        if not saved:
            # Most managers return False before changing a file, but include
            # the failed target as well in case an implementation wrote before
            # reporting its error.
            rollback_failures = _rollback_targets([*written, target])
            raise KerberosConfigurationError(
                _rollback_result_message(
                    f"No se pudo guardar {target.name}.", rollback_failures
                )
            )
        written.append(target)
    return written


def _rollback_targets(targets: list[_ConfigTarget]) -> list[str]:
    """Best-effort restore and return targets that could not be restored."""
    failures: list[str] = []
    for target in reversed(_unique_targets(targets)):
        try:
            # Empty, newly-created modules are harmless and avoid deleting a
            # path we did not own before the transaction.
            if not target.save(target.original):
                failures.append(target.name)
        except Exception:
            logger.exception("Could not roll back Kerberos target {}", target.name)
            failures.append(target.name)
    return failures


def _rollback_result_message(message: str, failures: list[str]) -> str:
    """Describe rollback truthfully without leaking implementation details."""
    if failures:
        return (
            f"{message} No se pudieron restaurar: {', '.join(dict.fromkeys(failures))}. "
            "Revisa los respaldos y el estado de Squid antes de continuar."
        )
    return f"{message} Se restauró la configuración anterior."


def _validate_prerequisites(
    config_manager,
    settings: KerberosSettings,
    runtime: _SquidRuntime | None = None,
    *,
    docker_mounts: list[tuple[Path, PurePosixPath]] | None = None,
    docker_mounts_checked: bool = False,
) -> dict[str, Any]:
    preflight = get_preflight(
        config_manager,
        settings,
        runtime,
        docker_mounts=docker_mounts,
        docker_mounts_checked=docker_mounts_checked,
    )
    if preflight["errors"]:
        raise KerberosConfigurationError(" ".join(preflight["errors"]))
    if not preflight["config"]["writable"]:
        raise KerberosConfigurationError(
            "SquidStats no tiene permiso para escribir el squid.conf configurado."
        )
    return preflight


def apply_configuration(
    data: Mapping[str, Any] | KerberosSettings, config_manager
) -> dict[str, Any]:
    """Apply one Kerberos change at a time against freshly loaded config."""
    with _APPLY_LOCK:
        config_path = str(getattr(config_manager, "config_path", "squid.conf"))
        with squid_config_write_lock(config_path):
            _refresh_config_manager(config_manager)
            return _apply_configuration(data, config_manager)


def _refresh_config_manager(config_manager) -> None:
    """Avoid overwriting a change made since the shared manager was created."""
    if not bool(getattr(config_manager, "is_valid", False)):
        return
    load_config = getattr(config_manager, "load_config", None)
    if not callable(load_config):
        return
    try:
        if load_config() is False:
            raise KerberosConfigurationError(
                "No se pudo recargar squid.conf antes de aplicar Kerberos."
            )
        refresh_layout = getattr(config_manager, "_check_modular_config", None)
        if callable(refresh_layout):
            refresh_layout()
    except KerberosConfigurationError:
        raise
    except Exception as exc:
        raise KerberosConfigurationError(
            "No se pudo recargar squid.conf antes de aplicar Kerberos."
        ) from exc


def _apply_configuration(
    data: Mapping[str, Any] | KerberosSettings, config_manager
) -> dict[str, Any]:
    """Safely add, update, or remove the managed Kerberos Squid directives.

    The writes are rolled back if parsing or the optional live reconfiguration
    fails.  No keytab bytes are ever read or copied by this operation.
    """
    settings = _validated_settings(data)
    if manual_write_message := _manual_squid_write_message():
        # This also prevents a "disable" request from attempting a write.
        # The packaged Debian service cannot escape ProtectSystem=full, even
        # when the Unix mode bits themselves appear writable.
        raise KerberosConfigurationError(manual_write_message)
    if not bool(getattr(config_manager, "is_valid", False)):
        raise KerberosConfigurationError(
            "La configuración de Squid no está disponible para escritura."
        )
    inspection_errors = _configuration_source_inspection_errors(config_manager)
    if inspection_errors:
        raise KerberosConfigurationError(" ".join(inspection_errors))

    main = _target_from_main(config_manager)
    modular = bool(getattr(config_manager, "is_modular", False))
    auth = (
        _target_from_module(config_manager, AUTH_MODULE_FILENAME) if modular else main
    )
    acl_module = (
        _target_from_module(config_manager, ACL_MODULE_FILENAME) if modular else main
    )
    access_module = (
        _target_from_module(config_manager, HTTP_ACCESS_MODULE_FILENAME)
        if modular
        else main
    )
    access = (
        _access_target(config_manager, main, modular, access_module)
        if settings.enabled and settings.enforce_auth
        else access_module
    )
    # Always include both possible access locations so turning enforcement off
    # (or migrating layouts) cannot leave a stale managed challenge behind.
    # Write generated modules before squid.conf starts including them; rollback
    # then happens in the opposite order and removes the includes first.
    targets = _unique_targets(
        [auth, acl_module, access_module, access, main] if modular else [main]
    )
    if settings.enabled and modular:
        _reject_indirect_active_module(config_manager, main, auth)
        if settings.enforce_auth and not _same_target(access, main):
            _reject_indirect_active_module(config_manager, main, access)
    # Discover this only once. In particular, an explicit Docker preference
    # must be honoured for both validation and the subsequent reconfigure.
    runtime = _find_squid_runtime()
    docker_mounts_checked = bool(runtime and runtime.kind == "docker")
    if docker_mounts_checked and not runtime.container_config_path:
        raise KerberosConfigurationError(
            "SQUID_CONTAINER_CONFIG_PATH no es una ruta absoluta segura dentro del contenedor."
        )
    docker_mounts = _docker_mounts(runtime) if docker_mounts_checked else None
    docker_target_mappings = (
        _docker_target_mapping_statuses(
            runtime,
            targets,
            main.path,
            docker_mounts,
            mounts_checked=docker_mounts_checked,
        )
        if docker_mounts_checked
        else {}
    )

    # Remove blocks from both possible locations. This also migrates the old
    # experimental marker safely if an administrator had used it before.
    for target in targets:
        target.content = _remove_managed_auth(target.content)
        target.content = _remove_managed_access(target.content)

    if not settings.enabled:
        written: list[_ConfigTarget] = []
        try:
            if docker_mounts_checked:
                _require_mapped_docker_targets(
                    targets, docker_target_mappings, main_target=main
                )
            written = _write_targets(targets)
            validation = validate_squid_configuration(main.path, runtime)
            if validation["available"] and not validation["valid"]:
                raise KerberosConfigurationError(
                    "Squid rechazó la configuración tras retirar Kerberos."
                )
        except Exception as exc:
            if not written and isinstance(exc, KerberosConfigurationError):
                raise
            rollback_failures = _rollback_targets(written)
            raise KerberosConfigurationError(
                _rollback_result_message(
                    "No se pudo retirar Kerberos.", rollback_failures
                )
            ) from exc
        return {
            "status": "success",
            "message": "Bloques Kerberos administrados eliminados. Reinicia Squid para deshabilitar el esquema de autenticación.",
            "validation": validation,
            "reconfigured": False,
            "restart_required": True,
            "settings": settings.to_dict(),
        }

    preflight = _validate_prerequisites(
        config_manager,
        settings,
        runtime,
        docker_mounts=docker_mounts,
        docker_mounts_checked=docker_mounts_checked,
    )
    negotiate_targets = _unique_targets([main, auth])
    acl_targets = _unique_targets([main, auth, acl_module])
    included_sources = _active_included_configuration_sources(config_manager)
    managed_target_paths = {
        os.path.realpath(str(target.path)) for target in negotiate_targets
    }
    external_negotiate_sources = [
        path
        for path, content in included_sources
        if os.path.realpath(path) not in managed_target_paths
        and _negotiate_directive_lines(content)
    ]
    if external_negotiate_sources:
        raise KerberosConfigurationError(
            "Se detectó una directiva Negotiate en un archivo incluido fuera de squid.conf/50_auth.conf. "
            "SquidStats no puede reemplazarlo de forma segura; migra esa configuración manualmente antes de continuar."
        )
    other_schemes = sorted(
        {
            scheme
            for content in [
                *(target.content for target in negotiate_targets),
                *(content for _path, content in included_sources),
            ]
            for scheme in _other_auth_program_schemes(content)
        }
    )
    if other_schemes:
        raise KerberosConfigurationError(
            "Se detectaron helpers de autenticación alternativos "
            f"({', '.join(other_schemes)}). Esta pantalla configura solo Negotiate/Kerberos; "
            "revísalos y desactívalos manualmente antes de continuar."
        )
    if (
        any(_has_unmanaged_negotiate(target.content) for target in negotiate_targets)
        and not settings.replace_existing_negotiate
    ):
        raise KerberosConfigurationError(
            "Ya existe una directiva Negotiate no administrada. Activa 'reemplazar configuración existente' "
            "solo después de revisarlo."
        )
    if settings.replace_existing_negotiate:
        for target in negotiate_targets:
            target.content = _remove_conflicting_negotiate_directives(target.content)
        for target in acl_targets:
            target.content = _remove_acl(target.content, settings.acl_name)

    # An ACL name is global to the complete active configuration. Looking at
    # only the conventional main/auth/ACL modules misses a definition in a
    # custom or access include, producing a syntactically valid-looking
    # preview that Squid later rejects. Use each target's in-memory content
    # (managed blocks have already been removed there) and inspect every other
    # active include without trying to rewrite administrator-owned fragments.
    target_contents = {
        os.path.realpath(str(target.path)): target.content
        for target in _unique_targets(targets)
    }
    acl_name_sources: list[str] = []
    for target in _unique_targets(targets):
        if _has_acl_definition(target.content, settings.acl_name):
            acl_name_sources.append(target.name)
    for path, content in included_sources:
        canonical_path = os.path.realpath(path)
        if canonical_path in target_contents:
            continue
        if _has_acl_definition(content, settings.acl_name):
            acl_name_sources.append(Path(path).name)
    if acl_name_sources:
        raise KerberosConfigurationError(
            f"Ya existe una ACL llamada '{settings.acl_name}' en "
            f"{', '.join(dict.fromkeys(acl_name_sources))}; SquidStats no puede reemplazarla de forma segura. "
            "Usa otro nombre o revísala manualmente antes de continuar."
        )

    auth.content = _insert_before_first_http_access(
        auth.content, _auth_block(settings), config_path=auth.path
    )

    if settings.enforce_auth:
        if _has_access_rule(access.content, settings.acl_name) and not settings.replace_existing_negotiate:
            raise KerberosConfigurationError(
                "Ya existe una regla http_access manual para esta ACL. Activa el reemplazo "
                "solo después de revisarla, o usa otra ACL."
            )
        if settings.replace_existing_negotiate:
            access.content = _remove_access_rule(access.content, settings.acl_name)

        # A previous quota sync may have generated this denial before
        # Kerberos existed.  Remove it while choosing the safe challenge
        # location, then put it immediately after the managed challenge.
        # Besides avoiding a premature proxy_auth lookup, this lets us repair
        # a stale quota rule that had drifted below a normal client allow.
        active_acl_contents = [
            main.content,
            *(content for _path, content in included_sources),
        ]
        access.content, quota_proxy_auth_deny = _take_proxy_auth_quota_deny(
            access.content, active_acl_contents
        )
        access.content = _add_access_block(
            access.content, settings, acl_contents=active_acl_contents
        )
        if quota_proxy_auth_deny is not None:
            access.content = _restore_proxy_auth_quota_deny(
                access.content, quota_proxy_auth_deny
            )

    if modular:
        include_directory = main.path.parent
        auth_include_path = auth.path
        access_include_path = access.path
        auth_include_value: str | Path = auth.path
        access_include_value: str | Path = access.path
        if docker_mounts_checked:
            # Match existing include directives in the host namespace, but
            # write a relative path that resolves to the same module in both
            # the host and container namespaces.
            auth_include_value = _docker_relative_include_value(
                main, auth, docker_target_mappings
            )
            if settings.enforce_auth and not _same_target(access, main):
                access_include_value = _docker_relative_include_value(
                    main, access, docker_target_mappings
                )
        if not _same_target(auth, main):
            main.content = _ensure_auth_include_before_access(
                main.content,
                auth_include_path,
                include_directory,
                None if _same_target(access, main) else access_include_path,
                acl_module.path,
                include_value=auth_include_value,
            )
        if settings.enforce_auth and not _same_target(access, main):
            main.content = _ensure_include(
                main.content,
                access_include_path,
                include_directory,
                include_value=access_include_value,
            )

    if docker_mounts_checked:
        _require_mapped_docker_targets(
            targets, docker_target_mappings, main_target=main
        )

    written: list[_ConfigTarget] = []
    reconfiguration_attempted = False
    try:
        written = _write_targets(targets)
        validation = validate_squid_configuration(main.path, runtime)
        if validation["available"] and not validation["valid"]:
            raise KerberosConfigurationError(
                "Squid rechazó la configuración."
            )
        if settings.reload_squid:
            if not validation["available"]:
                raise KerberosConfigurationError(
                    "No se encontró Squid para validar y recargar; desmarca la recarga solo si la harás manualmente."
                )
            reconfiguration_attempted = True
            reconfigured, reload_message = reconfigure_squid(main.path, runtime)
            if not reconfigured:
                raise KerberosConfigurationError(reload_message)
        else:
            reconfigured = False

        warning = None
        if not settings.reload_squid:
            warning = (
                "La configuración se escribió, pero no se recargó. Valida y recarga "
                "(o reinicia) Squid manualmente para activarla."
            )
        return {
            "status": "warning" if warning else "success",
            "message": warning or "Autenticación Kerberos configurada en Squid.",
            "validation": validation,
            "reconfigured": reconfigured,
            "restart_required": not settings.reload_squid,
            "reload_required": not settings.reload_squid,
            "settings": settings.to_dict(),
            "preflight": preflight,
        }
    except Exception as exc:
        # A write failure has already performed its own targeted rollback.
        # If no target was written, there is nothing to restore here.
        if not written:
            if isinstance(exc, KerberosConfigurationError):
                raise
            raise KerberosConfigurationError(
                "No se pudo completar la configuración Kerberos antes de modificar Squid."
            ) from exc

        rollback_failures = _rollback_targets(written)
        runtime_recovery_error = None
        if reconfiguration_attempted and not rollback_failures:
            restored, restore_message = reconfigure_squid(main.path, runtime)
            if not restored:
                runtime_recovery_error = restore_message

        message = _rollback_result_message(str(exc), rollback_failures)
        if runtime_recovery_error:
            message += (
                " No se pudo recargar la configuración restaurada "
                f"({runtime_recovery_error}). Reinicia Squid y revisa los respaldos antes de continuar."
            )
        raise KerberosConfigurationError(message) from exc
