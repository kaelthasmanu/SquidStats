import base64
import os
import socket

from dotenv import load_dotenv

load_dotenv()

SQUID_HOST = os.getenv("SQUID_HOST", "127.0.0.1")
SQUID_PORT = int(os.getenv("SQUID_PORT", 3128))
SQUID_MGR_USER = os.getenv("SQUID_MGR_USER")
SQUID_MGR_PASS = os.getenv("SQUID_MGR_PASS")


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
    except Exception as e:
        return str(e)
