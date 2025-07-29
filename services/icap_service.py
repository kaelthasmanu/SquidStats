import os
import socket

from dotenv import load_dotenv

load_dotenv()

ICAP_HOST = os.getenv("ICAP_HOST", os.getenv("SQUID_HOST"))
ICAP_PORT = int(os.getenv("ICAP_PORT", 1344))


def fetch_cicap_stats(host="10.34.8.15", port=1344):
    http_req = "GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"

    # Construimos la solicitud ICAP completa
    icap_req = (
        f"REQMOD icap://{host}:{port}/info?view=text ICAP/1.0\r\n"
        f"Host: {host}\r\n"
        f"Allow: 204\r\n"
        f"Encapsulated: req-hdr=0, null-body={len(http_req)}\r\n"
        "\r\n"
        f"{http_req}"
    )

    try:
        with socket.create_connection((host, port), timeout=5) as s:
            s.sendall(icap_req.encode())
            resp = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
        return resp.decode("utf-8", errors="ignore")
    except Exception as e:
        return f"Error connecting to ICAP server: {e}"
