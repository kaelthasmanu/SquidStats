import logging
import os
import shutil
from datetime import datetime

# Configurar logging para este módulo
logger = logging.getLogger(__name__)

# Configuración para Squid
SQUID_CONFIG_PATH = "/home/manuel/Desktop/config"
BACKUP_DIR = "/home/manuel/Desktop/config/backups"
ACL_FILES_DIR = "/home/manuel/Desktop/config/acls"


def validate_paths():
    errors = []

    # Verificar archivo de configuración
    if not os.path.exists(SQUID_CONFIG_PATH):
        errors.append(f"Configuration file not found: {SQUID_CONFIG_PATH}")
    elif not os.access(SQUID_CONFIG_PATH, os.R_OK):
        errors.append(f"No read permissions for: {SQUID_CONFIG_PATH}")
    elif not os.access(SQUID_CONFIG_PATH, os.W_OK):
        errors.append(f"No write permissions for: {SQUID_CONFIG_PATH}")

    # Verificar directorio de backups
    if not os.path.exists(BACKUP_DIR):
        errors.append(f"Backup directory not found: {BACKUP_DIR}")
    elif not os.access(BACKUP_DIR, os.W_OK):
        errors.append(
            f"No write permissions in backup directory: {BACKUP_DIR}"
        )

    # Verificar directorio de ACLs
    if not os.path.exists(ACL_FILES_DIR):
        errors.append(f"ACL directory not found: {ACL_FILES_DIR}")
    elif not os.access(ACL_FILES_DIR, os.W_OK):
        errors.append(
            f"No write permissions in ACL directory: {ACL_FILES_DIR}"
        )

    return errors


class SquidConfigManager:
    def __init__(self, config_path=SQUID_CONFIG_PATH):
        self.config_path = config_path
        self.config_content = ""
        self.is_valid = False
        self.errors = []

        # Validar entorno antes de cargar
        self._validate_environment()

        # Solo cargar si no hay errores críticos
        if self.is_valid:
            self.load_config()

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
            # Intentar crear backup antes de guardar
            backup_created = self.create_backup()
            if not backup_created:
                logger.warning(
                    "Could not create backup, but continuing with save..."
                )

            # Guardar nueva configuración
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

        try:
            # Verificar que el directorio de backup existe
            if not os.path.exists(BACKUP_DIR):
                logger.error(f"Backup directory does not exist: {BACKUP_DIR}")
                return False

            # Verificar permisos de escritura
            if not os.access(BACKUP_DIR, os.W_OK):
                logger.error(
                    f"No write permissions in backup directory: {BACKUP_DIR}"
                )
                return False

            # Verificar que el archivo fuente existe
            if not os.path.exists(self.config_path):
                logger.warning("No configuration file exists to backup")
                return False

            # Crear backup con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"squid.conf.backup_{timestamp}"
            backup_path = os.path.join(BACKUP_DIR, backup_filename)

            shutil.copy2(self.config_path, backup_path)
            logger.info(f"Backup created: {backup_path}")
            return True

        except PermissionError:
            logger.error(f"No permissions to create backup in: {BACKUP_DIR}")
            return False
        except OSError as e:
            logger.error(f"System error creating backup: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error creating backup: {e}")
            return False

    def get_acls(self):
        if not self.is_valid:
            logger.error("Cannot get ACLs: invalid environment")
            return []

        if not self.config_content:
            logger.warning("No configuration content available")
            return []

        try:
            acls = []
            lines = self.config_content.split("\n")
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

        if not self.config_content:
            logger.warning("No configuration content available")
            return []

        try:
            delay_pools = []
            lines = self.config_content.split("\n")

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

            logger.debug(
                f"Found {len(delay_pools)} delay pool configurations"
            )
            return delay_pools

        except Exception as e:
            logger.error(f"Unexpected error extracting delay pools: {e}")
            return []

    def get_http_access_rules(self):
        if not self.is_valid:
            logger.error("Cannot get HTTP rules: invalid environment")
            return []

        if not self.config_content:
            logger.warning("No configuration content available")
            return []

        try:
            rules = []
            lines = self.config_content.split("\n")

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

    def get_status(self):
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "config_loaded": bool(self.config_content),
            "config_path": self.config_path,
            "backup_dir": BACKUP_DIR,
            "acl_files_dir": ACL_FILES_DIR,
        }
