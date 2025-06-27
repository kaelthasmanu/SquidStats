import socket
import re
import os

SQUID_HOST = os.getenv("SQUID_HOST", "127.0.0.1")
SQUID_PORT = int(os.getenv("SQUID_PORT", "3128"))


def fetch_squid_cache_stats():
    try:
        with socket.create_connection((SQUID_HOST, SQUID_PORT), timeout=5) as s:
            request = f"GET cache_object://{SQUID_HOST}/storedir HTTP/1.0\r\n\r\n"
            s.sendall(request.encode())
            response = b""
            while chunk := s.recv(4096):
                response += chunk
        data = response.decode("utf-8")
        return parse_squid_cache_data(data)
    except Exception as e:
        return {"Error": str(e)}


def parse_squid_cache_data(data):
    stats = {}
    patterns = {
        "store_entries": r"Store Entries\s+: (\d+)",
        "max_swap_size": r"Maximum Swap Size\s+: (\d+) KB",
        "current_swap_size": r"Current Store Swap Size: ([\d\.]+) KB",
        "capacity_used": r"Current Capacity\s+: ([\d\.]+)% used",
        "capacity_free": r"Current Capacity\s+: [\d\.]+% used, ([\d\.]+)% free",
        "store_directory": r"Store Directory #\d+ \(.*\): (.+)",
        "fs_block_size": r"FS Block Size (\d+) Bytes",
        "first_level_dirs": r"First level subdirectories: (\d+)",
        "second_level_dirs": r"Second level subdirectories: (\d+)",
        "filemap_bits_used": r"Filemap bits in use: (\d+) of (\d+)",
        "filemap_bits_total": r"Filemap bits in use: \d+ of (\d+)",
        "fs_space_used": r"Filesystem Space in use: (\d+)/(\d+) KB",
        "fs_space_total": r"Filesystem Space in use: \d+/(\d+) KB",
        "fs_inodes_used": r"Filesystem Inodes in use: (\d+)/(\d+)",
        "fs_inodes_total": r"Filesystem Inodes in use: \d+/(\d+)",
        "removal_policy": r"Removal policy: (\w+)",
        "lru_age_days": r"LRU reference age: ([\d\.]+) days",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, data)
        if match:
            stats[key] = match.group(1) if key != "current_swap_size" else float(match.group(1))

    # Robustecer: asegurar que todas las claves esperadas existan, con valor 0 o None si no se encontraron
    defaults = {
        "store_entries": 0,
        "max_swap_size": 0,
        "current_swap_size": 0.0,
        "capacity_used": 0.0,
        "capacity_free": 0.0,
        "store_directory": None,
        "fs_block_size": 0,
        "first_level_dirs": 0,
        "second_level_dirs": 0,
        "filemap_bits_used": 0,
        "filemap_bits_total": 0,
        "fs_space_used": 0,
        "fs_space_total": 0,
        "fs_inodes_used": 0,
        "fs_inodes_total": 0,
        "removal_policy": None,
        "lru_age_days": 0.0,
    }
    for key, default in defaults.items():
        if key not in stats or stats[key] is None:
            stats[key] = default
    # Convertir a int/float según corresponda
    for key in ["store_entries", "max_swap_size", "fs_block_size", "first_level_dirs", "second_level_dirs", "filemap_bits_used", "filemap_bits_total", "fs_space_used", "fs_space_total", "fs_inodes_used", "fs_inodes_total"]:
        try:
            stats[key] = int(stats[key])
        except (ValueError, TypeError):
            stats[key] = 0
    for key in ["current_swap_size", "capacity_used", "capacity_free", "lru_age_days"]:
        try:
            stats[key] = float(stats[key])
        except (ValueError, TypeError):
            stats[key] = 0.0
    return stats