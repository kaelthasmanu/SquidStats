import sys
import re
from urllib.parse import quote

try:
    conn_str = sys.argv[1]

    if not conn_str.startswith('mysql+pymysql://'):
        raise ValueError('Esquema inválido. Debe comenzar con mysql+pymysql://')

    parts = conn_str.split('://', 1)[1].split('@', 1)
    if len(parts) != 2:
        raise ValueError('Formato incorrecto. Debe ser: usuario:clave@host:port/db')

    user_pass, host_port_db = parts
    if ':' not in user_pass:
        raise ValueError('Falta usuario o contraseña')

    user, password = user_pass.split(':', 1)

    encoded_pass = quote(password, safe='')

    if '/' not in host_port_db:
        raise ValueError('Falta nombre de la base de datos')

    host_port, db = host_port_db.split('/', 1)

    port_specified = ':' in host_port
    if port_specified:
        host, port = host_port.split(':', 1)
        if not port.isdigit():
            raise ValueError('Puerto debe ser numérico')
        port = int(port)
        if not (1 <= port <= 65535):
            raise ValueError(f'Puerto inválido: {port}')
    else:
        host = host_port
        port = 3306  # Valor por defecto

    encoded_conn = f'mysql+pymysql://{user}:{encoded_pass}@{host}'
    if port_specified:
        encoded_conn += f':{port}'
    encoded_conn += f'/{db}'

    print(encoded_conn)

except Exception as e:
    sys.exit(f'ERROR: {e}')