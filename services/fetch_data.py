import socket
from dotenv import load_dotenv
import os

load_dotenv()

SQUID_HOST = os.getenv("SQUID_HOST", "127.0.0.1")
SQUID_PORT = int(os.getenv("SQUID_PORT", "3128"))

def fetch_squid_data():
    try:
        with socket.create_connection((SQUID_HOST, SQUID_PORT), timeout=5) as s:
            request = f'GET cache_object://{SQUID_HOST}/active_requests HTTP/1.0\r\n\r\n'
            s.sendall(request.encode())
            response = b""
            while chunk := s.recv(4096):
                response += chunk
        return response.decode('utf-8')
    except Exception as e:
        return str(e)
