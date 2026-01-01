import base64
import os
import re
import socket
from datetime import datetime

from dotenv import load_dotenv

from config import Config

load_dotenv()

SQUID_HOST = Config.SQUID_HOST
SQUID_PORT = Config.SQUID_PORT
SQUID_MGR_USER = os.getenv("SQUID_MGR_USER")
SQUID_MGR_PASS = os.getenv("SQUID_MGR_PASS")

_SQUID_DATE_FMT = "%a, %d %b %Y %H:%M:%S %Z"


def _parse_squid_date(line: str) -> datetime:
    stamp = line.split(":", 1)[1].strip()
    return datetime.strptime(stamp, _SQUID_DATE_FMT)


def _re_float(key: str, text: str, default=0.0):
    m = re.search(rf"{re.escape(key)}\s*:\s*([0-9.]+)", text)
    return float(m.group(1)) if m else default


def _re_int(key: str, text: str, default=0):
    return int(_re_float(key, text, default))


def _format_host_header(host: str, port: int) -> str:
    # Bracket IPv6 literals
    if ":" in host and not host.startswith("["):
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _send_http_request(host: str, port: int, request: str, timeout: float = 5.0) -> str:
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(request.encode("utf-8"))
        response = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            response += chunk
    return response.decode("utf-8", errors="replace")


def fetch_squid_info_stats():
    default_stats = {
        "start_time": None,
        "current_time": None,
        "elapsed_hours": 0.0,
        "clients": 0,
        "requests_received": 0,
        "avg_requests_per_minute": 0.0,
        "median_service_times": {
            "http_requests_5m": 0.0,
            "http_requests_60m": 0.0,
            "cache_misses_5m": 0.0,
            "cache_misses_60m": 0.0,
            "cache_hits_5m": 0.0,
            "cache_hits_60m": 0.0,
            "near_hits_5m": 0.0,
            "near_hits_60m": 0.0,
            "not_modified_replies_5m": 0.0,
            "not_modified_replies_60m": 0.0,
            "dns_lookups_5m": 0.0,
            "dns_lookups_60m": 0.0,
            "icp_queries_5m": 0.0,
            "icp_queries_60m": 0.0,
        },
        "resource_usage": {
            "up_time_seconds": 0.0,
            "cpu_time_seconds": 0.0,
            "cpu_usage_percent": 0.0,
            "cpu_usage_5min": 0.0,
            "cpu_usage_60min": 0.0,
            "max_rss_kb": 0,
            "page_faults_io": 0,
        },
        "error": None,
        "connection_status": "connected",
    }

    try:
        host_header = _format_host_header(SQUID_HOST, int(SQUID_PORT))
        headers = [
            f"Host: {host_header}",
            "User-Agent: SquidStats/1.0",
            "Accept: */*",
            "Connection: close",
        ]
        if SQUID_MGR_USER and SQUID_MGR_PASS:
            token = base64.b64encode(
                f"{SQUID_MGR_USER}:{SQUID_MGR_PASS}".encode()
            ).decode()
            headers.append(f"Authorization: Basic {token}")

        modern_req = (
            "GET /squid-internal-mgr/info HTTP/1.1\r\n"
            + "\r\n".join(headers)
            + "\r\n\r\n"
        )
        response_text = _send_http_request(
            SQUID_HOST, int(SQUID_PORT), modern_req, timeout=5.0
        )

        first_line = response_text.splitlines()[0] if response_text else ""
        if " 400 " in first_line or "Bad Request" in response_text:
            legacy_req = (
                f"GET cache_object://{SQUID_HOST}/info HTTP/1.0\r\n"
                f"Host: {host_header}\r\n"
                "User-Agent: SquidStats/1.0\r\n"
                "Accept: */*\r\n\r\n"
            )
            response_text = _send_http_request(
                SQUID_HOST, int(SQUID_PORT), legacy_req, timeout=5.0
            )

        parts = response_text.split("\r\n\r\n", 1)
        data = parts[1] if len(parts) > 1 else response_text
    except Exception as e:
        default_stats["error"] = str(e)
        if isinstance(e, TimeoutError):
            default_stats["connection_status"] = "timeout"
        elif isinstance(e, ConnectionRefusedError):
            default_stats["connection_status"] = "connection_refused"
        elif isinstance(e, socket.gaierror):
            default_stats["connection_status"] = "dns_error"
        else:
            default_stats["connection_status"] = "unknown_error"
        return default_stats

    try:
        start_line = next(
            line for line in data.splitlines() if line.startswith("Start Time:")
        )
        current_line = next(
            line for line in data.splitlines() if line.startswith("Current Time:")
        )
        start_dt = _parse_squid_date(start_line)
        current_dt = _parse_squid_date(current_line)
        elapsed = current_dt - start_dt
        elapsed_hours = elapsed.total_seconds() / 3600

        clients = _re_int("Number of clients accessing cache", data)
        requests = _re_int("Number of HTTP requests received", data)
        avg_rpm = _re_float("Average HTTP requests per minute since start", data)

        m = re.search(r"HTTP Requests \(All\):\s+([\d.]+)\s+([\d.]+)", data)
        http_5m, http_60m = (float(x) for x in m.groups()) if m else (0, 0)

        m = re.search(r"Cache Misses:\s+([\d.]+)\s+([\d.]+)", data)
        miss_5m, miss_60m = (float(x) for x in m.groups()) if m else (0, 0)

        m = re.search(r"Cache Hits:\s+([\d.]+)\s+([\d.]+)", data)
        hit_5m, hit_60m = (float(x) for x in m.groups()) if m else (0, 0)

        m = re.search(r"Near Hits:\s+([\d.]+)\s+([\d.]+)", data)
        near_5m, near_60m = (float(x) for x in m.groups()) if m else (0, 0)

        m = re.search(r"Not-Modified Replies:\s+([\d.]+)\s+([\d.]+)", data)
        nmod_5m, nmod_60m = (float(x) for x in m.groups()) if m else (0, 0)

        m = re.search(r"DNS Lookups:\s+([\d.]+)\s+([\d.]+)", data)
        dns_5m, dns_60m = (float(x) for x in m.groups()) if m else (0, 0)

        m = re.search(r"ICP Queries:\s+([\d.]+)\s+([\d.]+)", data)
        icp_5m, icp_60m = (float(x) for x in m.groups()) if m else (0, 0)

        up_time = _re_float("UP Time", data)
        cpu_time = _re_float("CPU Time", data)
        cpu_use = _re_float("CPU Usage", data)
        cpu_5m = _re_float("CPU Usage, 5 minute avg", data)
        cpu_60m = _re_float("CPU Usage, 60 minute avg", data)
        max_rss = _re_int("Maximum Resident Size", data)
        page_faults = _re_int("Page faults with physical i/o", data)

        default_stats.update(
            {
                "start_time": start_dt,
                "current_time": current_dt,
                "elapsed_hours": round(elapsed_hours, 2),
                "clients": clients,
                "requests_received": requests,
                "avg_requests_per_minute": avg_rpm,
                "median_service_times": {
                    "http_requests_5m": http_5m,
                    "http_requests_60m": http_60m,
                    "cache_misses_5m": miss_5m,
                    "cache_misses_60m": miss_60m,
                    "cache_hits_5m": hit_5m,
                    "cache_hits_60m": hit_60m,
                    "near_hits_5m": near_5m,
                    "near_hits_60m": near_60m,
                    "not_modified_replies_5m": nmod_5m,
                    "not_modified_replies_60m": nmod_60m,
                    "dns_lookups_5m": dns_5m,
                    "dns_lookups_60m": dns_60m,
                    "icp_queries_5m": icp_5m,
                    "icp_queries_60m": icp_60m,
                },
                "resource_usage": {
                    "up_time_seconds": up_time,
                    "cpu_time_seconds": cpu_time,
                    "cpu_usage_percent": cpu_use,
                    "cpu_usage_5min": cpu_5m,
                    "cpu_usage_60min": cpu_60m,
                    "max_rss_kb": max_rss,
                    "page_faults_io": page_faults,
                },
            }
        )
        return default_stats

    except Exception as e:
        default_stats["error"] = f"Parsing error: {e}"
        default_stats["connection_status"] = "connected_but_parse_error"
        return default_stats
