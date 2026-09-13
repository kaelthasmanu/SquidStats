import ipaddress
import os
import re
import subprocess  # nosec B404
from collections.abc import Callable

from loguru import logger

from services.squid.kerberos_config_service import (
    _active_included_configuration_sources,
    _find_squid_runtime,
    reconfigure_squid,
)
from services.squid.squid_config_splitter import SquidConfigSplitter
from utils.admin import SquidConfigManager, squid_config_write_lock

_BLOCKED_USERS_PATH = "/etc/squid/usuarios_bloqueados.txt"
_KERBEROS_AUTH_START = "# BEGIN SquidStats Kerberos authentication"
_KERBEROS_AUTH_END = "# END SquidStats Kerberos authentication"
_KERBEROS_ACCESS_START = "# BEGIN SquidStats Kerberos access rule"
_KERBEROS_ACCESS_END = "# END SquidStats Kerberos access rule"


def _normalised_squid_line(line: str) -> str:
    """Return a directive suitable for exact ownership checks.

    The quota feature owns only its generated ACL/include pair.  Comparing
    tokens rather than prefixes prevents a similarly named administrator ACL
    (for example ``usuarios_bloqueados_extra``) from being removed.
    """
    return line.strip().split("#", 1)[0].strip()


def _is_quota_acl_entry(line: str, blocked_path: str) -> bool:
    """Whether *line* is either generated representation of the quota ACL.

    Before proxy authentication is configured, the quota list is a Squid
    ``include`` containing ``acl ... src`` entries.  With authentication it
    becomes a ``proxy_auth -i`` value list.  They are mutually exclusive:
    retaining both during a transition can either duplicate the ACL name or
    make Squid parse plain usernames as configuration directives.
    """
    parts = _normalised_squid_line(line).split()
    if not parts:
        return False
    if (
        len(parts) == 2
        and parts[0].casefold() == "include"
        and parts[1].strip('"').strip("'") == blocked_path
    ):
        return True
    return (
        len(parts) >= 2
        and parts[0].casefold() == "acl"
        and parts[1].casefold() == "usuarios_bloqueados"
    )


def _normalised_http_access_line(line: str) -> str:
    """Return a comparable Squid directive without an inline comment."""
    return line.strip().split("#", 1)[0].strip()


def _is_local_cache_manager_allow(line: str) -> bool:
    """Whether a line is the narrow Cache Manager exception.

    A broad ``allow manager`` or a negated ACL must not be treated as the
    management exception because either may authorize ordinary proxy traffic.
    """
    parts = _normalised_http_access_line(line).split()
    lowered = [part.casefold() for part in parts]
    return (
        len(lowered) == 4
        and lowered[:2] == ["http_access", "allow"]
        and set(lowered[2:]) == {"manager", "localhost"}
    )


def _managed_kerberos_modular_layout_is_supported(cm: SquidConfigManager) -> bool:
    """Refuse quota writes to inactive/ambiguous modules under Kerberos.

    Kerberos can safely manage a monolithic policy, or its dedicated standard
    modules.  A generic modular flag alone is not enough: it may be caused by
    a custom include while the active HTTP policy still lives in squid.conf.
    In that situation writing quota ACL/rules to 100/120 would either do
    nothing or create an allow/deny ordering the daemon never validated.
    """
    if not cm.is_modular:
        return True
    inspection_errors: list[str] = []
    try:
        included_sources = _active_included_configuration_sources(
            cm, inspection_errors=inspection_errors
        )
    except Exception as exc:
        logger.error("No se pudieron inspeccionar includes para cuotas Kerberos: {}", exc)
        return False

    main_path = os.path.realpath(cm.config_path)
    sources = [(main_path, cm.config_content or ""), *included_sources]
    managed_access_sources = [
        path
        for path, content in sources
        if _KERBEROS_ACCESS_START in content and _KERBEROS_ACCESS_END in content
    ]
    if not managed_access_sources:
        return True

    expected_paths = {
        "auth": os.path.realpath(os.path.join(cm.config_dir, "50_auth.conf")),
        "acls": os.path.realpath(os.path.join(cm.config_dir, "100_acls.conf")),
        "access": os.path.realpath(
            os.path.join(cm.config_dir, "120_http_access.conf")
        ),
    }
    active_contents = {os.path.realpath(path): content for path, content in sources}
    auth_content = active_contents.get(expected_paths["auth"], "")
    if (
        inspection_errors
        or expected_paths["acls"] not in active_contents
        or _KERBEROS_AUTH_START not in auth_content
        or _KERBEROS_AUTH_END not in auth_content
        or expected_paths["access"] not in managed_access_sources
    ):
        logger.error(
            "No se sincronizaron cuotas: Kerberos está activo en un diseño modular "
            "que no usa 50_auth.conf, 100_acls.conf y 120_http_access.conf activos "
            "en sus ubicaciones estándar. Migra la política desde Kerberos / SPNEGO."
        )
        return False
    return True


def _proxy_auth_deny_insert_index(lines: list[str]) -> int:
    """Choose a safe position for the quota's proxy-auth denial.

    A proxy-auth ACL can initiate an authentication lookup.  It therefore has
    to remain after the local Cache Manager exception and after the managed
    Kerberos challenge, but before the first normal client allow rule.
    """
    managed_end = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if line.strip() == _KERBEROS_ACCESS_END
        ),
        None,
    )
    if managed_end is not None:
        return managed_end

    first_client_allow = next(
        (
            index
            for index, line in enumerate(lines)
            if _normalised_http_access_line(line).casefold().startswith(
                "http_access allow"
            )
            and not _is_local_cache_manager_allow(line)
        ),
        None,
    )
    if first_client_allow is None:
        # Keep a deny rule reachable when a configuration lacks a normal allow
        # line, without placing it after the final catch-all deny.
        return next(
            (
                index
                for index, line in enumerate(lines)
                if _normalised_http_access_line(line).casefold()
                == "http_access deny all"
            ),
            len(lines),
        )

    # Security denials and a manual proxy-auth challenge belong before the
    # quota rule.  Insert after the last such denial, yet before the client
    # allow that would otherwise bypass it.
    last_deny = max(
        (
            index
            for index, line in enumerate(lines[:first_client_allow])
            if _normalised_http_access_line(line).casefold().startswith(
                "http_access deny"
            )
        ),
        default=None,
    )
    return last_deny + 1 if last_deny is not None else first_client_allow


def _ensure_quota_http_rule(
    lines: list[str], http_line: str, *, use_src: bool
) -> list[str]:
    """Add (or reposition) the quota deny rule without bypassing auth.

    The IP-based fallback keeps its historical early placement.  A quota that
    uses ``proxy_auth`` is ordered deliberately because touching it before the
    Cache Manager exception can turn local manager requests into 407s.
    """
    def is_quota_rule(line: str) -> bool:
        return _normalised_http_access_line(line).casefold() == http_line.casefold()
    if use_src:
        if any(is_quota_rule(line) for line in lines):
            return lines
        insertion = next(
            (
                index
                for index, line in enumerate(lines)
                if _normalised_http_access_line(line).casefold().startswith(
                    "http_access "
                )
            ),
            len(lines),
        )
        return [*lines[:insertion], http_line, *lines[insertion:]]

    without_existing = [line for line in lines if not is_quota_rule(line)]
    insertion = _proxy_auth_deny_insert_index(without_existing)
    return [
        *without_existing[:insertion],
        http_line,
        *without_existing[insertion:],
    ]


def _file_has_content(path: str) -> bool:
    """Devuelve True si el archivo existe y contiene al menos una entrada real."""
    try:
        if not os.path.exists(path):
            return False
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                return True
        return False
    except Exception:
        return False


def _has_compatible_blocked_file_content(path: str, use_src: bool) -> bool:
    """Whether a value file is safe for the ACL representation being enabled.

    A plain username is not valid content for a Squid ``include`` file, and a
    source ACL directive is not an authenticated username.  Do not activate a
    representation unless at least one valid entry already matches it.
    """
    blocked_usernames, _preserved_lines = _read_blocked_usernames(path, use_src)
    return bool(blocked_usernames)


def _sync_blocked_file_to_docker(blocked_path: str) -> bool:
    """Copy the blocked-user list only to the selected Docker Squid runtime.

    A host can have both a local Squid binary and more than one Docker
    container.  Do not use a hard-coded container name here: the quota ACL
    must be kept in sync with the same runtime selected for validation and
    reconfiguration.
    """
    runtime = _find_squid_runtime()
    if (
        runtime is None
        or runtime.kind != "docker"
        or not runtime.container_name
    ):
        logger.debug(
            "No se sincronizó %s por docker cp: el runtime Squid seleccionado no es Docker",
            blocked_path,
        )
        return False
    try:
        subprocess.run(  # nosec B603  # noqa: S603
            [
                runtime.executable,
                "cp",
                blocked_path,
                f"{runtime.container_name}:{blocked_path}",
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
        return True
    except Exception as e:
        logger.debug("No se pudo sincronizar %s a Docker: %s", blocked_path, e)
        return False


_SRC_BLOCK_ENTRY_RE = re.compile(
    r"^acl\s+usuarios_bloqueados\s+src\s+(\S+)\s*$", re.IGNORECASE
)


def _is_valid_src_value(value: str) -> bool:
    """Return whether an entry can safely be emitted in a ``src`` ACL.

    The quota table normally contains client IPs when proxy authentication is
    off.  Treating an arbitrary username as an ACL value is unsafe: a newline
    or another Squid directive would turn the included value file into active
    configuration.  Restrict this representation to IP addresses/networks,
    which is also what the ``src`` ACL accepts for this use case.
    """
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return True


def _is_valid_proxy_auth_value(value: str) -> bool:
    """Return whether a value is safe as one line of a proxy_auth list."""
    return (
        bool(value)
        and "#" not in value
        and not any(char.isspace() for char in value)
    )


def _is_preservable_blocked_file_line(raw_line: str) -> bool:
    """Keep comments/blank lines, but never incompatible list data.

    A source-format list is parsed as Squid configuration while a proxy-auth
    list is parsed as identities.  Preserving arbitrary non-comment lines
    across a mode change was the root cause of malformed ``include`` files.
    """
    stripped = raw_line.strip()
    return not stripped or stripped.startswith("#")


def _parse_blocked_file_line(raw_line: str, use_src: bool) -> str | None:
    """Parse one entry only when it belongs to the requested representation."""
    raw = raw_line.strip()
    if not raw or raw.startswith("#"):
        return None
    source_directive = _normalised_squid_line(raw)
    match = _SRC_BLOCK_ENTRY_RE.fullmatch(source_directive)
    if use_src:
        if match and _is_valid_src_value(match.group(1)):
            return match.group(1)
        return None

    # A previous IP-based representation is not a username.  Dropping it is
    # safer than accidentally blocking a literal identity named ``acl`` (or
    # emitting a malformed source include on a later transition).
    if match:
        return None
    parts = [part.strip() for part in raw.split(" - ")]
    value = parts[1] if len(parts) > 1 else parts[0]
    return value if _is_valid_proxy_auth_value(value) else None


def _read_blocked_usernames(
    file_path: str, use_src: bool
) -> tuple[set[str], list[str]]:
    blocked_usernames: set[str] = set()
    preserved_lines: list[str] = []
    if not os.path.exists(file_path):
        return blocked_usernames, preserved_lines

    try:
        with open(file_path, encoding="utf-8") as f:
            for raw_line in f:
                username = _parse_blocked_file_line(raw_line, use_src)
                if username is None:
                    if _is_preservable_blocked_file_line(raw_line):
                        preserved_lines.append(raw_line.rstrip("\n"))
                    elif raw_line.strip():
                        logger.warning(
                            "Se descartó una entrada de cuota incompatible con el modo %s: %s",
                            "src" if use_src else "proxy_auth",
                            raw_line.strip(),
                        )
                else:
                    blocked_usernames.add(username)
    except Exception as e:
        logger.warning("No se pudo leer %s: %s", file_path, e)

    return blocked_usernames, preserved_lines


def _render_block_entry(username: str, use_src: bool) -> str | None:
    """Render one safely validated quota value for the selected ACL mode."""
    value = str(username).strip()
    if use_src:
        if not _is_valid_src_value(value):
            logger.warning("Se omitió una cuota sin IP/red válida para ACL src: %s", value)
            return None
        return f"acl usuarios_bloqueados src {value}"
    if not _is_valid_proxy_auth_value(value):
        logger.warning("Se omitió una identidad proxy_auth no válida: %s", value)
        return None
    return value


def _render_block_entries(usernames: set[str], use_src: bool) -> list[str]:
    """Render a deterministic, validated complete quota list."""
    entries: list[str] = []
    for username in sorted({str(username) for username in usernames}):
        entry = _render_block_entry(username, use_src)
        if entry is not None:
            entries.append(entry)
    return entries


def _build_blocked_users_file_content(
    file_path: str, usernames: set[str], use_src: bool
) -> tuple[str | None, set[str]]:
    """Build the complete target file without writing it.

    Returning ``None`` means the file should not exist.  This makes an empty
    quota set an explicit state transition rather than a silently ignored
    deletion.
    """
    existing_blocked, preserved_lines = _read_blocked_usernames(file_path, use_src)
    output_lines = [*preserved_lines, *_render_block_entries(usernames, use_src)]
    if not output_lines:
        return None, existing_blocked
    return "\n".join(output_lines).rstrip() + "\n", existing_blocked


def _sync_blocked_users_file(
    file_path: str, usernames: set[str], use_src: bool
) -> tuple[bool, set[str]]:
    new_content, existing_blocked = _build_blocked_users_file_content(
        file_path, usernames, use_src
    )

    if new_content is None:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                return True, existing_blocked
            except Exception as e:
                logger.warning("No se pudo eliminar %s: %s", file_path, e)
        return False, existing_blocked

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as f:
                current_content = f.read()
            if current_content == new_content:
                return False, existing_blocked

        # Do not truncate a live value list.  The same atomic replacement
        # primitive used for squid.conf preserves the old file until the new
        # complete representation is ready.
        SquidConfigManager._atomic_write(file_path, new_content)

        try:
            os.chmod(file_path, 0o640)
        except Exception as e:
            logger.warning("No se pudo fijar permisos en %s: %s", file_path, e)

        return True, existing_blocked
    except Exception as e:
        logger.warning("No se pudo escribir %s: %s", file_path, e)
        return False, existing_blocked


def clear_blocked_users_file() -> None:
    """Elimina el archivo de usuarios bloqueados del sistema local.

    Debe llamarse cuando se vacía la lista de bloqueados (ej: reinicio mensual).
    Después de esta llamada, invocar _sync_quota_squid_rules(True) para que las
    directivas ACL se eliminen de squid.conf al detectar que el archivo no existe.
    """
    try:
        if os.path.exists(_BLOCKED_USERS_PATH):
            os.remove(_BLOCKED_USERS_PATH)
            logger.info(
                "Archivo de usuarios bloqueados eliminado: %s", _BLOCKED_USERS_PATH
            )
        else:
            logger.debug(
                "Archivo %s ya no existe, nada que eliminar", _BLOCKED_USERS_PATH
            )
    except Exception as e:
        logger.warning("No se pudo eliminar %s: %s", _BLOCKED_USERS_PATH, e)


def _commit_modular_config(cm: SquidConfigManager, filename: str, lines: list[str]):
    content = "\n".join(line for line in lines if line.strip() != "")
    return cm.save_modular_config(filename, content)


def _sync_quota_squid_rules(
    enabled: bool,
    *,
    blocked_file_ready: bool | None = None,
    before_validation: Callable[[], bool] | None = None,
    rollback_callback: Callable[[], None] | None = None,
    force_reload: bool = False,
) -> bool:
    """Sync `usuarios_bloqueados` ACL/http_access in Squid config.

    The optional callbacks are used by the scheduler's format transition:
    they keep the list-file update in the same write transaction as its ACL
    representation, and run it before validation/reconfigure.
    """
    cm = SquidConfigManager()
    if not cm.is_valid:
        return _sync_quota_squid_rules_locked(
            enabled,
            cm,
            blocked_file_ready=blocked_file_ready,
            before_validation=before_validation,
            rollback_callback=rollback_callback,
            force_reload=force_reload,
        )
    # Use the normalized path selected by the manager rather than the global
    # default.  Installations may fall back from a stale environment path to
    # /etc/squid/squid.conf, which must share the same transaction lock as
    # Kerberos and the other configuration editors.
    with squid_config_write_lock(cm.config_path):
        if cm.load_config() is False:
            logger.error("No se pudo recargar squid.conf antes de sincronizar cuotas")
            return False
        refresh_layout = getattr(cm, "_check_modular_config", None)
        if callable(refresh_layout):
            refresh_layout()
        return _sync_quota_squid_rules_locked(
            enabled,
            cm,
            blocked_file_ready=blocked_file_ready,
            before_validation=before_validation,
            rollback_callback=rollback_callback,
            force_reload=force_reload,
        )


def _sync_quota_squid_rules_locked(
    enabled: bool,
    cm: SquidConfigManager | None = None,
    *,
    blocked_file_ready: bool | None = None,
    before_validation: Callable[[], bool] | None = None,
    rollback_callback: Callable[[], None] | None = None,
    force_reload: bool = False,
) -> bool:
    """Perform one quota configuration transaction while holding the shared lock."""
    cm = cm or SquidConfigManager()
    logger.debug(
        "sync_quota_squid_rules: enabled={}, config_path={}, config_dir={}, is_modular={}, is_valid={}",
        enabled,
        cm.config_path,
        cm.config_dir,
        cm.is_modular,
        cm.is_valid,
    )
    if not cm.is_valid:
        logger.warning(
            "SquidConfigManager no válido: no se puede sincronizar reglas de cuota. Errores: {}",
            "; ".join(cm.errors) if cm.errors else "sin detalles",
        )
        return False
    if not _managed_kerberos_modular_layout_is_supported(cm):
        return False

    blocked_path = _BLOCKED_USERS_PATH

    def _is_acl_line(line: str) -> bool:
        return _is_quota_acl_entry(line, blocked_path)

    def _is_http_line(line: str) -> bool:
        return (
            _normalised_squid_line(line).casefold()
            == "http_access deny usuarios_bloqueados"
        )

    def _build_acl_line(use_src: bool) -> str:
        if use_src:
            return f"include {blocked_path}"
        # Squid treats a quoted path as an external ACL value file.  Without
        # quotes it is merely one literal username equal to the path, so the
        # quota list would never be consulted.
        return f'acl usuarios_bloqueados proxy_auth -i "{blocked_path}"'

    auth_configured = cm.has_proxy_authentication()
    use_src = not auth_configured
    # The ACL is only safe to enable when the file already uses its selected
    # syntax.  A transition supplies ``blocked_file_ready`` because it stages
    # the converted file inside this same transaction.
    if blocked_file_ready is None:
        blocked_file_ready = _has_compatible_blocked_file_content(
            blocked_path, use_src
        )
    enabled = enabled and blocked_file_ready
    logger.debug(
        "_sync_quota_squid_rules: blocked_path={}, should_enable_acl={}",
        blocked_path,
        enabled,
    )

    acl_line = _build_acl_line(use_src)
    http_line = "http_access deny usuarios_bloqueados"

    def _apply_changes(acl_line: str, http_line: str, use_src: bool) -> bool:
        previous_main_content = cm.config_content or ""
        previous_acls_content = ""
        previous_http_content = ""
        config_changed = False
        runtime = None
        reconfiguration_attempted = False

        try:
            if cm.is_modular:
                previous_acls_content = cm.read_modular_config("100_acls.conf") or ""
                previous_http_content = (
                    cm.read_modular_config("120_http_access.conf") or ""
                )

                acls_content = previous_acls_content
                acl_lines = [
                    line for line in acls_content.split("\n") if line.strip() != ""
                ]
                original_acl_lines = acl_lines.copy()

                # ``include ...usuarios_bloqueados`` and the proxy_auth ACL
                # are two encodings of the same generated policy.  Remove
                # every prior encoding first, then add exactly the selected
                # one.  Keeping an old include during a Kerberos transition
                # makes Squid parse plain identities as directives.
                acl_lines = [line for line in acl_lines if not _is_acl_line(line)]
                if enabled:
                    if use_src:
                        acl_lines.insert(0, acl_line)
                    else:
                        inserted = False
                        for i, line in enumerate(acl_lines):
                            if line.strip().startswith("acl "):
                                acl_lines.insert(i, acl_line)
                                inserted = True
                                break
                        if not inserted:
                            acl_lines.append(acl_line)

                if acl_lines != original_acl_lines:
                    config_changed = True

                if not _commit_modular_config(cm, "100_acls.conf", acl_lines):
                    raise RuntimeError("No se pudieron guardar 100_acls.conf")

                http_content = previous_http_content
                http_lines = [
                    line for line in http_content.split("\n") if line.strip() != ""
                ]
                original_http_lines = http_lines.copy()

                if enabled:
                    http_lines = _ensure_quota_http_rule(
                        http_lines, http_line, use_src=use_src
                    )
                else:
                    http_lines = [
                        line for line in http_lines if not _is_http_line(line)
                    ]

                if http_lines != original_http_lines:
                    config_changed = True

                if not _commit_modular_config(cm, "120_http_access.conf", http_lines):
                    raise RuntimeError("No se pudieron guardar 120_http_access.conf")

            else:
                if not cm.config_content and enabled:
                    logger.error(
                        "config_content está vacío (posible fallo de carga). "
                        "Se cancela la modificación de squid.conf para evitar pérdida de datos."
                    )
                    return False
                lines = cm.config_content.split("\n") if cm.config_content else []
                original_lines = lines.copy()

                # See the modular branch above: migration is replacement,
                # not addition.  This also cleans older direct ``src`` ACLs
                # generated by previous releases.
                lines = [line for line in lines if not _is_acl_line(line)]
                if enabled:
                    if use_src:
                        insert_idx = 0
                        for i, line in enumerate(lines):
                            if line.strip() and not line.strip().startswith("#"):
                                insert_idx = i
                                break
                        lines.insert(insert_idx, acl_line)
                    else:
                        inserted = False
                        for i, line in enumerate(lines):
                            if line.strip().startswith("acl ") or line.strip().startswith(
                                "http_access "
                            ):
                                lines.insert(i, acl_line)
                                inserted = True
                                break
                        if not inserted:
                            lines.append(acl_line)

                    lines = _ensure_quota_http_rule(
                        lines, http_line, use_src=use_src
                    )
                else:
                    lines = [line for line in lines if not _is_http_line(line)]

                if lines != original_lines:
                    config_changed = True

                if not cm.save_config("\n".join(lines)):
                    raise RuntimeError("No se pudo guardar squid.conf")

            # A proxy-auth transition first switches the ACL representation,
            # then writes its value list here, before Squid can validate or
            # reload it.  Conversely, src transitions stage the value file
            # before calling this transaction.  Both paths therefore avoid
            # exposing a plain username as an ``include`` directive.
            if before_validation is not None and not before_validation():
                raise RuntimeError(
                    "No se pudo preparar el archivo de bloqueados para la transición de cuotas"
                )

            if not config_changed and not force_reload:
                return True

            splitter = SquidConfigSplitter(
                input_file=cm.config_path,
                output_dir=cm.config_dir,
            )
            runtime = _find_squid_runtime()
            if runtime is None:
                raise RuntimeError(
                    "No se encontró el runtime Squid correcto para validar y recargar cuotas."
                )
            validation = splitter._validate_squid_config()

            if not validation.get("success"):
                raise RuntimeError(
                    "Validación de Squid falló al sincronizar reglas de cuota: "
                    f"{validation.get('error_message') or validation.get('output') or '<sin detalles>'}"
                )

            reconfiguration_attempted = True
            reload_success, reload_msg = reconfigure_squid(cm.config_path, runtime)
            if not reload_success:
                raise RuntimeError(
                    "Squid no se pudo recargar después de actualizar reglas de cuota: "
                    f"{reload_msg}"
                )
            logger.info("Squid recargado correctamente")

            return True

        except Exception:
            logger.exception("Error aplicando reglas de cuota")
            if cm.is_modular:
                cm.save_modular_config("100_acls.conf", previous_acls_content)
                cm.save_modular_config("120_http_access.conf", previous_http_content)
            if previous_main_content:
                cm.save_config(previous_main_content)
            if rollback_callback is not None:
                try:
                    rollback_callback()
                except Exception as rollback_error:
                    logger.error(
                        "No se pudo restaurar el archivo de cuotas tras un fallo: {}",
                        rollback_error,
                    )
            if reconfiguration_attempted and runtime is not None:
                restored, restore_message = reconfigure_squid(cm.config_path, runtime)
                if not restored:
                    logger.error(
                        "No se pudo recargar Squid tras restaurar cuotas: {}",
                        restore_message,
                    )
            return False

    ok = _apply_changes(acl_line, http_line, use_src)
    if not ok:
        logger.error(
            "No se pudo sincronizar las reglas de cuota. use_src={}, acl_line={}, http_line={}",
            use_src,
            acl_line,
            http_line,
        )
    return ok


def _blocked_users_file_snapshot(file_path: str) -> tuple[bool, str | None, int | None]:
    """Capture the managed list before a config/list transition."""
    if not os.path.exists(file_path):
        return False, None, None
    with open(file_path, encoding="utf-8") as current_file:
        content = current_file.read()
    return True, content, os.stat(file_path).st_mode & 0o777


def _restore_blocked_users_file(
    file_path: str, snapshot: tuple[bool, str | None, int | None]
) -> None:
    """Restore a value-list snapshot after a failed quota transaction."""
    existed, content, mode = snapshot
    if not existed:
        if os.path.exists(file_path):
            os.remove(file_path)
        return
    if content is None:
        raise RuntimeError("Snapshot de cuotas incompleto")
    SquidConfigManager._atomic_write(file_path, content)
    if mode is not None:
        os.chmod(file_path, mode)


def _sync_blocked_file_to_selected_runtime(blocked_path: str) -> bool:
    """Copy a changed value file when the selected Squid runtime is Docker."""
    runtime = _find_squid_runtime()
    if runtime is None or getattr(runtime, "kind", None) != "docker":
        return True
    return _sync_blocked_file_to_docker(blocked_path)


def _sync_blocked_users_and_squid_rules(
    file_path: str, usernames: set[str]
) -> tuple[bool, set[str]]:
    """Atomically transition the quota list and its Squid representation.

    The returned boolean reports a fully committed state, not merely whether
    the file content changed. The source representation (an ``include`` of
    ACL directives) cannot read a plain proxy-auth list. The reverse is
    syntactically safe, so a move to
    ``proxy_auth`` switches the config first and writes the list immediately
    before validation/reload.  A move back to ``src`` writes valid ACL
    directives first and only then enables the include.  All writes share the
    Squid configuration lock and restore both files on failure.
    """
    cm = SquidConfigManager()
    if not cm.is_valid:
        logger.warning(
            "SquidConfigManager no válido: no se puede sincronizar el estado de cuotas"
        )
        return False, set()

    with squid_config_write_lock(cm.config_path):
        if cm.load_config() is False:
            logger.error(
                "No se pudo recargar squid.conf antes de migrar el archivo de cuotas"
            )
            return False, set()
        refresh_layout = getattr(cm, "_check_modular_config", None)
        if callable(refresh_layout):
            refresh_layout()

        use_src = not cm.has_proxy_authentication()
        try:
            snapshot = _blocked_users_file_snapshot(file_path)
            planned_content, existing_blocked = _build_blocked_users_file_content(
                file_path, usernames, use_src
            )
        except OSError as exc:
            logger.warning(
                "No se pudo preparar la transición del archivo de cuotas %s: %s",
                file_path,
                exc,
            )
            return False, set()

        existed, previous_content, _mode = snapshot
        file_will_change = (
            (not existed and planned_content is not None)
            or (existed and previous_content != planned_content)
        )
        blocked_file_ready = bool(_render_block_entries(usernames, use_src))
        file_changed = False
        restored = False

        def restore_file() -> None:
            nonlocal restored
            if restored:
                return
            _restore_blocked_users_file(file_path, snapshot)
            if snapshot[0]:
                _sync_blocked_file_to_selected_runtime(file_path)
            restored = True

        def stage_file() -> bool:
            nonlocal file_changed
            file_changed, _unused_existing = _sync_blocked_users_file(
                file_path, usernames, use_src
            )
            if not file_changed:
                return not file_will_change
            if planned_content is not None and not _sync_blocked_file_to_selected_runtime(
                file_path
            ):
                logger.error(
                    "No se pudo sincronizar el archivo de cuotas al runtime Docker seleccionado"
                )
                return False
            return True

        if use_src:
            # A source include must never see a plain identity line.  Stage
            # its ACL-format list before adding/replacing the include.
            if not stage_file():
                restore_file()
                return False, existing_blocked
            ok = _sync_quota_squid_rules_locked(
                True,
                cm,
                blocked_file_ready=blocked_file_ready,
                rollback_callback=restore_file,
                force_reload=file_changed,
            )
        else:
            # Switching source -> proxy_auth is safe only after the include
            # is removed.  Stage the plain list after that replacement but
            # before validation/reconfigure.
            ok = _sync_quota_squid_rules_locked(
                True,
                cm,
                blocked_file_ready=blocked_file_ready,
                before_validation=stage_file,
                rollback_callback=restore_file,
                force_reload=file_will_change,
            )

        if not ok:
            restore_file()
        return ok, existing_blocked
