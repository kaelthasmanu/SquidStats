from flask import Flask, render_template
import socket
import re
from collections import defaultdict

app = Flask(__name__, static_folder='./static')

SQUID_HOST = '127.0.0.1'
SQUID_PORT = 3128
CACHEMGR_PASSWORD = ''


def fetch_squid_data():
    """
    Conecta al servidor Squid y obtiene los datos en formato texto.
    """
    try:
        with socket.create_connection((SQUID_HOST, SQUID_PORT), timeout=10) as s:
            request = f'GET cache_object://{SQUID_HOST}/active_requests HTTP/1.0\r\n\r\n'
            s.sendall(request.encode())
            response = b""
            while chunk := s.recv(4096):
                response += chunk
        return response.decode('utf-8')
    except Exception as e:
        return str(e)


import re

def parse_raw_data(raw_data):
    """
    Analiza los datos crudos obtenidos de Squid y retorna una lista de conexiones detalladas.
    """
    connections = []
    connection_blocks = raw_data.split("Connection:")
    
    for block in connection_blocks[1:]:
        connection = {}

        connection["fd"] = re.search(r"FD (\d+)", block).group(1) if re.search(r"FD (\d+)", block) else "N/A"
        connection["uri"] = re.search(r"uri (.+)", block).group(1) if re.search(r"uri (.+)", block) else "N/A"
        connection["username"] = re.search(r"username (.+)", block).group(1) if re.search(r"username (.+)", block) else "Anónimo"
        connection["logType"] = re.search(r"logType (.+)", block).group(1) if re.search(r"logType (.+)", block) else "N/A"
        connection["start"] = re.search(r"start ([\d.]+)", block).group(1) if re.search(r"start ([\d.]+)", block) else "N/A"
        connection["elapsed_time"] = re.search(r"start .*?\(([\d.]+) seconds ago\)", block).group(1) if re.search(r"start .*?\(([\d.]+) seconds ago\)", block) else "N/A"
        connection["remote"] = re.search(r"remote: ([\d.]+:\d+)", block).group(1) if re.search(r"remote: ([\d.]+:\d+)", block) else "N/A"
        connection["local"] = re.search(r"local: ([\d.]+:\d+)", block).group(1) if re.search(r"local: ([\d.]+:\d+)", block) else "N/A"

        fd_read = re.search(r"read (\d+)", block)
        fd_wrote = re.search(r"wrote (\d+)", block)
        connection["fd_total"] = (
            int(fd_read.group(1)) + int(fd_wrote.group(1))
            if fd_read and fd_wrote
            else "N/A"
        )

        nrequests = re.search(r"nrequests: (\d+)", block)
        connection["nrequests"] = int(nrequests.group(1)) if nrequests else 0

        delay_pool = re.search(r"delay_pool (\d+)", block)
        connection["delay_pool"] = int(delay_pool.group(1)) if delay_pool else "N/A"

        connections.append(connection)

    return connections



def group_by_user(connections):
    """
    Agrupa las conexiones por usuarios.
    """
    grouped = defaultdict(list)
    for connection in connections:
        grouped[connection["username"]].append(connection)
    return grouped


@app.route('/')
def index():
    """
    Página principal que muestra las estadísticas de Squid agrupadas por usuarios.
    """
    raw_data = fetch_squid_data()
    if 'Error' in raw_data:
        return f"Error al conectar con Squid: {raw_data}"

    connections = parse_raw_data(raw_data)
    grouped_connections = group_by_user(connections)

    return render_template('index.html', grouped_connections=grouped_connections)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
