import re
from collections import defaultdict

REGEX_MAP = {
    "fd": re.compile(r"FD (\d+)"),
    "uri": re.compile(r"uri (.+)"),
    "username": re.compile(r"username (.+)"),
    "logType": re.compile(r"logType (.+)"),
    "start": re.compile(r"start ([\d.]+)"),
    "elapsed_time": re.compile(r"start .*?\(([\d.]+) seconds ago\)"),
    "client_ip": re.compile(r"remote: ([\d.]+:\d+)"),
    "proxy_local_ip": re.compile(r"local: ([\d.]+:\d+)"),
    "fd_read": re.compile(r"read (\d+)"),
    "fd_wrote": re.compile(r"wrote (\d+)"),
    "nrequests": re.compile(r"nrequests: (\d+)"),
    "delay_pool": re.compile(r"delay_pool (\d+)"),
    "out_size": re.compile(r"out\.size (\d+)"),
}


def parse_raw_data(raw_data):
    connections = []
    blocks = raw_data.split("Connection:")[1:]

    for block in blocks:
        try:
            connection = parse_connection_block(block)
            connections.append(connection)
        except Exception as e:
            print(f"Error parseando bloque: {e}\n{block[:100]}...")

    return connections


def parse_connection_block(block):
    conn = {}

    for key, regex in REGEX_MAP.items():
        if key not in [
            "fd_read",
            "fd_wrote",
            "nrequests",
            "delay_pool",
            "fd_total",
            "out_size",
        ]:
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

    out_size_match = REGEX_MAP["out_size"].search(block)
    conn["out_size"] = int(out_size_match.group(1)) if out_size_match else 0

    elapsed_match = REGEX_MAP["elapsed_time"].search(block)
    elapsed_time = float(elapsed_match.group(1)) if elapsed_match else 0
    conn["elapsed_time"] = elapsed_time

    if conn["out_size"] > 0 and elapsed_time > 0:
        conn["bandwidth_bps"] = round((conn["out_size"] * 8) / elapsed_time, 2)
        conn["bandwidth_kbps"] = round(conn["bandwidth_bps"] / 1000, 2)
    else:
        conn["bandwidth_bps"] = 0
        conn["bandwidth_kbps"] = 0

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
        if not isinstance(user, str):
            user = str(user) if user is not None else ""
        user_normalized = user.strip().lower() if user else ""

        if user_normalized == "n/a":
            continue

        is_anonymous = not user_normalized or user_normalized in (
            indicator.lower()
            for indicator in ANONYMOUS_INDICATORS
            if indicator is not None
        )

        if not is_anonymous:
            key = user
            client_ip = connection.get("client_ip", "Not found")
        else:
            raw_ip = connection.get("client_ip", "Not found")
            ip_only = raw_ip.split(":")[0] if ":" in raw_ip else raw_ip
            key = ip_only
            client_ip = ip_only

        if not grouped[key]["connections"]:
            grouped[key]["client_ip"] = client_ip
        grouped[key]["connections"].append(connection)

    return dict(grouped)
