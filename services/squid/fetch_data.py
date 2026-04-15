import base64
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

from config import Config

from loguru import logger

load_dotenv()

SQUID_HOST = Config.SQUID_HOST
SQUID_PORT = Config.SQUID_PORT
SQUID_MGR_USER = os.getenv("SQUID_MGR_USER")
SQUID_MGR_PASS = os.getenv("SQUID_MGR_PASS")


def get_squid_hosts() -> list[tuple[str, int]]:
    """Return list of (host, port) for all configured Squid proxies.

    Uses SQUID_HOSTS (comma-separated host:port) when available, otherwise
    falls back to the single SQUID_HOST / SQUID_PORT.
    """
    if Config.SQUID_HOSTS:
        result = []
        for entry in Config.SQUID_HOSTS:
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                # handle IPv6 like [::1]:3128
                if entry.startswith("["):
                    bracket_end = entry.rfind("]")
                    host = entry[1:bracket_end]
                    port = (
                        int(entry[bracket_end + 2 :])
                        if bracket_end + 2 < len(entry)
                        else 3128
                    )
                else:
                    last_colon = entry.rfind(":")
                    host = entry[:last_colon]
                    port_str = entry[last_colon + 1 :]
                    try:
                        port = int(port_str)
                    except ValueError:
                        port = 3128
            else:
                host = entry
                port = 3128
            result.append((host, port))
        return result
    return [(SQUID_HOST, SQUID_PORT)]


def _format_host_header(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        # likely IPv6 literal
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


def _squid_error_response(host: str, port: int) -> str:
    logger.exception(f"Error fetching Squid data from {host}:{port}")
    return "error: unable to fetch squid data"


def fetch_squid_data():
    try:
        # Build HTTP/1.1 request similar to curl
        host_header = _format_host_header(SQUID_HOST, SQUID_PORT)
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

        path_request = (
            "GET /squid-internal-mgr/active_requests HTTP/1.1\r\n"
            + "\r\n".join(headers)
            + "\r\n\r\n"
        )
        response_text = _send_http_request(
            SQUID_HOST, SQUID_PORT, path_request, timeout=5.0
        )

        # If Squid returns 400 Bad Request, try legacy cache_object form
        first_line = response_text.splitlines()[0] if response_text else ""
        if " 400 " in first_line or "Bad Request" in response_text:
            legacy_request = (
                f"GET cache_object://{SQUID_HOST}/active_requests HTTP/1.0\r\n"
                f"Host: {host_header}\r\n"
                "User-Agent: SquidStats/1.0\r\n"
                "Accept: */*\r\n\r\n"
            )
            response_text = _send_http_request(
                SQUID_HOST, SQUID_PORT, legacy_request, timeout=5.0
            )

        return response_text
    except Exception:
        return _squid_error_response(SQUID_HOST, SQUID_PORT)


def fetch_squid_data_from_host(host: str, port: int) -> str:
    """Fetch active_requests from a specific Squid host:port."""
    try:
        host_header = _format_host_header(host, port)
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

        path_request = (
            "GET /squid-internal-mgr/active_requests HTTP/1.1\r\n"
            + "\r\n".join(headers)
            + "\r\n\r\n"
        )
        response_text = _send_http_request(host, port, path_request, timeout=5.0)

        first_line = response_text.splitlines()[0] if response_text else ""
        if " 400 " in first_line or "Bad Request" in response_text:
            legacy_request = (
                f"GET cache_object://{host}/active_requests HTTP/1.0\r\n"
                f"Host: {host_header}\r\n"
                "User-Agent: SquidStats/1.0\r\n"
                "Accept: */*\r\n\r\n"
            )
            response_text = _send_http_request(host, port, legacy_request, timeout=5.0)

        return response_text
    except Exception:
        return _squid_error_response(host, port)


def fetch_all_squid_data() -> list[dict]:
    """Fetch active_requests from all configured Squid proxies concurrently.

    Returns a list of dicts:
        {
          "host": str,
          "port": int,
          "label": str,   # "host:port"
          "data": str,    # raw response or error string
          "ok": bool,
        }
    """
    hosts = get_squid_hosts()

    results: list[dict] = []

    def _fetch(host: str, port: int) -> dict:
        label = f"{host}:{port}"
        raw = fetch_squid_data_from_host(host, port)
        ok = (
            bool(raw)
            and not raw.strip().lower().startswith("error")
            and not raw.strip().lower().startswith("[errno")
        )
        return {"host": host, "port": port, "label": label, "data": raw, "ok": ok}

    if len(hosts) == 1:
        results.append(_fetch(*hosts[0]))
    else:
        with ThreadPoolExecutor(max_workers=min(len(hosts), 10)) as executor:
            futures = {executor.submit(_fetch, h, p): (h, p) for h, p in hosts}
            for future in as_completed(futures):
                results.append(future.result())

    return results
