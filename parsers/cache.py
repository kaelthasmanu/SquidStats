import os
import re
import re as _re
import socket
import traceback

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

SQUID_HOST = os.getenv("SQUID_HOST", "127.0.0.1")
SQUID_PORT = int(os.getenv("SQUID_PORT", "3128"))


def fetch_squid_cache_stats():
    default_stats = {
        "store_entries": 0,
        "max_swap_size": 0,
        "current_swap_size": 0.0,
        "capacity_used": 0.0,
        "capacity_free": 100.0,
        "store_directory": "No disponible",
        "fs_block_size": 4096,
        "first_level_dirs": 0,
        "second_level_dirs": 0,
        "filemap_bits_used": 0,
        "filemap_bits_total": 0,
        "fs_space_used": 0,
        "fs_space_total": 0,
        "fs_inodes_used": 0,
        "fs_inodes_total": 0,
        "removal_policy": "lru",
        "lru_age_days": 0.0,
        "error": None,
        "connection_status": "connected",
    }
    try:
        requests_to_try = [
            (
                f"GET /squid-internal-mgr/storedir HTTP/1.1\r\n"
                f"Host: {SQUID_HOST}:{SQUID_PORT}\r\n"
                "Connection: close\r\n\r\n"
            ),
            f"GET cache_object://{SQUID_HOST}/storedir HTTP/1.0\r\n\r\n",
            (
                f"GET cache_object://{SQUID_HOST}/storedir HTTP/1.1\r\n"
                f"Host: {SQUID_HOST}\r\n"
                "Connection: close\r\n\r\n"
            ),
            (
                f"GET /storedir HTTP/1.1\r\n"
                f"Host: {SQUID_HOST}\r\n"
                "Connection: close\r\n\r\n"
            ),
            "GET cache_object://localhost/storedir HTTP/1.0\r\n\r\n",
            ("GET cache_object://127.0.0.1/storedir HTTP/1.0\r\n\r\n"),
            "GET mgr:storedir HTTP/1.0\r\n\r\n",
            (
                "GET mgr:storedir HTTP/1.1\r\n"
                f"Host: {SQUID_HOST}\r\n"
                "Connection: close\r\n\r\n"
            ),
        ]

        response = b""
        last_status = None
        for idx, request in enumerate(requests_to_try):
            try:
                with socket.create_connection((SQUID_HOST, SQUID_PORT), timeout=5) as s:
                    s.sendall(request.encode())
                    response = b""
                    while chunk := s.recv(4096):
                        response += chunk
            except Exception:
                tb = traceback.format_exc()
                print(
                    f"[cache_debug] Connection attempt {idx + 1} failed:\n{tb}",
                    flush=True,
                )
                response = b""
                continue

            if not response:
                continue

            try:
                parts = _re.split(rb"\r\n\r\n|\n\n", response, maxsplit=1)
                headers_bytes = parts[0]
                body_bytes = parts[1] if len(parts) > 1 else b""

                headers_text = headers_bytes.decode("utf-8", errors="replace")
                first_line = (
                    headers_text.splitlines()[0] if headers_text.splitlines() else ""
                )

                headers_lines = headers_text.splitlines()[1:]
                headers_dict = {}
                for line in headers_lines:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        headers_dict[k.strip().lower()] = v.strip()

                def _dechunk(b: bytes) -> bytes:
                    out = bytearray()
                    i = 0
                    L = len(b)
                    while i < L:
                        j = b.find(b"\r\n", i)
                        if j == -1:
                            break
                        line = b[i:j].strip()
                        try:
                            size = int(line.split(b";", 1)[0], 16)
                        except Exception:
                            break
                        i = j + 2
                        if size == 0:
                            # fin de chunks
                            break
                        chunk = b[i : i + size]
                        out.extend(chunk)
                        i = i + size
                        if b[i : i + 2] == b"\r\n":
                            i += 2
                        else:
                            break
                    return bytes(out)

                if (
                    "transfer-encoding" in headers_dict
                    and "chunked" in headers_dict.get("transfer-encoding", "")
                ):
                    try:
                        body_clean = _dechunk(body_bytes)
                        data = body_clean.decode("utf-8", errors="replace")
                    except Exception:
                        data = body_bytes.decode("utf-8", errors="replace")
                else:
                    data = body_bytes.decode("utf-8", errors="replace")
                http_status = None
                try:
                    parts_status = first_line.split()
                    if len(parts_status) >= 2 and parts_status[1].isdigit():
                        http_status = int(parts_status[1])
                except Exception:
                    http_status = None

                if (
                    http_status == 400
                    or " 400 " in first_line
                    or "400 Bad" in first_line
                ):
                    last_status = 400
                    continue
                else:
                    # éxito o otro código; usaremos esta respuesta
                    last_status = http_status or 200
                    default_stats["http_status"] = last_status
                    default_stats["raw_response"] = response.decode(
                        "utf-8", errors="replace"
                    )
                    break
            except Exception:
                tb = traceback.format_exc()
                print(
                    f"[cache_debug] Error decoding response on attempt {idx + 1}:\n{tb}",
                    flush=True,
                )
                response = b""
                continue

        # Si después de todos los intentos no tenemos datos, preparar error
        if not response:
            default_stats["error"] = (
                f"No response from {SQUID_HOST}:{SQUID_PORT} using tried request variants"
            )
            default_stats["connection_status"] = "no_response"
            return default_stats
        parsed_stats = parse_squid_cache_data(data)
        if parsed_stats and not parsed_stats.get("error"):
            default_stats.update(parsed_stats)
            default_stats["connection_status"] = "connected"
        else:
            # Si hubo error en el parsing, mantener defaults pero indicar el error
            default_stats["error"] = parsed_stats.get("error", "Error parsing data")
            default_stats["connection_status"] = "connected_but_parse_error"
        return default_stats
    except TimeoutError:
        default_stats["error"] = f"Timeout connecting to {SQUID_HOST}:{SQUID_PORT}"
        default_stats["connection_status"] = "timeout"
        return default_stats
    except ConnectionRefusedError:
        default_stats["error"] = f"Connection refused to {SQUID_HOST}:{SQUID_PORT}"
        default_stats["connection_status"] = "connection_refused"
        return default_stats
    except socket.gaierror as e:
        default_stats["error"] = f"DNS resolution error for {SQUID_HOST}: {str(e)}"
        default_stats["connection_status"] = "dns_error"
        return default_stats
    except UnicodeDecodeError:
        default_stats["error"] = "Error decoding response from Squid"
        default_stats["connection_status"] = "decode_error"
        return default_stats
    except Exception as e:
        default_stats["error"] = f"Unexpected error: {str(e)}"
        default_stats["connection_status"] = "unknown_error"
        return default_stats


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
            stats[key] = (
                match.group(1) if key != "current_swap_size" else float(match.group(1))
            )

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
    for key in [
        "store_entries",
        "max_swap_size",
        "fs_block_size",
        "first_level_dirs",
        "second_level_dirs",
        "filemap_bits_used",
        "filemap_bits_total",
        "fs_space_used",
        "fs_space_total",
        "fs_inodes_used",
        "fs_inodes_total",
    ]:
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
