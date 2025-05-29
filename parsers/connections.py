import re
from collections import defaultdict

# Precompilar todas las expresiones regulares para mejor rendimiento
REGEX_MAP = {
    "fd": re.compile(r"FD (\d+)"),
    "uri": re.compile(r"uri (.+)"),
    "username": re.compile(r"username (.+)"),
    "logType": re.compile(r"logType (.+)"),
    "start": re.compile(r"start ([\d.]+)"),
    "elapsed_time": re.compile(r"start .*?\(([\d.]+) seconds ago\)"),
    "remote": re.compile(r"remote: ([\d.]+:\d+)"),
    "local": re.compile(r"local: ([\d.]+:\d+)"),
    "fd_read": re.compile(r"read (\d+)"),
    "fd_wrote": re.compile(r"wrote (\d+)"),
    "nrequests": re.compile(r"nrequests: (\d+)"),
    "delay_pool": re.compile(r"delay_pool (\d+)")
}

def parse_raw_data(raw_data):
    """Analiza datos crudos de Squid y retorna conexiones estructuradas"""
    connections = []
    blocks = raw_data.split("Connection:")[1:]  # Ignorar el primer vacío
    
    for block in blocks:
        try:
            connection = parse_connection_block(block)
            connections.append(connection)
        except Exception as e:
            # Registrar error pero continuar procesando
            print(f"Error parsing block: {e}\n{block[:100]}...")
    
    return connections

def parse_connection_block(block):
    """Procesa un bloque individual de conexión"""
    conn = {}
    
    # Extraer campos simples
    for key, regex in REGEX_MAP.items():
        if key not in ["fd_read", "fd_wrote", "nrequests", "delay_pool", "fd_total"]:
            match = regex.search(block)
            conn[key] = match.group(1) if match else "N/A"
    
    # Manejar campos numéricos especiales
    conn["fd_read"] = int(REGEX_MAP["fd_read"].search(block).group(1)) if REGEX_MAP["fd_read"].search(block) else 0
    conn["fd_wrote"] = int(REGEX_MAP["fd_wrote"].search(block).group(1)) if REGEX_MAP["fd_wrote"].search(block) else 0
    conn["fd_total"] = conn["fd_read"] + conn["fd_wrote"]
    
    conn["nrequests"] = int(REGEX_MAP["nrequests"].search(block).group(1)) if REGEX_MAP["nrequests"].search(block) else 0
    conn["delay_pool"] = int(REGEX_MAP["delay_pool"].search(block).group(1)) if REGEX_MAP["delay_pool"].search(block) else "N/A"
    
    return conn

def group_by_user(connections):
    """Agrupa conexiones por usuario con conteo eficiente"""
    grouped = defaultdict(list)
    for connection in connections:
        user = connection["username"]
        # Filtrar usuarios inválidos directamente
        if user in (None, "", "-", "Anónimo"):
            user = "Anónimo"
        grouped[user].append(connection)
    
    return grouped