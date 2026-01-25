import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime

from config import logger


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
                "50_ssl_bump.conf",
                [
                    re.compile(r"^ssl_"),
                    re.compile(r"^sslcrtd_"),
                    re.compile(r"SslBump"),
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
                "90_auth.conf",
                [
                    re.compile(r"^auth_param\b"),
                    re.compile(r"^authenticate_"),
                ],
            ),
            Rule(
                "100_acls.conf",
                [
                    re.compile(r"^acl\b"),
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

        # Create backup of squid.conf before splitting
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{self.input_file}.bak{timestamp}"
        try:
            shutil.copy2(self.input_file, backup_file)
            logger.info(f"Backup created: {backup_file}")
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            raise RuntimeError(f"Failed to create backup: {e}")

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
        results["_backup_file"] = backup_file

        try:
            with open(self.input_file, encoding="utf-8") as f:
                for lineno, raw_line in enumerate(f, start=1):
                    line = raw_line.rstrip("\n")
                    stripped = line.strip()

                    # Comments and empty lines
                    if not stripped or stripped.startswith("#"):
                        pending_comments.append(raw_line)
                        continue

                    try:
                        target = self._classify_line(stripped)
                    except ValueError as e:
                        logger.error(f"Error in line {lineno}: {e}")
                        raise RuntimeError(f"Line {lineno}: {e}")

                    if target == self.unknown_file and self.strict:
                        raise RuntimeError(
                            f"Unknown directive at line {lineno}: {stripped}"
                        )

                    buffers.setdefault(target, [])
                    buffers[target].extend(pending_comments)
                    pending_comments.clear()
                    buffers[target].append(raw_line)

            # Orphaned final comments
            if pending_comments:
                buffers.setdefault(self.unknown_file, []).extend(pending_comments)

            # Final writing
            for filename, content in sorted(buffers.items()):
                path = os.path.join(self.output_dir, filename)
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(content)

                results[filename] = len(content)
                logger.info(f"[OK] {path} ({len(content)} lines)")

            # Generate the new main squid.conf with includes
            self._generate_main_config(list(buffers.keys()))
            logger.info(f"Generated new main config: {self.input_file}")

            return results

        except Exception as e:
            logger.exception(f"Error splitting configuration file: {e}")
            raise

    def _generate_main_config(self, generated_files: list[str]) -> None:
        header = [
            "# ============================================================\n",
            "# Archivo generado automáticamente por SquidStats\n",
            f"# Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "# NO EDITAR A MANO - Los cambios se perderán\n",
            "# ============================================================\n",
            "\n",
        ]

        includes = []
        for filename in sorted(generated_files):
            include_path = os.path.join(self.output_dir, filename)
            includes.append(f"include {include_path}\n")

        try:
            with open(self.input_file, "w", encoding="utf-8") as f:
                f.writelines(header)
                f.writelines(includes)
            logger.info(
                f"Main configuration file regenerated with {len(includes)} includes"
            )
        except Exception as e:
            logger.error(f"Failed to generate main config: {e}")
            raise RuntimeError(f"Failed to generate main config: {e}")

    def get_split_info(self) -> dict[str, str]:
        return {
            "00_ports.conf": "HTTP ports configuration",
            "10_misc.conf": "Miscellaneous configurations",
            "20_security.conf": "Security configuration",
            "30_cache.conf": "Cache configuration",
            "40_refresh_patterns.conf": "Refresh patterns",
            "50_ssl_bump.conf": "SSL Bump configuration",
            "60_logs.conf": "Logs configuration",
            "70_icap.conf": "ICAP configuration",
            "80_dns.conf": "DNS configuration",
            "90_auth.conf": "Authentication configuration",
            "100_acls.conf": "Access control lists (ACLs)",
            "110_delay_pools.conf": "Delay pools configuration",
            "115_cache_control.conf": "Cache control and peering",
            "120_http_access.conf": "HTTP access rules",
            "999_unknown.conf": "Unclassified directives",
        }

    def check_output_dir_exists(self) -> bool:
        return os.path.exists(self.output_dir) and os.path.isdir(self.output_dir)

    def count_files_in_output_dir(self) -> int:
        if not self.check_output_dir_exists():
            return 0
        return len([f for f in os.listdir(self.output_dir) if f.endswith(".conf")])
