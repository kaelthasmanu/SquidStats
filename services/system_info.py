import os
import socket
import platform
import subprocess
import re
import psutil
import asyncio
import time

def get_network_info():
    """Obtiene información de red usando psutil"""
    ips = []
    try:
        net_info = psutil.net_if_addrs()
        for interface, addrs in net_info.items():
            if interface == 'lo':
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ips.append({
                        'interface': interface,
                        'ip': addr.address,
                        'netmask': addr.netmask,
                        'version': 'IPv4'
                    })
    except Exception as e:
        return f"Error: {str(e)}"
    
    return ips if ips else "No disponible"

def get_os_info():
    """Obtiene información del sistema operativo de manera confiable"""
    try:
        with open('/etc/os-release') as f:
            os_data = {}
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    os_data[key] = value.strip('"')
        
        os_name = os_data.get('PRETTY_NAME', 
                     os_data.get('NAME', 
                     os_data.get('ID', 'Linux Desconocido')))
        
        return f"{os_name} ({platform.machine()})"
    except Exception:
        return f"{platform.system()} {platform.release()} ({platform.machine()})"

def get_uptime():
    """Obtiene tiempo de actividad del sistema"""
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            return f"{days}d {hours}h {minutes}m"
    except Exception as e:
        return f"Error al obtener el tiempo de actividad: {str(e)}"

def get_ram_info():
    """Obtiene información de memoria RAM usando psutil"""
    try:
        ram = psutil.virtual_memory()
        return {
            'total': f"{ram.total / (1024**3):.2f} GB",
            'available': f"{ram.available / (1024**3):.2f} GB",
            'used': f"{ram.used / (1024**3):.2f} GB",
            'percent': f"{ram.percent}%"
        }
    except Exception as e:
        return f"Error: {str(e)}"

def get_swap_info():
    """Obtiene información de memoria swap usando psutil"""
    try:
        swap = psutil.swap_memory()
        if swap.total > 0:
            return {
                'total': f"{swap.total / (1024**3):.2f} GB",
                'used': f"{swap.used / (1024**3):.2f} GB",
                'free': f"{swap.free / (1024**3):.2f} GB",
                'percent': f"{swap.percent}%"
            }
        return "No disponible"
    except Exception as e:
        return f"Error: {str(e)}"

def get_cpu_info():
    """Obtiene información de la CPU usando psutil"""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        try:
            cpu_freq = psutil.cpu_freq()
            freq_current = cpu_freq.current
            freq_min = cpu_freq.min
            freq_max = cpu_freq.max
        except Exception as e:
            freq_current = freq_min = freq_max = "N/A"
            print(f"Error al obtener información de frecuencia de CPU: {str(e)}")

        cpu_times = psutil.cpu_times_percent(interval=0.5, percpu=False)
        return {
            'physical_cores': psutil.cpu_count(logical=False),
            'total_cores': psutil.cpu_count(logical=True),
            'usage': f"{cpu_percent}%",
            'current_freq': f"{freq_current} MHz" if isinstance(freq_current, (int, float)) else freq_current,
            'min_freq': f"{freq_min} MHz" if isinstance(freq_min, (int, float)) else freq_min,
            'max_freq': f"{freq_max} MHz" if isinstance(freq_max, (int, float)) else freq_max,
            'user_time': f"{cpu_times.user}%",
            'system_time': f"{cpu_times.system}%",
            'idle_time': f"{cpu_times.idle}%"
        }
    except Exception as e:
        return f"Error: {str(e)}"

def get_squid_version():
    """Obtiene la versión de Squid de manera robusta"""
    try:
        result = subprocess.run(
            ['squid', '-v'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        output = result.stdout + result.stderr
        patterns = [
            r'Squid Cache: Version ([\d\.]+[\w\-\.]*)',
            r'Version: ([\d\.]+[\w\-\.]*)',
            r'squid/([\d\.]+[\w\-\.]*)'
        ]
        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(1)
        return "Instalado (versión no detectada)"
    except FileNotFoundError:
        return "No instalado"
    except Exception as e:
        return f"Error: {str(e)}"

# Variables globales para el cálculo de estadísticas de red
_last_net_io = None
_last_net_time = None

def get_network_stats():
    """Obtiene estadísticas de uso de red (ancho de banda)"""
    global _last_net_io, _last_net_time
    
    try:
        current_time = time.time()
        current_net_io = psutil.net_io_counters()
        
        # Si es la primera vez, inicializar y esperar 1 segundo
        if _last_net_io is None:
            _last_net_io = current_net_io
            _last_net_time = current_time
            time.sleep(1)
            current_time = time.time()
            current_net_io = psutil.net_io_counters()
        
        # Calcular tiempo transcurrido
        time_diff = current_time - _last_net_time
        
        # Calcular bytes por segundo
        bytes_sent_per_sec = int((current_net_io.bytes_sent - _last_net_io.bytes_sent) / time_diff)
        bytes_recv_per_sec = int((current_net_io.bytes_recv - _last_net_io.bytes_recv) / time_diff)
        
        # Convertir a Mbps
        up_mbps = round((bytes_sent_per_sec * 8) / 1_000_000, 2)
        down_mbps = round((bytes_recv_per_sec * 8) / 1_000_000, 2)
        
        # Actualizar valores para la próxima medición
        _last_net_io = current_net_io
        _last_net_time = current_time
        
        return {
            'up_mbps': up_mbps,
            'down_mbps': down_mbps,
            'bytes_sent_per_sec': bytes_sent_per_sec,
            'bytes_recv_per_sec': bytes_recv_per_sec,
            'bytes_sent_total': current_net_io.bytes_sent,
            'bytes_recv_total': current_net_io.bytes_recv,
            'packets_sent': current_net_io.packets_sent,
            'packets_recv': current_net_io.packets_recv
        }
    except Exception as e:
        return {
            'up_mbps': 0.0,
            'down_mbps': 0.0,
            'bytes_sent_per_sec': 0,
            'bytes_recv_per_sec': 0,
            'bytes_sent_total': 0,
            'bytes_recv_total': 0,
            'packets_sent': 0,
            'packets_recv': 0,
            'error': str(e)
        }

def get_timezone():
    """Obtiene la zona horaria del sistema"""
    try:
        if os.path.exists('/etc/timezone'):
            with open('/etc/timezone', 'r') as f:
                return f.read().strip()
        tz_path = os.path.realpath('/etc/localtime')
        if 'zoneinfo' in tz_path:
            return tz_path.split('zoneinfo/')[-1]
        result = subprocess.run(['timedatectl'], stdout=subprocess.PIPE, text=True)
        match = re.search(r'Time zone: (\S+)\s+(\S+/\S+)', result.stdout)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return "Desconocido"
    except Exception as e:
        return f"Error al obtener la zona horaria: {str(e)}"