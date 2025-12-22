import os
import platform
import re
import socket
import subprocess
import time

import psutil

# Variables globales para el cálculo de estadísticas de red
_last_net_io = None
_last_net_time = None


def get_network_info():
    ips = []
    try:
        net_info = psutil.net_if_addrs()
        for interface, addrs in net_info.items():
            if interface == "lo":
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ips.append(
                        {
                            "interface": interface,
                            "ip": addr.address,
                            "netmask": addr.netmask,
                            "version": "IPv4",
                        }
                    )
    except Exception as e:
        return f"Error: {str(e)}"

    return ips if ips else "Not available"


def get_os_info():
    try:
        with open("/etc/os-release") as f:
            os_data = {}
            for line in f:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    os_data[key] = value.strip('"')

        os_name = os_data.get(
            "PRETTY_NAME", os_data.get("NAME", os_data.get("ID", "Unknown Linux"))
        )

        return f"{os_name} ({platform.machine()})"
    except Exception:
        return f"{platform.system()} {platform.release()} ({platform.machine()})"


def get_uptime():
    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.readline().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            return f"{days}d {hours}h {minutes}m"
    except Exception as e:
        return f"Error getting uptime: {str(e)}"


def get_ram_info():
    try:
        ram = psutil.virtual_memory()
        return {
            "total": f"{ram.total / (1024**3):.2f} GB",
            "available": f"{ram.available / (1024**3):.2f} GB",
            "used": f"{ram.used / (1024**3):.2f} GB",
            "percent": f"{ram.percent}%",
        }
    except Exception as e:
        return f"Error: {str(e)}"


def get_swap_info():
    try:
        swap = psutil.swap_memory()
        if swap.total > 0:
            return {
                "total": f"{swap.total / (1024**3):.2f} GB",
                "used": f"{swap.used / (1024**3):.2f} GB",
                "free": f"{swap.free / (1024**3):.2f} GB",
                "percent": f"{swap.percent}%",
            }
        return "Not available"
    except Exception as e:
        return f"Error: {str(e)}"


def get_cpu_info():
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        try:
            cpu_freq = psutil.cpu_freq()
            freq_current = cpu_freq.current
            freq_min = cpu_freq.min
            freq_max = cpu_freq.max
        except Exception as e:
            freq_current = freq_min = freq_max = "N/A"
            print(f"Error getting CPU frequency info: {str(e)}")

        cpu_times = psutil.cpu_times_percent(interval=0.5, percpu=False)
        return {
            "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True),
            "usage": f"{cpu_percent}%",
            "current_freq": f"{freq_current} MHz"
            if isinstance(freq_current, int | float)
            else freq_current,
            "min_freq": f"{freq_min} MHz"
            if isinstance(freq_min, int | float)
            else freq_min,
            "max_freq": f"{freq_max} MHz"
            if isinstance(freq_max, int | float)
            else freq_max,
            "user_time": f"{cpu_times.user}%",
            "system_time": f"{cpu_times.system}%",
            "idle_time": f"{cpu_times.idle}%",
        }
    except Exception as e:
        return f"Error: {str(e)}"


r""" def get_squid_version():
    try:
        result = subprocess.run(
            ["squid", "-v"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout + result.stderr
        patterns = [
            r"Squid Cache: Version ([\d\.]+[\w\-\.]*)",
            r"Version: ([\d\.]+[\w\-\.]*)",
            r"squid/([\d\.]+[\w\-\.]*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(1)
        return "Installed (version not detected)"
    except FileNotFoundError:
        return "Not installed"
    except Exception as e:
        return f"Error: {str(e)}" """


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
        bytes_sent_per_sec = int(
            (current_net_io.bytes_sent - _last_net_io.bytes_sent) / time_diff
        )
        bytes_recv_per_sec = int(
            (current_net_io.bytes_recv - _last_net_io.bytes_recv) / time_diff
        )

        # Convertir a Mbps
        up_mbps = round((bytes_sent_per_sec * 8) / 1_000_000, 2)
        down_mbps = round((bytes_recv_per_sec * 8) / 1_000_000, 2)

        # Actualizar valores para la próxima medición
        _last_net_io = current_net_io
        _last_net_time = current_time

        return {
            "up_mbps": up_mbps,
            "down_mbps": down_mbps,
            "bytes_sent_per_sec": bytes_sent_per_sec,
            "bytes_recv_per_sec": bytes_recv_per_sec,
            "bytes_sent_total": current_net_io.bytes_sent,
            "bytes_recv_total": current_net_io.bytes_recv,
            "packets_sent": current_net_io.packets_sent,
            "packets_recv": current_net_io.packets_recv,
        }
    except Exception as e:
        return {
            "up_mbps": 0.0,
            "down_mbps": 0.0,
            "bytes_sent_per_sec": 0,
            "bytes_recv_per_sec": 0,
            "bytes_sent_total": 0,
            "bytes_recv_total": 0,
            "packets_sent": 0,
            "packets_recv": 0,
            "error": str(e),
        }


def get_timezone():
    try:
        if os.path.exists("/etc/timezone"):
            with open("/etc/timezone") as f:
                return f.read().strip()
        tz_path = os.path.realpath("/etc/localtime")
        if "zoneinfo" in tz_path:
            return tz_path.split("zoneinfo/")[-1]
        result = subprocess.run(["timedatectl"], stdout=subprocess.PIPE, text=True)
        match = re.search(r"Time zone: (\S+)\s+(\S+/\S+)", result.stdout)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return "Unknown"
    except Exception as e:
        return f"Error getting timezone: {str(e)}"


def get_system_type():
    # Check for Linux
    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        value = line.split("=", 1)[1].strip()
                        if (value.startswith('"') and value.endswith('"')) or (
                            value.startswith("'") and value.endswith("'")
                        ):
                            value = value[1:-1]
                        return value
        except Exception:
            pass

    # Check for macOS
    try:
        result = subprocess.run(
            ["sw_vers", "-productName"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            name = result.stdout.strip()
            result = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.strip()
            return f"{name} {version}"
    except Exception:
        pass

    # Check for Windows
    try:
        result = subprocess.run(
            'systeminfo | findstr /B /C:"OS Name" /B /C:"OS Version"',
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            os_name = ""
            os_version = ""
            for line in lines:
                if line.startswith("OS Name:"):
                    os_name = line.split(":", 1)[1].strip()
                elif line.startswith("OS Version:"):
                    os_version = line.split(":", 1)[1].strip()
            if os_name and os_version:
                return f"{os_name} {os_version}"
            elif os_name:
                return os_name
    except Exception:
        pass

    return "Unknown"
