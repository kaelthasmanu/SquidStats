import logging
import os
import shutil
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# SQUID_CONFIG_PATH = os.getenv("SQUID_CONFIG_PATH", "/etc/squid/squid.conf")
# ACL_FILES_DIR = os.getenv("ACL_FILES_DIR", "/etc/squid/acls")
SQUID_CONFIG_PATH = "/etc/squid/squid.conf"
ACL_FILES_DIR = "/etc/squid/squid.d/"


def validate_paths():
    errors = []

    cfg = os.path.abspath(os.path.expanduser(SQUID_CONFIG_PATH))

    if os.path.isdir(cfg):
        squid_conf = os.path.join(cfg, "squid.conf")
        if not os.path.exists(squid_conf):
            errors.append(f"'squid.conf' not found in directory: {cfg}")
        else:
            if not os.path.isfile(squid_conf):
                errors.append(f"Found but not a regular file: {squid_conf}")
            else:
                if not os.access(squid_conf, os.R_OK):
                    errors.append(f"No read permissions for: {squid_conf}")
                if not os.access(squid_conf, os.W_OK):
                    errors.append(f"No write permissions for: {squid_conf}")
    else:
        squid_conf = cfg
        if not os.path.exists(squid_conf):
            errors.append(f"Configuration file not found: {squid_conf}")
        else:
            if not os.path.isfile(squid_conf):
                errors.append(f"Not a regular file: {squid_conf}")
            if os.path.basename(squid_conf) != "squid.conf":
                errors.append(
                    f"Expected file named 'squid.conf', got: {os.path.basename(squid_conf)}"
                )
            if os.path.isfile(squid_conf):
                if not os.access(squid_conf, os.R_OK):
                    errors.append(f"No read permissions for: {squid_conf}")
                if not os.access(squid_conf, os.W_OK):
                    errors.append(f"No write permissions for: {squid_conf}")

    acl_dir = os.path.abspath(os.path.expanduser(ACL_FILES_DIR))
    if not os.path.exists(acl_dir):
        errors.append(f"ACL directory not found: {acl_dir}")
    elif not os.path.isdir(acl_dir):
        errors.append(f"ACL path is not a directory: {acl_dir}")
    elif not os.access(acl_dir, os.W_OK):
        errors.append(f"No write permissions in ACL directory: {acl_dir}")

    return errors


class SquidConfigManager:
    def __init__(self, config_path=SQUID_CONFIG_PATH, config_dir=ACL_FILES_DIR):
        self.config_path = config_path
        self.config_dir = config_dir
        self.config_content = ""
        self.is_valid = False
        self.errors = []
        self.is_modular = False  # Flag to check if using modular configs

        self._validate_environment()

        if self.is_valid:
            self.load_config()
            self._check_modular_config()

    def _validate_environment(self):
        self.errors = validate_paths()

        if self.errors:
            for error in self.errors:
                logger.error(error)
            self.is_valid = False
            logger.error(
                "SquidConfigManager cannot be initialized due to configuration errors"
            )
        else:
            self.is_valid = True
            logger.info("SquidConfigManager initialized successfully")

    def load_config(self):
        if not self.is_valid:
            logger.error("Cannot load configuration: invalid environment")
            return False

        try:
            with open(self.config_path, encoding="utf-8") as f:
                self.config_content = f.read()
            logger.debug(f"Configuration loaded from: {self.config_path}")
            return True
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            self.config_content = ""
            return False
        except PermissionError:
            logger.error(f"No read permissions for: {self.config_path}")
            self.config_content = ""
            return False
        except UnicodeDecodeError as e:
            logger.error(f"File encoding error: {e}")
            self.config_content = ""
            return False
        except Exception as e:
            logger.error(f"Unexpected error loading configuration: {e}")
            self.config_content = ""
            return False

    def save_config(self, content):
        if not self.is_valid:
            logger.error("Cannot save configuration: invalid environment")
            return False

        try:
            backup_created = self.create_backup()
            if not backup_created:
                logger.warning("Could not create backup, but continuing with save...")

            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(content)

            self.config_content = content
            logger.info(f"Configuration saved successfully to: {self.config_path}")
            return True

        except PermissionError:
            logger.error(f"No write permissions for: {self.config_path}")
            return False
        except OSError as e:
            logger.error(f"System error saving configuration: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving configuration: {e}")
            return False

    def create_backup(self):
        if not self.is_valid:
            logger.error("Cannot create backup: invalid environment")
            return False

    def get_acls(self):
        if not self.is_valid:
            logger.error("Cannot get ACLs: invalid environment")
            return []

        # If using modular config, read from the ACLs specific file
        if self.is_modular:
            acl_content = self.read_modular_config("100_acls.conf")
            if not acl_content:
                logger.warning("Could not read modular ACL config, falling back to main config")
                config_to_parse = self.config_content
            else:
                config_to_parse = acl_content
        else:
            if not self.config_content:
                logger.warning("No configuration content available")
                return []
            config_to_parse = self.config_content

        try:
            acls = []
            lines = config_to_parse.split("\n")
            acl_index = 0

            for line_num, line in enumerate(lines, 1):
                try:
                    line = line.strip()
                    if line.startswith("acl ") and not line.startswith("#"):
                        parts = line.split()
                        if len(parts) >= 3:
                            acl_name = parts[1]
                            acl_type = parts[2]
                            acl_value = " ".join(parts[3:]) if len(parts) > 3 else ""
                            acls.append(
                                {
                                    "id": acl_index,
                                    "name": acl_name,
                                    "type": acl_type,
                                    "value": acl_value,
                                    "full_line": line,
                                }
                            )
                            acl_index += 1
                except Exception as e:
                    logger.warning(f"Error processing ACL at line {line_num}: {e}")
                    continue

            logger.debug(f"Found {len(acls)} ACLs")
            return acls

        except Exception as e:
            logger.error(f"Unexpected error extracting ACLs: {e}")
            return []

    def get_delay_pools(self):
        if not self.is_valid:
            logger.error("Cannot get delay pools: invalid environment")
            return []

        # If using modular config, read from the delay pools specific file
        if self.is_modular:
            delay_content = self.read_modular_config("110_delay_pools.conf")
            if not delay_content:
                logger.warning("Could not read modular delay pools config, falling back to main config")
                config_to_parse = self.config_content
            else:
                config_to_parse = delay_content
        else:
            if not self.config_content:
                logger.warning("No configuration content available")
                return []
            config_to_parse = self.config_content

        try:
            delay_pools = []
            lines = config_to_parse.split("\n")

            for line_num, line in enumerate(lines, 1):
                try:
                    line = line.strip()
                    if line.startswith("delay_pools "):
                        parts = line.split()
                        if len(parts) >= 2:
                            delay_pools.append(
                                {"directive": "delay_pools", "value": parts[1]}
                            )
                    elif line.startswith("delay_class "):
                        parts = line.split()
                        if len(parts) >= 3:
                            delay_pools.append(
                                {
                                    "directive": "delay_class",
                                    "pool": parts[1],
                                    "class": parts[2],
                                }
                            )
                    elif line.startswith("delay_parameters "):
                        parts = line.split()
                        if len(parts) >= 3:
                            delay_pools.append(
                                {
                                    "directive": "delay_parameters",
                                    "pool": parts[1],
                                    "parameters": " ".join(parts[2:]),
                                }
                            )
                    elif line.startswith("delay_access "):
                        parts = line.split()
                        if len(parts) >= 4:
                            delay_pools.append(
                                {
                                    "directive": "delay_access",
                                    "pool": parts[1],
                                    "action": parts[2],
                                    "acl": " ".join(parts[3:]),
                                }
                            )
                except Exception as e:
                    logger.warning(
                        f"Error processing delay pool at line {line_num}: {e}"
                    )
                    continue

            logger.debug(f"Found {len(delay_pools)} delay pool configurations")
            return delay_pools

        except Exception as e:
            logger.error(f"Unexpected error extracting delay pools: {e}")
            return []

    def get_http_access_rules(self):
        if not self.is_valid:
            logger.error("Cannot get HTTP rules: invalid environment")
            return []

        # If using modular config, read from the http_access specific file
        if self.is_modular:
            http_content = self.read_modular_config("120_http_access.conf")
            if not http_content:
                logger.warning("Could not read modular http_access config, falling back to main config")
                config_to_parse = self.config_content
            else:
                config_to_parse = http_content
        else:
            if not self.config_content:
                logger.warning("No configuration content available")
                return []
            config_to_parse = self.config_content

        try:
            rules = []
            lines = config_to_parse.split("\n")

            for line_num, line in enumerate(lines, 1):
                try:
                    line = line.strip()
                    if line.startswith("http_access ") and not line.startswith("#"):
                        parts = line.split()
                        if len(parts) >= 3:
                            rules.append(
                                {"action": parts[1], "acl": " ".join(parts[2:])}
                            )
                except Exception as e:
                    logger.warning(
                        f"Error processing HTTP rule at line {line_num}: {e}"
                    )
                    continue

            logger.debug(f"Found {len(rules)} HTTP access rules")
            return rules

        except Exception as e:
            logger.error(f"Unexpected error extracting HTTP rules: {e}")
            return []

    def _check_modular_config(self):
        """Check if the main config file uses modular includes."""
        if not self.config_content:
            return

        # Check if config contains include directives pointing to squid.d
        self.is_modular = "include" in self.config_content.lower() and "squid.d" in self.config_content
        if self.is_modular:
            logger.info("Modular configuration detected")

    def list_modular_configs(self) -> list[dict[str, str]]:
        """List all modular configuration files in squid.d directory."""
        if not os.path.exists(self.config_dir):
            logger.warning(f"Config directory not found: {self.config_dir}")
            return []

        try:
            configs = []
            for filename in sorted(os.listdir(self.config_dir)):
                if filename.endswith('.conf'):
                    filepath = os.path.join(self.config_dir, filename)
                    if os.path.isfile(filepath):
                        try:
                            stat = os.stat(filepath)
                            configs.append({
                                "filename": filename,
                                "filepath": filepath,
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                                "readable": os.access(filepath, os.R_OK),
                                "writable": os.access(filepath, os.W_OK),
                            })
                        except Exception as e:
                            logger.warning(f"Error reading file info for {filename}: {e}")
            return configs
        except Exception as e:
            logger.error(f"Error listing modular configs: {e}")
            return []

    def read_modular_config(self, filename: str) -> Optional[str]:
        """Read a specific modular configuration file."""
        filepath = os.path.join(self.config_dir, filename)

        if not os.path.exists(filepath):
            logger.error(f"Config file not found: {filepath}")
            return None

        if not filepath.endswith('.conf'):
            logger.error(f"Invalid file extension: {filename}")
            return None

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.debug(f"Read modular config: {filename}")
            return content
        except Exception as e:
            logger.error(f"Error reading modular config {filename}: {e}")
            return None

    def save_modular_config(self, filename: str, content: str) -> bool:
        """Save content to a specific modular configuration file."""
        filepath = os.path.join(self.config_dir, filename)

        if not filename.endswith('.conf'):
            logger.error(f"Invalid file extension: {filename}")
            return False

        # Validate filename to prevent directory traversal
        if '/' in filename or '\\' in filename or '..' in filename:
            logger.error(f"Invalid filename (potential path traversal): {filename}")
            return False

        try:
            # Create backup before saving
            if os.path.exists(filepath):
                backup_path = f"{filepath}.bak{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                try:
                    shutil.copy2(filepath, backup_path)
                    logger.info(f"Backup created: {backup_path}")
                except Exception as e:
                    logger.warning(f"Could not create backup: {e}")

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"Saved modular config: {filename}")
            return True
        except Exception as e:
            logger.error(f"Error saving modular config {filename}: {e}")
            return False

    def delete_modular_config(self, filename: str) -> bool:
        """Delete a specific modular configuration file."""
        filepath = os.path.join(self.config_dir, filename)

        if not os.path.exists(filepath):
            logger.error(f"Config file not found: {filepath}")
            return False

        if not filename.endswith('.conf'):
            logger.error(f"Invalid file extension: {filename}")
            return False

        # Validate filename to prevent directory traversal
        if '/' in filename or '\\' in filename or '..' in filename:
            logger.error(f"Invalid filename (potential path traversal): {filename}")
            return False

        try:
            # Create backup before deleting
            backup_path = f"{filepath}.deleted{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                shutil.move(filepath, backup_path)
                logger.info(f"File moved to: {backup_path}")
                return True
            except Exception as e:
                logger.error(f"Error deleting file {filename}: {e}")
                return False
        except Exception as e:
            logger.error(f"Error handling file deletion {filename}: {e}")
            return False

    def get_modular_config_info(self) -> dict:
        """Get information about the modular configuration setup."""
        return {
            "is_modular": self.is_modular,
            "config_dir": self.config_dir,
            "config_dir_exists": os.path.exists(self.config_dir),
            "config_files_count": len(self.list_modular_configs()),
            "main_config_path": self.config_path,
        }

    def get_status(self):
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "config_loaded": bool(self.config_content),
            "config_path": self.config_path,
            "config_dir": self.config_dir,
            "is_modular": self.is_modular,
            "acl_files_dir": ACL_FILES_DIR,
        }
