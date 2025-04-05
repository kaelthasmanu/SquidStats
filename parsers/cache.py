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
        "fs_space_used": r"Filesystem Space in use: (\d+)/\d+ KB",
        "fs_space_total": r"Filesystem Space in use: \d+/(\d+) KB",
        "fs_inodes_used": r"Filesystem Inodes in use: (\d+)/\d+",
        "fs_inodes_total": r"Filesystem Inodes in use: \d+/(\d+)",
        "removal_policy": r"Removal policy: (\w+)",
        "lru_age_days": r"LRU reference age: ([\d\.]+) days",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, data)
        if match:
            stats[key] = match.group(1) if key != "current_swap_size" else float(match.group(1))
    stats["fs_space_total"] = int(stats["fs_space_total"])
    stats["fs_space_used"] = int(stats["fs_space_used"])
    return stats