import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime

from loguru import logger


@dataclass(frozen=True)
class Rule:
    filename: str
    patterns: list[re.Pattern]


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
        self.auth_patterns = [re.compile(r"^auth_param\b"), re.compile(r"^acl auth\b")]
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
                    re.compile(r"^cache_(?!log\b|mgr\b|store_log\b|access_log\b)"),
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
                    re.compile(r"^auth_param\b"),
                    re.compile(r"^authenticate_"),
                    re.compile(r"^acl auth\b"),
                ],
            ),
            Rule(
                "100_acls.conf",
                [
                    re.compile(r"^acl(?! auth\b)(?!.*\bat_step\b)"),
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
            "100_acls.conf",  # All other ACLs defined here
            "70_icap.conf",  # Uses 'infoaccess' ACL
            "110_delay_pools.conf",  # Uses 'auth', 'work_time_*', 'research_files' ACLs
            "115_cache_control.conf",
            "120_http_access.conf",  # Uses all ACLs
            "55_ssl_bump.conf",  # Can go anywhere but typically after ACLs
            "90_includes.conf",  # Additional includes
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

    def split_config(self) -> dict[str, int]:
        # Verify that the input file exists
        if not os.path.exists(self.input_file):
            raise FileNotFoundError(f"File not found: {self.input_file}")

        # Backup of squid.conf is disabled by user request.
        # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # backup_file = f"{self.input_file}.bak{timestamp}"
        # try:
        #     shutil.copy2(self.input_file, backup_file)
        #     logger.info(f"Backup created: {backup_file}")
        # except PermissionError:
        #     logger.exception("Permission denied to create backup file: %s", backup_file)
        #     raise RuntimeError("Permission denied to create backup file")
        # except Exception:
        #     logger.exception("Failed to create backup file: %s", backup_file)
        #     raise RuntimeError("Failed to create backup file")
        logger.info("Backup creation disabled: no .bak file generated")

        # Create the output directory if it doesn't exist
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
        backup_file = None
        results["_backup_file"] = backup_file

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

            # Final writing
            for filename, content in sorted(buffers.items()):
                path = os.path.join(self.output_dir, filename)
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.writelines(content)
                    results[filename] = len(content)
                    logger.info(f"[OK] {path} ({len(content)} lines)")
                except PermissionError:
                    logger.exception("Permission denied writing to file: %s", path)
                    raise RuntimeError("Permission denied writing generated file")
                except Exception:
                    logger.exception("Failed to write file: %s", path)
                    raise RuntimeError("Failed to write generated file")

            # Generate the new main squid.conf with includes
            self._generate_main_config(buffers)
            logger.info(f"Generated new main config: {self.input_file}")

            # Validate Squid configuration
            validation_result = self._validate_squid_config()
            if not validation_result["success"]:
                error_details = validation_result.get("error_message", "Unknown error")
                logger.error(
                    "Squid configuration validation failed. Rolling back changes. Error: %s",
                    error_details,
                )
                if backup_file:
                    self._rollback_changes(backup_file, list(buffers.keys()))
                else:
                    logger.warning(
                        "No backup file available: no rollback will be performed"
                    )
                raise RuntimeError(
                    f"Squid configuration validation failed. Changes have been reverted.\n\nSquid output:\n{error_details}"
                )

            logger.info("Squid configuration validated successfully.")
            return results

        except Exception:
            logger.exception("Error splitting configuration file")
            raise

    def _validate_squid_config(self) -> dict:
        """
        Validate Squid configuration using 'squid -k parse'.
        First tries the system squid command; if not found, falls back to Docker.
        Returns dict with 'success' (bool), 'output' (str), and 'error_message' (str) if failed.
        """

        def _run_command(cmd: list[str]) -> dict:
            """Run a validation command and return a result dict."""
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                stdout_output = result.stdout.strip() if result.stdout else ""
                stderr_output = result.stderr.strip() if result.stderr else ""
                full_output = ""
                if stdout_output:
                    full_output += f"STDOUT:\n{stdout_output}\n"
                if stderr_output:
                    full_output += f"STDERR:\n{stderr_output}\n"
                if not full_output:
                    full_output = "No output from squid command"
                return {
                    "ran": True,
                    "returncode": result.returncode,
                    "output": full_output,
                }
            except subprocess.TimeoutExpired as e:
                stdout_partial = e.stdout.strip() if e.stdout else ""
                stderr_partial = e.stderr.strip() if e.stderr else ""
                partial_output = ""
                if stdout_partial:
                    partial_output += f"STDOUT (partial):\n{stdout_partial}\n"
                if stderr_partial:
                    partial_output += f"STDERR (partial):\n{stderr_partial}\n"
                return {
                    "ran": True,
                    "returncode": -1,
                    "output": partial_output,
                    "timeout": True,
                }
            except FileNotFoundError:
                return {"ran": False, "output": ""}
            except Exception as e:
                return {"ran": True, "returncode": -1, "output": str(e)}

        # --- Try system squid first ---
        logger.info("Validating Squid configuration with 'squid -k parse'...")
        res = _run_command(["squid", "-k", "parse"])

        if not res["ran"]:
            # squid binary not found on the system, try Docker
            logger.warning(
                "'squid' not found on system. Trying Docker fallback "
                "('docker exec squid_proxy squid -k parse')..."
            )
            res = _run_command(
                ["docker", "exec", "squid_proxy", "squid", "-k", "parse"]
            )

            if not res["ran"]:
                error_msg = (
                    "Neither 'squid' nor 'docker' command found. "
                    "Cannot validate configuration. "
                    "Please ensure Squid is installed (system or Docker)."
                )
                logger.error(error_msg)
                return {"success": False, "error_message": error_msg}

        # --- Evaluate result ---
        if res.get("timeout"):
            error_msg = f"Squid configuration validation timed out after 30 seconds.\n{res['output']}"
            logger.error(error_msg)
            return {
                "success": False,
                "error_message": error_msg,
                "output": res["output"],
            }

        if res["returncode"] == 0:
            logger.info(
                f"Squid configuration is valid.\nCommand output:\n{res['output']}"
            )
            return {
                "success": True,
                "output": res["output"],
                "return_code": res["returncode"],
            }

        error_msg = (
            f"Validation failed with return code {res['returncode']}\n{res['output']}"
        )
        logger.error(f"Squid configuration validation failed:\n{error_msg}")
        return {
            "success": False,
            "error_message": error_msg,
            "output": res["output"],
            "return_code": res["returncode"],
        }

    def _rollback_changes(self, backup_file: str, generated_files: list[str]) -> None:
        """
        Rollback changes by restoring the backup and deleting generated files.
        """
        try:
            # Restore backup
            if os.path.exists(backup_file):
                shutil.copy2(backup_file, self.input_file)
                logger.info(f"Restored backup from {backup_file} to {self.input_file}")
            else:
                logger.error(f"Backup file not found: {backup_file}")

            # Delete generated files
            for filename in generated_files:
                file_path = os.path.join(self.output_dir, filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Deleted generated file: {file_path}")

            logger.info("Rollback completed successfully.")

        except Exception:
            logger.exception("Error during rollback")
            raise RuntimeError("Rollback failed")

    def _generate_main_config(self, buffers: dict[str, list[str]]) -> None:
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

        try:
            with open(self.input_file, "w", encoding="utf-8") as f:
                f.writelines(header)
                f.writelines(includes)
            logger.info(
                f"Main configuration file regenerated with {len(includes)} includes in correct dependency order"
            )
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
                "message": "No se tienen permisos suficientes para leer los archivos",
                "code": 403,
            }

        except Exception:
            logger.exception("Error al obtener archivos de configuración")
            return {
                "status": "error",
                "message": "Error interno al obtener los archivos",
                "code": 500,
            }
