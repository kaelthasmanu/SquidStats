import os
import subprocess
from datetime import datetime
import threading
import time
from typing import List, Dict, Any

# Almacenamiento mejorado de notificaciones
notifications_store = {
    'notifications': [],
    'unread_count': 0,
    'last_check': None
}

# Variable global para Socket.IO
socketio = None

def set_socketio_instance(sio):
    global socketio
    socketio = sio

def set_commit_notifications(has_updates, messages):
    """Mantener por compatibilidad"""
    # Convertir commits a notificaciones del sistema
    if has_updates and messages:
        for msg in messages:
            add_notification('info', f"Commit: {msg}", 'fa-code-branch', 'git')

def get_commit_notifications():
    """Mantener por compatibilidad con código existente"""
    return {
        'has_updates': len([n for n in notifications_store['notifications'] if n.get('source') == 'git']) > 0,
        'commits': [n['message'].replace('Commit: ', '') for n in notifications_store['notifications'] if n.get('source') == 'git']
    }

def add_notification(notification_type: str, message: str, icon: str = None, source: str = "system"):
    """Agrega una notificación al sistema y emite via Socket.IO si está configurado"""
    notification = {
        'id': len(notifications_store['notifications']) + 1,
        'type': notification_type,  # 'info', 'warning', 'error', 'success'
        'message': message,
        'icon': icon or get_default_icon(notification_type),
        'timestamp': datetime.now().isoformat(),
        'time': 'Hace unos momentos',
        'read': False,
        'source': source
    }
    
    # Agregar al inicio de la lista
    notifications_store['notifications'].insert(0, notification)
    
    # Incrementar contador de no leídas
    if not notification['read']:
        notifications_store['unread_count'] += 1
    
    # Mantener máximo 50 notificaciones
    if len(notifications_store['notifications']) > 50:
        # Eliminar las más antiguas, pero mantener las no leídas si es posible
        old_notifications = notifications_store['notifications'][50:]
        for old_notif in old_notifications:
            if not old_notif['read']:
                notifications_store['unread_count'] -= 1
        notifications_store['notifications'] = notifications_store['notifications'][:50]
    
    # Emitir via Socket.IO si está configurado
    if socketio:
        socketio.emit('new_notification', {
            'notification': notification,
            'unread_count': notifications_store['unread_count']
        })
    
    return notification

def get_default_icon(notification_type):
    icons = {
        'info': 'fa-info-circle',
        'warning': 'fa-exclamation-triangle',
        'error': 'fa-times-circle',
        'success': 'fa-check-circle'
    }
    return icons.get(notification_type, 'fa-bell')

def get_all_notifications(limit: int = 10) -> Dict[str, Any]:
    """Obtiene todas las notificaciones del sistema"""
    return {
        'unread_count': notifications_store['unread_count'],
        'notifications': notifications_store['notifications'][:limit]
    }

def mark_notifications_read(notification_ids: List[int]):
    """Marca notificaciones como leídas"""
    for notification in notifications_store['notifications']:
        if notification['id'] in notification_ids and not notification['read']:
            notification['read'] = True
            notifications_store['unread_count'] -= 1

def check_squid_service():
    """Verifica el estado del servicio Squid y genera notificaciones"""
    try:
        # Verificar si Squid está corriendo
        result = subprocess.run(
            ['systemctl', 'is-active', 'squid'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            add_notification('error', 'Servicio Squid no está corriendo', 'fa-exclamation-triangle', 'squid')
        else:
            # Verificar logs de errores recientes de Squid
            log_check = subprocess.run(
                ['journalctl', '-u', 'squid', '--since', '1 hour ago', '--no-pager'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if 'error' in log_check.stdout.lower() or 'failed' in log_check.stdout.lower():
                add_notification('warning', 'Errores detectados en logs de Squid', 'fa-exclamation-triangle', 'squid')
                
    except subprocess.TimeoutExpired:
        add_notification('warning', 'Timeout al verificar estado de Squid', 'fa-clock', 'squid')
    except Exception as e:
        print(f"Error checking Squid service: {e}")

def check_squid_log_health():
    """Verifica la salud de los logs de Squid"""
    try:
        log_file = os.getenv("SQUID_LOG", "/var/log/squid/access.log")
        
        if os.path.exists(log_file):
            # Verificar si el archivo de log está creciendo
            stat_info = os.stat(log_file)
            file_size_mb = stat_info.st_size / (1024 * 1024)
            
            if file_size_mb > 100:  # Más de 100MB
                add_notification('warning', f'Log de Squid muy grande: {file_size_mb:.1f}MB', 'fa-file-alt', 'squid')
            
            # Verificar última modificación (no se actualiza en más de 5 minutos)
            last_modified = datetime.fromtimestamp(stat_info.st_mtime)
            time_diff = datetime.now() - last_modified
            if time_diff.total_seconds() > 300:  # 5 minutos
                add_notification('warning', 'Log de Squid no se actualiza hace más de 5 minutos', 'fa-clock', 'squid')
                
        else:
            add_notification('error', f'Archivo de log de Squid no encontrado: {log_file}', 'fa-file-exclamation', 'squid')
            
    except Exception as e:
        print(f"Error checking Squid log health: {e}")

def check_system_health():
    """Verifica la salud general del sistema"""
    try:
        # Verificar uso de disco
        disk_usage = os.statvfs('/')
        free_disk = (disk_usage.f_bavail * disk_usage.f_frsize) / (1024 ** 3)  # GB libres
        
        if free_disk < 1:  # Menos de 1GB libres
            add_notification('error', f'Espacio en disco crítico: {free_disk:.1f}GB libres', 'fa-hdd', 'system')
        elif free_disk < 5:  # Menos de 5GB libres
            add_notification('warning', f'Espacio en disco bajo: {free_disk:.1f}GB libres', 'fa-hdd', 'system')
            
    except Exception as e:
        print(f"Error checking system health: {e}")

# Función para commits
def has_remote_commits_with_messages(
    repo_path: str, branch: str = "main"
) -> tuple[bool, list[str]]:
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise ValueError(f"No es un repositorio Git válido: {repo_path}")
    try:
        # Configurar proxy si existe la variable de entorno
        env = os.environ.copy()
        http_proxy = env.get("HTTP_PROXY", "")
        if http_proxy:
            env["http_proxy"] = http_proxy
            env["https_proxy"] = http_proxy

        subprocess.run(
            ["git", "fetch"],
            cwd=repo_path,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        result = subprocess.run(
            [
                "git",
                "rev-list",
                "--left-right",
                "--count",
                f"origin/{branch}...{branch}",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        ahead_behind = result.stdout.strip().split()
        remote_ahead = int(ahead_behind[0])

        if remote_ahead > 0:
            log_result = subprocess.run(
                ["git", "log", f"{branch}..origin/{branch}", "--pretty=format:%s"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            commit_messages = (
                log_result.stdout.strip().split("\n")
                if log_result.stdout.strip()
                else []
            )
            return True, commit_messages

        return False, []

    except subprocess.CalledProcessError as e:
        print(f"Error al ejecutar comandos git: {e.stderr}")
        return False, []

# Hilo para verificaciones periódicas
def start_notification_monitor():
    """Inicia el monitor de notificaciones en segundo plano"""
    def monitor_loop():
        check_count = 0
        while True:
            try:
                # Verificar commits cada 30 minutos (cada 15 ciclos)
                if check_count % 15 == 0:
                    current_file_dir = os.path.dirname(os.path.abspath(__file__))
                    repo_path = os.path.dirname(current_file_dir)  # Subir un nivel
                    if os.path.exists(repo_path):
                        has_updates, messages = has_remote_commits_with_messages(repo_path)
                        set_commit_notifications(has_updates, messages)
                
                # Verificaciones CRÍTICAS cada 2 minutos (siempre)
                check_squid_service()
                check_squid_log_health()
                check_system_health()
                
                # Verificaciones de SEGURIDAD cada 5 minutos (cada 2-3 ciclos)
                if check_count % 3 == 0:
                    check_security_events()
                
                # Verificaciones de USUARIOS cada 10 minutos (cada 5 ciclos)
                if check_count % 5 == 0:
                    check_user_activity()
                
                check_count += 1
                if check_count > 1000:  # Prevenir overflow
                    check_count = 0
                
            except Exception as e:
                print(f"Error en monitor de notificaciones: {e}")
            
            time.sleep(120)  # Esperar 2 minutos entre ciclos
    
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()

# Funciones específicas para Squid que pueden ser llamadas desde otras partes
def notify_squid_restart_success():
    """Notificar reinicio exitoso de Squid"""
    add_notification('success', 'Squid reiniciado correctamente', 'fa-sync-alt', 'squid')

def notify_squid_restart_failed(error_message: str = ""):
    """Notificar fallo en reinicio de Squid"""
    message = 'Error al reiniciar Squid'
    if error_message:
        message += f': {error_message}'
    add_notification('error', message, 'fa-exclamation-triangle', 'squid')

def notify_squid_config_error(error_message: str):
    """Notificar error en configuración de Squid"""
    add_notification('error', f'Error en configuración de Squid: {error_message}', 'fa-cog', 'squid')

def notify_squid_high_usage(warning_message: str):
    """Notificar uso alto de recursos de Squid"""
    add_notification('warning', warning_message, 'fa-chart-line', 'squid')

def check_security_events():
    """Verifica eventos de seguridad desde la base de datos"""
    try:
        from database.database import get_session
        from services.auditoria_service import (
            find_suspicious_activity, 
            get_failed_auth_attempts,
            get_denied_requests
        )
        
        db = get_session()
        
        # 1. Intentos de autenticación fallidos
        failed_auth_count = get_failed_auth_attempts(db, hours=1)
        if failed_auth_count > 15:
            add_notification('warning', 
                f'{failed_auth_count} intentos de autenticación fallidos en la última hora', 
                'fa-shield-alt', 'security')
        
        # 2. Requests denegados
        denied_count = get_denied_requests(db, hours=1)
        if denied_count > 20:
            add_notification('warning',
                f'{denied_count} requests denegados en la última hora',
                'fa-ban', 'security')
        
        # 3. IPs sospechosas (muchos requests en poco tiempo)
        suspicious_ips = find_suspicious_activity(db, threshold=100, hours=1)
        for ip, count in suspicious_ips:
            if count > 200:  # Más de 200 requests en 1 hora
                add_notification('warning',
                    f'Actividad sospechosa desde IP {ip}: {count} requests/hora',
                    'fa-user-secret', 'security')
            elif count > 500:  # Más de 500 requests - crítico
                add_notification('error',
                    f'Actividad crítica desde IP {ip}: {count} requests/hora',
                    'fa-exclamation-triangle', 'security')
        
        db.close()
                
    except Exception as e:
        print(f"Error checking security events: {e}")

def check_user_activity():
    """Verifica actividad de usuarios desde la base de datos"""
    try:
        from database.database import get_session
        from services.auditoria_service import get_active_users_count, get_high_usage_users
        
        db = get_session()
        
        # 1. Usuarios activos en la última hora
        active_users = get_active_users_count(db, hours=1)
        
        if active_users > 50:
            add_notification('info',
                f'Alta actividad: {active_users} usuarios conectados en la última hora',
                'fa-users', 'users')
        
        elif active_users == 0:
            add_notification('warning',
                'No hay usuarios activos en la última hora',
                'fa-users', 'users')
        
        # 2. Usuarios con alto consumo de datos
        high_usage_users = get_high_usage_users(db, hours=24, threshold_mb=100)
        
        for user, usage_mb in high_usage_users[:3]:  # Top 3
            if usage_mb > 1000:  # Más de 1GB
                add_notification('warning',
                    f'Usuario {user} consumió {usage_mb:.0f}MB en 24h',
                    'fa-chart-line', 'users')
            elif usage_mb > 500:  # Más de 500MB
                add_notification('info',
                    f'Usuario {user} consumió {usage_mb:.0f}MB en 24h',
                    'fa-user', 'users')
        
        db.close()
                    
    except Exception as e:
        print(f"Error checking user activity: {e}")