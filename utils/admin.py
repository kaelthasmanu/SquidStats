import os
import shutil
import logging
from datetime import datetime

# Configurar logging para este módulo
logger = logging.getLogger(__name__)

# Configuración para Squid
SQUID_CONFIG_PATH = "/home/manuel/Desktop/config"
BACKUP_DIR = "/home/manuel/Desktop/config/backups"
ACL_FILES_DIR = "/home/manuel/Desktop/config/acls"


def validate_paths():
    """Validar que existan los directorios y archivos necesarios."""
    errors = []
    
    # Verificar archivo de configuración
    if not os.path.exists(SQUID_CONFIG_PATH):
        errors.append(f"Archivo de configuración no encontrado: {SQUID_CONFIG_PATH}")
    elif not os.access(SQUID_CONFIG_PATH, os.R_OK):
        errors.append(f"Sin permisos de lectura para: {SQUID_CONFIG_PATH}")
    elif not os.access(SQUID_CONFIG_PATH, os.W_OK):
        errors.append(f"Sin permisos de escritura para: {SQUID_CONFIG_PATH}")
    
    # Verificar directorio de backups
    if not os.path.exists(BACKUP_DIR):
        errors.append(f"Directorio de backups no encontrado: {BACKUP_DIR}")
    elif not os.access(BACKUP_DIR, os.W_OK):
        errors.append(f"Sin permisos de escritura en directorio de backups: {BACKUP_DIR}")
    
    # Verificar directorio de ACLs
    if not os.path.exists(ACL_FILES_DIR):
        errors.append(f"Directorio de ACLs no encontrado: {ACL_FILES_DIR}")
    elif not os.access(ACL_FILES_DIR, os.W_OK):
        errors.append(f"Sin permisos de escritura en directorio de ACLs: {ACL_FILES_DIR}")
    
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
        """Validar que el entorno esté correctamente configurado."""
        self.errors = validate_paths()
        
        if self.errors:
            for error in self.errors:
                logger.error(error)
            self.is_valid = False
            logger.error("SquidConfigManager no se puede inicializar debido a errores de configuración")
        else:
            self.is_valid = True
            logger.info("SquidConfigManager inicializado correctamente")

    def load_config(self):
        """Cargar el archivo de configuración con manejo de errores."""
        if not self.is_valid:
            logger.error("No se puede cargar configuración: entorno no válido")
            return False
            
        try:
            with open(self.config_path, encoding="utf-8") as f:
                self.config_content = f.read()
            logger.debug(f"Configuración cargada desde: {self.config_path}")
            return True
        except FileNotFoundError:
            logger.error(f"Archivo de configuración no encontrado: {self.config_path}")
            self.config_content = ""
            return False
        except PermissionError:
            logger.error(f"Sin permisos para leer: {self.config_path}")
            self.config_content = ""
            return False
        except UnicodeDecodeError as e:
            logger.error(f"Error de codificación al leer el archivo: {e}")
            self.config_content = ""
            return False
        except Exception as e:
            logger.error(f"Error inesperado al cargar configuración: {e}")
            self.config_content = ""
            return False

    def save_config(self, content):
        """Guardar la configuración con backup y manejo de errores."""
        if not self.is_valid:
            logger.error("No se puede guardar configuración: entorno no válido")
            return False
            
        try:
            # Intentar crear backup antes de guardar
            backup_created = self.create_backup()
            if not backup_created:
                logger.warning("No se pudo crear backup, pero continuando con guardado...")
            
            # Guardar nueva configuración
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            self.config_content = content
            logger.info(f"Configuración guardada exitosamente en: {self.config_path}")
            return True
            
        except PermissionError:
            logger.error(f"Sin permisos para escribir en: {self.config_path}")
            return False
        except OSError as e:
            logger.error(f"Error del sistema al guardar configuración: {e}")
            return False
        except Exception as e:
            logger.error(f"Error inesperado al guardar configuración: {e}")
            return False

    def create_backup(self):
        """Crear backup de la configuración actual con manejo de errores."""
        if not self.is_valid:
            logger.error("No se puede crear backup: entorno no válido")
            return False
            
        try:
            # Verificar que el directorio de backup existe
            if not os.path.exists(BACKUP_DIR):
                logger.error(f"Directorio de backup no existe: {BACKUP_DIR}")
                return False
            
            # Verificar permisos de escritura
            if not os.access(BACKUP_DIR, os.W_OK):
                logger.error(f"Sin permisos de escritura en directorio de backup: {BACKUP_DIR}")
                return False
            
            # Verificar que el archivo fuente existe
            if not os.path.exists(self.config_path):
                logger.warning("No existe archivo de configuración para respaldar")
                return False
            
            # Crear backup con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"squid.conf.backup_{timestamp}"
            backup_path = os.path.join(BACKUP_DIR, backup_filename)
            
            shutil.copy2(self.config_path, backup_path)
            logger.info(f"Backup creado: {backup_path}")
            return True
            
        except PermissionError:
            logger.error(f"Sin permisos para crear backup en: {BACKUP_DIR}")
            return False
        except OSError as e:
            logger.error(f"Error del sistema al crear backup: {e}")
            return False
        except Exception as e:
            logger.error(f"Error inesperado al crear backup: {e}")
            return False

    def get_acls(self):
        """Extraer ACLs del archivo de configuración con manejo de errores."""
        if not self.is_valid:
            logger.error("No se pueden obtener ACLs: entorno no válido")
            return []
            
        if not self.config_content:
            logger.warning("No hay contenido de configuración disponible")
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
                            acls.append({
                                "id": acl_index,
                                "name": acl_name,
                                "type": acl_type,
                                "value": acl_value,
                                "full_line": line,
                            })
                            acl_index += 1
                except Exception as e:
                    logger.warning(f"Error procesando ACL en línea {line_num}: {e}")
                    continue
                    
            logger.debug(f"Se encontraron {len(acls)} ACLs")
            return acls
            
        except Exception as e:
            logger.error(f"Error inesperado al extraer ACLs: {e}")
            return []

    def get_delay_pools(self):
        """Extraer configuración de delay pools con manejo de errores."""
        if not self.is_valid:
            logger.error("No se pueden obtener delay pools: entorno no válido")
            return []
            
        if not self.config_content:
            logger.warning("No hay contenido de configuración disponible")
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
                            delay_pools.append({"directive": "delay_pools", "value": parts[1]})
                    elif line.startswith("delay_class "):
                        parts = line.split()
                        if len(parts) >= 3:
                            delay_pools.append({
                                "directive": "delay_class",
                                "pool": parts[1],
                                "class": parts[2],
                            })
                    elif line.startswith("delay_parameters "):
                        parts = line.split()
                        if len(parts) >= 3:
                            delay_pools.append({
                                "directive": "delay_parameters",
                                "pool": parts[1],
                                "parameters": " ".join(parts[2:]),
                            })
                    elif line.startswith("delay_access "):
                        parts = line.split()
                        if len(parts) >= 4:
                            delay_pools.append({
                                "directive": "delay_access",
                                "pool": parts[1],
                                "action": parts[2],
                                "acl": " ".join(parts[3:]),
                            })
                except Exception as e:
                    logger.warning(f"Error procesando delay pool en línea {line_num}: {e}")
                    continue
                    
            logger.debug(f"Se encontraron {len(delay_pools)} configuraciones de delay pools")
            return delay_pools
            
        except Exception as e:
            logger.error(f"Error inesperado al extraer delay pools: {e}")
            return []

    def get_http_access_rules(self):
        """Extraer reglas de acceso HTTP con manejo de errores."""
        if not self.is_valid:
            logger.error("No se pueden obtener reglas HTTP: entorno no válido")
            return []
            
        if not self.config_content:
            logger.warning("No hay contenido de configuración disponible")
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
                            rules.append({"action": parts[1], "acl": " ".join(parts[2:])})
                except Exception as e:
                    logger.warning(f"Error procesando regla HTTP en línea {line_num}: {e}")
                    continue
                    
            logger.debug(f"Se encontraron {len(rules)} reglas de acceso HTTP")
            return rules
            
        except Exception as e:
            logger.error(f"Error inesperado al extraer reglas HTTP: {e}")
            return []

    def get_status(self):
        """Obtener el estado actual del manager."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "config_loaded": bool(self.config_content),
            "config_path": self.config_path,
            "backup_dir": BACKUP_DIR,
            "acl_files_dir": ACL_FILES_DIR
        }
