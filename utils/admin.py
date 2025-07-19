import os
import shutil
from datetime import datetime

# Configuración para Squid
SQUID_CONFIG_PATH = '/etc/squid/squid.conf'
BACKUP_DIR = '/etc/squid/backups'
ACL_FILES_DIR = '/etc/squid/acls'


class SquidConfigManager:
    def __init__(self, config_path=SQUID_CONFIG_PATH):
        self.config_path = config_path
        self.config_content = ""
        self.load_config()
    def load_config(self):
        """Cargar el archivo de configuración"""
        try:
            with open(self.config_path, encoding='utf-8') as f:
                self.config_content = f.read()
        except FileNotFoundError:
            self.config_content = ""
    def save_config(self, content):
        """Guardar la configuración con backup"""
        # Crear backup
        self.create_backup()
        # Guardar nueva configuración
        with open(self.config_path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.config_content = content
    def create_backup(self):
        """Crear backup de la configuración actual"""
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(BACKUP_DIR, f'squid.conf.backup_{timestamp}')
        shutil.copy2(self.config_path, backup_path)

    def get_acls(self):
        """Extraer ACLs del archivo de configuración"""
        acls = []
        lines = self.config_content.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('acl ') and not line.startswith('#'):
                parts = line.split()
                if len(parts) >= 3:
                    acl_name = parts[1]
                    acl_type = parts[2]
                    acl_value = ' '.join(parts[3:]) if len(parts) > 3 else ''
                    acls.append({
                        'name': acl_name,
                        'type': acl_type,
                        'value': acl_value,
                        'full_line': line
                    })
        return acls

    def get_delay_pools(self):
        """Extraer configuración de delay pools"""
        delay_pools = []
        lines = self.config_content.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('delay_pools '):
                parts = line.split()
                if len(parts) >= 2:
                    delay_pools.append({
                        'directive': 'delay_pools',
                        'value': parts[1]
                    })
            elif line.startswith('delay_class '):
                parts = line.split()
                if len(parts) >= 3:
                    delay_pools.append({
                        'directive': 'delay_class',
                        'pool': parts[1],
                        'class': parts[2]
                    })
            elif line.startswith('delay_parameters '):
                parts = line.split()
                if len(parts) >= 3:
                    delay_pools.append({
                        'directive': 'delay_parameters',
                        'pool': parts[1],
                        'parameters': ' '.join(parts[2:])
                    })
            elif line.startswith('delay_access '):
                parts = line.split()
                if len(parts) >= 4:
                    delay_pools.append({
                        'directive': 'delay_access',
                        'pool': parts[1],
                        'action': parts[2],
                        'acl': ' '.join(parts[3:])
                    })
        return delay_pools

    def get_http_access_rules(self):
        """Extraer reglas de acceso HTTP"""
        rules = []
        lines = self.config_content.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('http_access ') and not line.startswith('#'):
                parts = line.split()
                if len(parts) >= 3:
                    rules.append({
                        'action': parts[1],
                        'acl': ' '.join(parts[2:])
                    })
        return rules
