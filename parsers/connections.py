import re
from collections import defaultdict

REGEX_MAP = {
    "fd": re.compile(r"FD (\d+)"),
    "uri": re.compile(r"uri (.+)"),
    "username": re.compile(r"username (.+)"),
    "logType": re.compile(r"logType (.+)"),
    "start": re.compile(r"start ([\d.]+)"),
    "elapsed_time": re.compile(r"start .*?\(([\d.]+) seconds ago\)"),
    "client_ip": re.compile(r"remote: ([\d.]+:\d+)"),  # IP del cliente
    "proxy_local_ip": re.compile(r"local: ([\d.]+:\d+)"),  # IP del proxy
    "fd_read": re.compile(r"read (\d+)"),
    "fd_wrote": re.compile(r"wrote (\d+)"),
    "nrequests": re.compile(r"nrequests: (\d+)"),
    "delay_pool": re.compile(r"delay_pool (\d+)"),
}


def parse_raw_data(raw_data):
    connections = []
    blocks = raw_data.split("Connection:")[1:]

    for block in blocks:
        try:
            connection = parse_connection_block(block)
            connections.append(connection)
        except Exception as e:
            # Imprime un error pero permite que el script continúe
            print(f"Error parseando bloque: {e}\n{block[:100]}...")

    return connections


def parse_connection_block(block):
    conn = {}

    for key, regex in REGEX_MAP.items():
        if key not in ["fd_read", "fd_wrote", "nrequests", "delay_pool", "fd_total"]:
            match = regex.search(block)
            conn[key] = match.group(1) if match else "N/A"

    conn["fd_read"] = (
        int(REGEX_MAP["fd_read"].search(block).group(1))
        if REGEX_MAP["fd_read"].search(block)
        else 0
    )
    conn["fd_wrote"] = (
        int(REGEX_MAP["fd_wrote"].search(block).group(1))
        if REGEX_MAP["fd_wrote"].search(block)
        else 0
    )
    conn["fd_total"] = conn["fd_read"] + conn["fd_wrote"]

    conn["nrequests"] = (
        int(REGEX_MAP["nrequests"].search(block).group(1))
        if REGEX_MAP["nrequests"].search(block)
        else 0
    )
    conn["delay_pool"] = (
        int(REGEX_MAP["delay_pool"].search(block).group(1))
        if REGEX_MAP["delay_pool"].search(block)
        else "N/A"
    )
    return conn


def group_by_user(connections):
    ANONYMOUS_INDICATORS = {
        None,
        "",
        "-",
        "Anónimo",
        "N/A",
        "anonymous",
        "Anonymous",
        "unknown",
        "guest",
        "none",
        "null",
    }

    grouped = defaultdict(lambda: {"client_ip": "Not found", "connections": []})

    for connection in connections:
        user = connection.get("username")

        if user is None:
            continue
        if not isinstance(user, str):
            user = str(user)
        user_normalized = user.strip().lower()
        is_anonymous = not user_normalized or user_normalized in (
            indicator.lower()
            for indicator in ANONYMOUS_INDICATORS
            if indicator is not None
        )
        if is_anonymous:
            continue

        if not grouped[user]["connections"]:
            grouped[user]["client_ip"] = connection.get("client_ip", "Not found")

        grouped[user]["connections"].append(connection)

    return dict(grouped)
