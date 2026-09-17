import glob
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from flask_babel import gettext as _
from loguru import logger

from utils.admin import SquidConfigManager, squid_config_write_lock

_KERBEROS_MANAGED_MARKERS = (
    "# BEGIN SquidStats Kerberos authentication",
    "# END SquidStats Kerberos authentication",
    "# BEGIN SquidStats Kerberos access rule",
    "# END SquidStats Kerberos access rule",
    "# SQUIDSTATS KERBEROS AUTH START",
    "# SQUIDSTATS KERBEROS AUTH END",
)
_NEGOTIATE_AUTH_RE = re.compile(r"^\s*auth_param\s+negotiate\b", re.I | re.M)
_INCLUDE_RE = re.compile(r"^\s*include\s+(.+?)\s*$", re.I)


@dataclass(frozen=True)
class Rule:
    filename: str
    patterns: list[re.Pattern]


@dataclass
class _FileSnapshot:
    """Original state of one output file in a split transaction."""

    path: str
    resolved_path: str
    existed: bool
    content: str | None
    written_content: str | None = None


class SquidConfigSplitter:
    def __init__(
        self, input_file: str = None, output_dir: str = None, strict: bool = False
    ):
        self.input_file = input_file or "/etc/squid/squid.conf"
        self.output_dir = output_dir or "/etc/squid/squid.d"
        self.strict = strict
        self.unknown_file = "999_unknown.conf"
        self.has_auth = False
        self.auth_lines = []
        self.auth_patterns = [
            re.compile(r"^auth_param\b"),
            # Authentication ACLs need to be loaded after auth_param and
            # before rules in 120_http_access.conf. Kerberos names its ACL
            # explicitly (for example, `kerberos_auth`), not just `auth`.
            re.compile(r"^acl\s+\S+(?:\s+-\S+)*\s+proxy_auth\b"),
        ]
        self.rules = self._compile_rules()

    def _compile_rules(self) -> list[Rule]:
        """
        Compile the directive classification rules.
        The order matters and is intentional.
        """
        return [
            Rule(
                "00_ports.conf",
                [
                    re.compile(r"^http_port\b"),
                ],
            ),
            Rule(
                "10_misc.conf",
                [
                    re.compile(r"^max_filedesc\b"),
                    re.compile(r"^pconn_lifetime\b"),
                    re.compile(r"^visible_hostname\b"),
                    re.compile(r"^pid_filename\b"),
                    re.compile(r"^client_db\b"),
                    re.compile(r"^cache_mgr\b"),
                ],
            ),
            Rule(
                "20_security.conf",
                [
                    re.compile(r"^via\b"),
                    re.compile(r"^forwarded_for\b"),
                    re.compile(r"^request_header_access\b"),
                    re.compile(r"^quick_abort"),
                    re.compile(r"^httpd_suppress_version_string\b"),
                    re.compile(r"^reload_into_ims\b"),
                    re.compile(r"^read_ahead_gap\b"),
                    re.compile(r"^negative_ttl\b"),
                    re.compile(r"^positive_dns_ttl\b"),
                    re.compile(r"^negative_dns_ttl\b"),
                    re.compile(r"^range_offset_limit\b"),
                    re.compile(r"^pinger_enable\b"),
                    re.compile(r"^server_persistent_connections\b"),
                    re.compile(r"^client_persistent_connections\b"),
                    re.compile(r"^check_hostnames\b"),
                    re.compile(r"^half_closed_clients\b"),
                ],
            ),
            Rule(
                "60_logs.conf",
                [
                    re.compile(r"^access_log\b"),
                    re.compile(r"^cache_log\b"),
                    re.compile(r"^cache_store_log\b"),
                    re.compile(r"^cache_access_log\b"),
                    re.compile(r"^icap_log\b"),
                    re.compile(r"^logformat\b"),
                    re.compile(r"^strip_query_terms\b"),
                    re.compile(r"^coredump_dir\b"),
                ],
            ),
            Rule(
                "30_cache.conf",
                [
                    re.compile(
                        r"^cache_(?!log\b|mgr\b|store_log\b|access_log\b|peer(?:\b|_))"
                    ),
                    re.compile(r"^maximum_object_"),
                    re.compile(r"^minimum_object_"),
                    re.compile(r"^memory_"),
                    re.compile(r"^ipcache_"),
                    re.compile(r"^fqdncache_"),
                ],
            ),
            Rule(
                "40_refresh_patterns.conf",
                [
                    re.compile(r"^refresh_pattern\b"),
                ],
            ),
            Rule(
                "55_ssl_bump.conf",
                [
                    re.compile(r"^ssl_"),
                    re.compile(r"^sslcrtd_"),
                    re.compile(r"^acl\s+\S+\s+at_step\b"),
                    re.compile(r"sslproxy_"),
                ],
            ),
            Rule(
                "70_icap.conf",
                [
                    re.compile(r"^icap_(?!log\b)"),
                    re.compile(r"^adaptation_"),
                ],
            ),
            Rule(
                "80_dns.conf",
                [
                    re.compile(r"^dns_"),
                    re.compile(r"^hosts_file\b"),
                    re.compile(r"^connect_timeout\b"),
                    re.compile(r"^read_timeout\b"),
                ],
            ),
            Rule(
                "50_auth.conf",
                [
                    *self.auth_patterns,
                    re.compile(r"^authenticate_"),
                ],
            ),
            Rule(
                "100_acls.conf",
                [
                    re.compile(
                        r"^acl(?!\s+auth\b)(?!.*\bat_step\b)(?!.*\bproxy_auth\b)"
                    ),
                    re.compile(r"^external_acl_type\b"),
                ],
            ),
            Rule(
                "110_delay_pools.conf",
                [
                    re.compile(r"^delay_"),
                ],
            ),
            Rule(
                "115_cache_control.conf",
                [
                    re.compile(r"^no_cache\b"),
                    re.compile(r"^icp_access\b"),
                    re.compile(r"^cache_peer"),
                    re.compile(r"^never_direct\b"),
                ],
            ),
            Rule(
                "120_http_access.conf",
                [
                    re.compile(r"^http_access\b"),
                    re.compile(r"^deny_info\b"),
                ],
            ),
            Rule(
                "90_includes.conf",
                [
                    re.compile(r"^include\b"),
                ],
            ),
        ]

    def _get_load_order(self) -> list[str]:
        """
        Return the correct load order for config files.
        ACLs and auth must be loaded before being referenced.
        """
        return [
            "00_ports.conf",
            "10_misc.conf",
            "20_security.conf",
            "30_cache.conf",
            "40_refresh_patterns.conf",
            "50_auth.conf",  # Auth defines 'auth' ACL
            "60_logs.conf",
            "80_dns.conf",
            "90_includes.conf",  # Includes may define ACLs (e.g. usuarios_bloqueados)
            "100_acls.conf",  # All other ACLs defined here
            "70_icap.conf",  # Uses 'infoaccess' ACL
            "110_delay_pools.conf",  # Uses 'auth', 'work_time_*', 'research_files' ACLs
            "115_cache_control.conf",
            "120_http_access.conf",  # Uses all ACLs
            "55_ssl_bump.conf",  # Can go anywhere but typically after ACLs
            self.unknown_file,  # Catch-all for unclassified
        ]

    def _classify_line(self, line: str) -> str:
        matches = [
            rule.filename
            for rule in self.rules
            for pattern in rule.patterns
            if pattern.search(line)
        ]

        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous rule match for line:\n{line}\nMatches: {matches}"
            )

        if matches:
            return matches[0]

        return self.unknown_file

    @staticmethod
    def _contains_kerberos_configuration(content: str) -> bool:
        """Whether a source contains managed or manually configured Negotiate.

        Splitting moves generic include directives into a normalized load order.
        That cannot preserve the position of a Kerberos challenge relative to
        arbitrary nested policy fragments, so the safe path is to refuse a
        split until the administrator has removed or migrated it deliberately.
        """
        # Squid permits directives to continue on the next physical line.
        # Test the logical directive as well; otherwise a split
        # ``auth_param`` / ``negotiate`` directive evades this guard and can
        # reorder a live Kerberos policy.
        logical_content = re.sub(r"\\[ \t]*\r?\n[ \t]*", " ", content)
        return _NEGOTIATE_AUTH_RE.search(logical_content) is not None or any(
            marker in content for marker in _KERBEROS_MANAGED_MARKERS
        )

    def _has_existing_kerberos_configuration(self, input_content: str) -> bool:
        """Inspect direct and recursively active sources before splitting."""
        seen = {os.path.realpath(self.input_file)}

        def logical_lines(content: str) -> list[str]:
            result: list[str] = []
            pending = ""
            for raw_line in content.splitlines():
                line = raw_line.split("#", 1)[0].strip()
                if not line:
                    continue
                if pending:
                    line = f"{pending} {line.lstrip()}"
                if line.rstrip().endswith("\\"):
                    pending = line.rstrip()[:-1].rstrip()
                    continue
                result.append(line)
                pending = ""
            if pending:
                result.append(pending)
            return result

        def visit(content: str, directory: str, depth: int = 0) -> bool:
            if self._contains_kerberos_configuration(content):
                return True
            if depth >= 8:
                # A deeper active config could contain a challenge whose
                # order this splitter cannot preserve.
                return any(
                    _INCLUDE_RE.fullmatch(line) for line in logical_lines(content)
                )
            for line in logical_lines(content):
                match = _INCLUDE_RE.fullmatch(line)
                if not match:
                    continue
                include_path = os.path.expanduser(match.group(1).strip().strip('"'))
                pattern = os.path.abspath(
                    include_path
                    if os.path.isabs(include_path)
                    else os.path.join(directory, include_path)
                )
                try:
                    candidates = sorted(glob.glob(pattern))
                except OSError:
                    return True
                for candidate in candidates:
                    real_candidate = os.path.realpath(candidate)
                    if real_candidate in seen or not os.path.isfile(real_candidate):
                        continue
                    seen.add(real_candidate)
                    try:
                        with open(real_candidate, encoding="utf-8") as included:
                            included_content = included.read()
                    except (OSError, UnicodeDecodeError):
                        # Do not rewrite an ordered configuration whose
                        # active source cannot be inspected.
                        return True
                    if visit(
                        included_content, os.path.dirname(real_candidate), depth + 1
                    ):
                        return True
            return False

        if visit(input_content, os.path.dirname(os.path.abspath(self.input_file))):
            return True
        if not os.path.isdir(self.output_dir):
            return False
        for filename in ("50_auth.conf", "120_http_access.conf"):
            path = os.path.join(self.output_dir, filename)
            try:
                with open(path, encoding="utf-8") as module:
                    if self._contains_kerberos_configuration(module.read()):
                        return True
            except FileNotFoundError:
                continue
            except (OSError, UnicodeDecodeError):
                # An unreadable conventional module must not be overwritten
                # by the splitter while its policy state is unknown.
                return True
        return False

    @staticmethod
    def _atomic_write(path: str, content: str, encoding: str = "utf-8") -> None:
        """Use the shared metadata-preserving Squid configuration writer.

        Splitting must retain a package's owner, mode, extended ACLs, and
        symbolic main-config link just like all other configuration editors.
        """
        SquidConfigManager._atomic_write(path, content, encoding)

    @staticmethod
    def _snapshot_file(path: str) -> _FileSnapshot:
        """Read an output target before replacing it, without following it later.

        The resolved path is retained so rollback can refuse to overwrite a
        target that another process has moved or changed while this transaction
        was in progress.
        """
        resolved_path = os.path.realpath(os.path.abspath(path))
        try:
            with open(resolved_path, encoding="utf-8") as existing:
                return _FileSnapshot(
                    path=path,
                    resolved_path=resolved_path,
                    existed=True,
                    content=existing.read(),
                )
        except FileNotFoundError:
            return _FileSnapshot(
                path=path,
                resolved_path=resolved_path,
                existed=False,
                content=None,
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                f"No se pudo respaldar el módulo de salida {os.path.basename(path)}."
            ) from exc

    @staticmethod
    def _assert_snapshot_is_current(snapshot: _FileSnapshot) -> None:
        """Refuse to replace a target changed after its transaction snapshot.

        The common flock protects cooperative SquidStats writers.  This
        additional compare immediately before replacement protects against a
        manually edited or otherwise non-cooperating file between the initial
        transaction snapshot and the final write.  A regular file system
        cannot provide a perfect CAS against a process that deliberately
        ignores locks, but this prevents the normal stale-write path and
        leaves its newer content untouched on failure.
        """
        current_path = os.path.realpath(os.path.abspath(snapshot.path))
        if current_path != snapshot.resolved_path:
            raise RuntimeError(
                f"La ruta de {os.path.basename(snapshot.path)} cambió durante la operación."
            )
        try:
            with open(snapshot.resolved_path, encoding="utf-8") as current:
                current_content: str | None = current.read()
        except FileNotFoundError:
            current_content = None
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                f"No se pudo verificar {os.path.basename(snapshot.path)} antes de escribir."
            ) from exc
        if current_content != snapshot.content:
            raise RuntimeError(
                f"{os.path.basename(snapshot.path)} cambió durante la operación; no se sobrescribió."
            )

    def _restore_output_snapshot(self, snapshot: _FileSnapshot) -> str | None:
        """Restore one changed output file, avoiding an out-of-band overwrite."""
        if snapshot.written_content is None:
            return None
        if os.path.realpath(os.path.abspath(snapshot.path)) != snapshot.resolved_path:
            return f"{os.path.basename(snapshot.path)} (la ruta cambió durante la operación)"
        try:
            try:
                with open(snapshot.resolved_path, encoding="utf-8") as current:
                    current_content: str | None = current.read()
            except FileNotFoundError:
                current_content = None
            if current_content != snapshot.written_content:
                return (
                    f"{os.path.basename(snapshot.path)} (cambió durante la operación)"
                )
            if snapshot.existed:
                self._atomic_write(snapshot.path, snapshot.content or "")
            elif current_content is not None:
                os.unlink(snapshot.resolved_path)
        except OSError:
            logger.exception(
                "Could not restore generated split module %s", snapshot.path
            )
            return os.path.basename(snapshot.path)
        return None

    def _rollback_split_transaction(
        self,
        output_snapshots: list[_FileSnapshot],
        *,
        main_content: str,
        main_resolved_path: str,
        generated_main_content: str | None,
        created_output_dir: bool,
    ) -> list[str]:
        """Restore all changed files and return any incomplete rollback targets."""
        failures: list[str] = []
        if generated_main_content is not None:
            try:
                if (
                    os.path.realpath(os.path.abspath(self.input_file))
                    != main_resolved_path
                ):
                    failures.append("squid.conf (la ruta cambió durante la operación)")
                else:
                    with open(main_resolved_path, encoding="utf-8") as current:
                        current_content = current.read()
                    if current_content != generated_main_content:
                        failures.append("squid.conf (cambió durante la operación)")
                    else:
                        self._atomic_write(self.input_file, main_content)
            except (OSError, UnicodeDecodeError):
                logger.exception("Rollback of squid.conf failed")
                failures.append("squid.conf")

        for snapshot in reversed(output_snapshots):
            failure = self._restore_output_snapshot(snapshot)
            if failure:
                failures.append(failure)

        if created_output_dir:
            try:
                os.rmdir(self.output_dir)
            except FileNotFoundError:
                pass
            except OSError:
                # It is safe to leave an empty/new directory behind.  Do not
                # remove a directory that acquired an external file while the
                # transaction was running.
                logger.warning(
                    "Could not remove newly-created output directory %s",
                    self.output_dir,
                )
        return failures

    def split_config(self) -> dict[str, int]:
        """Split under the same inter-process lock as all config writers."""
        with squid_config_write_lock(self.input_file):
            return self._split_config_locked()

    def _split_config_locked(self) -> dict[str, int]:
        # Capture the input before creating output files. This snapshot is
        # also compared just before the generated main config replaces it.
        main_snapshot = self._snapshot_file(self.input_file)
        if not main_snapshot.existed:
            raise FileNotFoundError(f"File not found: {self.input_file}")

        # Read before creating output files. A split normalizes include order,
        # which can move a previously safe Kerberos challenge behind an allow
        # rule or separate its managed markers. Do not alter such a setup.
        _original_content = main_snapshot.content or ""
        if self._has_existing_kerberos_configuration(_original_content):
            raise RuntimeError(
                "No se puede dividir una configuración que contiene Kerberos/Negotiate "
                "o un include activo que no se pudo verificar. Migra o deshabilita "
                "Kerberos desde su pantalla dedicada y revisa los includes antes de "
                "dividir squid.conf."
            )

        # Create the output directory if it doesn't exist. Track ownership so
        # a failed transaction can remove only the empty directory it created.
        created_output_dir = not os.path.exists(self.output_dir)
        try:
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir, exist_ok=True)
                logger.info(f"Output directory created: {self.output_dir}")
            else:
                logger.info(f"Output directory already exists: {self.output_dir}")
        except PermissionError as e:
            logger.error(f"Permission denied to create directory: {self.output_dir}")
            raise PermissionError(
                f"No permissions to create directory: {self.output_dir}"
            ) from e
        except OSError as e:
            logger.error(f"Failed to create output directory: {e}")
            raise RuntimeError(
                f"Failed to create output directory: {self.output_dir}"
            ) from e

        buffers: dict[str, list[str]] = {}
        pending_comments: list[str] = []
        results: dict[str, int] = {}
        output_snapshots: list[_FileSnapshot] = []
        main_resolved_path = main_snapshot.resolved_path
        generated_main_content: str | None = None
        validation_error: str | None = None
        # A splitter instance may be reused by a caller; auth collection is a
        # property of this input transaction, not of the instance lifetime.
        self.has_auth = False
        self.auth_lines = []

        try:
            with open(self.input_file, encoding="utf-8") as f:
                in_continuation = False
                continuation_target = None
                for lineno, raw_line in enumerate(f, start=1):
                    line = raw_line.rstrip("\n")
                    stripped = line.strip()

                    # Handle backslash continuation lines
                    if in_continuation:
                        buffers.setdefault(continuation_target, [])
                        buffers[continuation_target].extend(pending_comments)
                        pending_comments.clear()
                        buffers[continuation_target].append(raw_line)
                        if not line.rstrip().endswith("\\"):
                            in_continuation = False
                            continuation_target = None
                        continue

                    # Comments and empty lines
                    if not stripped or stripped.startswith("#"):
                        pending_comments.append(raw_line)
                        continue

                    # Check for auth lines and collect them
                    if any(p.search(stripped) for p in self.auth_patterns):
                        self.has_auth = True
                        self.auth_lines.append(raw_line)

                    try:
                        target = self._classify_line(stripped)
                    except ValueError:
                        logger.exception(
                            "Error classifying line %s: %s", lineno, stripped
                        )
                        raise RuntimeError("Error classifying configuration line")

                    if target == self.unknown_file and self.strict:
                        logger.error(
                            "Unknown directive at line %s: %s", lineno, stripped
                        )
                        raise RuntimeError(
                            "Unknown directive found in strict mode. Review configuration."
                        )

                    buffers.setdefault(target, [])
                    buffers[target].extend(pending_comments)
                    pending_comments.clear()
                    buffers[target].append(raw_line)

                    # Start tracking continuation if line ends with backslash
                    if line.rstrip().endswith("\\"):
                        in_continuation = True
                        continuation_target = target

            # Orphaned final comments
            if pending_comments:
                buffers.setdefault(self.unknown_file, []).extend(pending_comments)

            # Ensure auth file is created if auth config exists
            self._ensure_auth_file(buffers)

            # Snapshot every output before any write.  This makes an invalid
            # generated main file fully reversible even when it already
            # included this directory through a wildcard before the split.
            seen_output_targets: set[str] = set()
            snapshots_by_path: dict[str, _FileSnapshot] = {}
            for filename in sorted(buffers):
                path = os.path.join(self.output_dir, filename)
                snapshot = self._snapshot_file(path)
                if snapshot.resolved_path in seen_output_targets:
                    raise RuntimeError(
                        "Dos módulos de salida resuelven al mismo archivo; no es seguro dividir la configuración."
                    )
                seen_output_targets.add(snapshot.resolved_path)
                output_snapshots.append(snapshot)
                snapshots_by_path[path] = snapshot

            # Final writing
            for filename, content in sorted(buffers.items()):
                path = os.path.join(self.output_dir, filename)
                rendered_content = "".join(content)
                snapshot = snapshots_by_path[path]
                try:
                    self._assert_snapshot_is_current(snapshot)
                    if not (snapshot.existed and snapshot.content == rendered_content):
                        self._atomic_write(path, rendered_content)
                        snapshot.written_content = rendered_content
                    results[filename] = len(content)
                    logger.info(f"[OK] {path} ({len(content)} lines)")
                except PermissionError:
                    logger.exception("Permission denied writing to file: %s", path)
                    raise RuntimeError("Permission denied writing generated file")
                except RuntimeError:
                    # Keep a stale-snapshot error actionable. The outer
                    # transaction handler will roll back only files it wrote,
                    # preserving the external change that caused this abort.
                    raise
                except Exception:
                    logger.exception("Failed to write file: %s", path)
                    raise RuntimeError("Failed to write generated file")

            # Generate the new main squid.conf with includes
            self._assert_snapshot_is_current(main_snapshot)
            generated_main_content = self._generate_main_config(buffers)
            logger.info(f"Generated new main config: {self.input_file}")

            # Validate Squid configuration
            validation_result = self._validate_squid_config()
            if not validation_result["success"]:
                validation_error = validation_result.get(
                    "error_message", "Unknown error"
                )
                logger.error(
                    "Squid configuration validation failed. Rolling back changes. Error: %s",
                    validation_error,
                )
                raise RuntimeError("Squid configuration validation failed.")

            logger.info("Squid configuration validated successfully.")
            return results

        except Exception as exc:
            rollback_failures = self._rollback_split_transaction(
                output_snapshots,
                main_content=_original_content,
                main_resolved_path=main_resolved_path,
                generated_main_content=generated_main_content,
                created_output_dir=created_output_dir,
            )
            if rollback_failures:
                details = ", ".join(dict.fromkeys(rollback_failures))
                raise RuntimeError(
                    "No se pudo dividir squid.conf y la restauración quedó incompleta "
                    f"({details}). Revisa los archivos antes de recargar Squid."
                ) from exc
            if validation_error is not None:
                raise RuntimeError(
                    "Squid configuration validation failed. Changes have been reverted.\n\n"
                    f"Squid output:\n{validation_error}"
                ) from exc
            logger.exception("Error splitting configuration file")
            raise

    def _validate_squid_config(self) -> dict:
        """Validate the exact local or Docker runtime selected for Squid.

        Reuse the Kerberos runtime selection so an installed host binary never
        masks a Docker deployment, and so Docker receives its configured
        ``-f`` path rather than whatever its image happens to default to.
        """
        # Imported lazily to keep this generic splitter independent at module
        # load time while sharing one authoritative runtime policy.
        from services.squid.kerberos_config_service import (  # noqa: PLC0415
            _docker_config_mount_status,
            _docker_mounts,
            _find_squid_runtime,
            _runtime_selection_error,
            validate_squid_configuration,
        )

        runtime = _find_squid_runtime()
        if runtime is None:
            message = _runtime_selection_error() or (
                "No se encontró el runtime Squid configurado para validar la división."
            )
            logger.error(message)
            return {"success": False, "error_message": message}

        if runtime.kind == "docker":
            if not runtime.container_config_path:
                message = (
                    "SQUID_CONTAINER_CONFIG_PATH no es una ruta absoluta segura "
                    "dentro del contenedor Docker."
                )
                logger.error(message)
                return {"success": False, "error_message": message}
            mount_status = _docker_config_mount_status(
                runtime,
                Path(self.input_file),
                mounts=_docker_mounts(runtime),
                mounts_checked=True,
            )
            if mount_status.get("mapped") is not True:
                message = (
                    "No se pudo comprobar que el squid.conf a dividir sea el archivo "
                    "cargado por el contenedor Docker configurado."
                )
                logger.error(message)
                return {"success": False, "error_message": message}

        result = validate_squid_configuration(self.input_file, runtime)
        if result.get("available") and result.get("valid"):
            logger.info("Squid configuration validated successfully.")
            return {"success": True, "output": result.get("message", "")}

        message = result.get("message") or "Squid rechazó la configuración."
        logger.error("Squid configuration validation failed: %s", message)
        return {"success": False, "error_message": message}

    def _generate_main_config(self, buffers: dict[str, list[str]]) -> str:
        header = [
            "# ============================================================\n",
            "# Archivo generado automáticamente por SquidStats\n",
            f"# Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "# NO EDITAR A MANO - Los cambios se perderán\n",
            "# ============================================================\n",
            "\n",
        ]

        includes = []
        load_order = self._get_load_order()
        for filename in load_order:
            if filename in buffers:
                include_path = os.path.join(self.output_dir, filename)
                includes.append(f"include {include_path}\n")

        generated_content = "".join(header) + "".join(includes)
        try:
            self._atomic_write(self.input_file, generated_content)
            logger.info(
                f"Main configuration file regenerated with {len(includes)} includes in correct dependency order"
            )
            return generated_content
        except Exception:
            logger.exception("Failed to generate main config")
            raise RuntimeError("Failed to generate main config")

    def _ensure_auth_file(self, buffers: dict[str, list[str]]) -> None:
        """
        Ensure that 50_auth.conf is created if there are auth-related lines in the original config.
        """
        auth_filename = "50_auth.conf"
        if auth_filename in buffers:
            return  # Already exists

        if self.has_auth:
            # Create auth file content from collected lines
            auth_content = ["# Auth Configuration\n"] + self.auth_lines
            buffers[auth_filename] = auth_content
            logger.info(
                f"Created {auth_filename} with authentication configuration from original file"
            )

    def get_split_info(self) -> dict[str, str]:
        return {
            "00_ports.conf": "HTTP ports configuration",
            "10_misc.conf": "Miscellaneous configurations",
            "20_security.conf": "Security configuration",
            "30_cache.conf": "Cache configuration",
            "40_refresh_patterns.conf": "Refresh patterns",
            "50_auth.conf": "Authentication configuration",
            "55_ssl_bump.conf": "SSL Bump configuration",
            "60_logs.conf": "Logs configuration",
            "70_icap.conf": "ICAP configuration",
            "80_dns.conf": "DNS configuration",
            "100_acls.conf": "Access control lists (ACLs)",
            "110_delay_pools.conf": "Delay pools configuration",
            "115_cache_control.conf": "Cache control and peering",
            "120_http_access.conf": "HTTP access rules",
            "90_includes.conf": "Additional include directives",
            "999_unknown.conf": "Unclassified directives",
        }

    def check_output_dir_exists(self) -> bool:
        return os.path.exists(self.output_dir) and os.path.isdir(self.output_dir)

    def count_files_in_output_dir(self) -> int:
        if not self.check_output_dir_exists():
            return 0
        return len([f for f in os.listdir(self.output_dir) if f.endswith(".conf")])

    @staticmethod
    def get_split_files_info(output_dir: str = None) -> dict:
        if output_dir is None:
            output_dir = "/etc/squid/squid.d"

        if not os.path.exists(output_dir):
            return {
                "status": "error",
                "message": f"El directorio {output_dir} no existe",
                "code": 404,
            }

        try:
            files_info = []
            for filename in sorted(os.listdir(output_dir)):
                if filename.endswith(".conf"):
                    file_path = os.path.join(output_dir, filename)
                    try:
                        # Get file statistics
                        stat_info = os.stat(file_path)
                        file_size = stat_info.st_size
                        modified_time = datetime.fromtimestamp(
                            stat_info.st_mtime
                        ).strftime("%Y-%m-%d %H:%M:%S")

                        # Count lines
                        with open(file_path, encoding="utf-8") as f:
                            line_count = sum(1 for _ in f)

                        files_info.append(
                            {
                                "filename": filename,
                                "size": file_size,
                                "size_human": f"{file_size / 1024:.2f} KB"
                                if file_size > 1024
                                else f"{file_size} B",
                                "lines": line_count,
                                "modified": modified_time,
                            }
                        )
                    except Exception as e:
                        logger.error(f"Error al leer archivo {filename}: {e}")
                        continue

            return {
                "status": "success",
                "data": {
                    "output_dir": output_dir,
                    "files": files_info,
                    "total_files": len(files_info),
                },
            }

        except PermissionError as e:
            logger.error(f"Error de permisos al leer archivos: {e}")
            return {
                "status": "error",
                "message": _(
                    "No se tienen permisos suficientes para leer los archivos"
                ),
                "code": 403,
            }

        except Exception:
            logger.exception("Error al obtener archivos de configuración")
            return {
                "status": "error",
                "message": _("Error interno al obtener los archivos"),
                "code": 500,
            }
