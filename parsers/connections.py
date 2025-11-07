import re
from collections import defaultdict

REGEX_MAP = {
    "fd": re.compile(r"FD (\d+)"),
    "uri": re.compile(r"uri (.+)"),
    "username": re.compile(r"username (.+)"),
    "logType": re.compile(r"logType (.+)"),
    "start": re.compile(r"start ([\d.]+)"),
    "elapsed_time": re.compile(r"start .*?\(([\d.]+) seconds ago\)"),
    "client_ip": re.compile(r"remote:\s+([\[\]a-fA-F0-9:\.]+:\d+)"),
    "proxy_local_ip": re.compile(r"local:\s+([\[\]a-fA-F0-9:\.]+:\d+)"),
    "fd_read": re.compile(r"read (\d+)"),
    "fd_wrote": re.compile(r"wrote (\d+)"),
    "nrequests": re.compile(r"nrequests: (\d+)"),
    "delay_pool": re.compile(r"delay_pool (\d+)"),
    "out_size": re.compile(r"out\.size (\d+)"),
    "squid_version": re.compile(r"Server:\s*squid/([^\s]+)"),
    "via_squid": re.compile(r"Via:.*\(squid/([^\)]+)\)"),
    "kid_open": re.compile(r"^\s*by\s+(kid\d+)\s*\{"),
    "kid_close": re.compile(r"^\s*\}\s+by\s+(kid\d+)\s*$"),
}


def parse_raw_data(raw_data: str):
    if not raw_data:
        return []

    first_idx = raw_data.find("Connection:")
    header = raw_data[:first_idx] if first_idx != -1 else raw_data
    body = raw_data[first_idx:] if first_idx != -1 else ""

    squid_version = "N/A"
    m = REGEX_MAP["squid_version"].search(header)
    if m:
        squid_version = m.group(1)
    else:
        vm = REGEX_MAP["via_squid"].search(header)
        if vm:
            squid_version = vm.group(1)

    connections = []
    current_kid = None
    current_block_lines = None

    lines = body.splitlines()
    for line in lines:
        if REGEX_MAP["kid_open"].match(line):
            current_kid = REGEX_MAP["kid_open"].match(line).group(1)
            continue
        if REGEX_MAP["kid_close"].match(line):
            current_kid = None
            continue

        if line.lstrip().startswith("Connection:"):
            if current_block_lines is not None:
                block_text = "\n".join(current_block_lines)
                try:
                    conn = parse_connection_block(
                        block_text, squid_version, kid=current_kid
                    )
                    connections.append(conn)
                except Exception as e:
                    print(f"Error parseando bloque: {e}\n{block_text[:120]}...")
            current_block_lines = [line]
        else:
            if current_block_lines is not None:
                current_block_lines.append(line)

    if current_block_lines is not None:
        block_text = "\n".join(current_block_lines)
        try:
            conn = parse_connection_block(block_text, squid_version, kid=current_kid)
            connections.append(conn)
        except Exception as e:
            print(f"Error parseando bloque: {e}\n{block_text[:120]}...")

    filtered = [
        c for c in connections
        if not (
            isinstance(c.get("uri"), str)
            and "squid-internal-mgr/active_requests" in c.get("uri")
        )
    ]

    return filtered


def parse_connection_block(block: str, squid_version: str, kid: str | None = None):
    conn: dict = {}

    for key, regex in REGEX_MAP.items():
        if key not in [
            "fd_read",
            "fd_wrote",
            "nrequests",
            "delay_pool",
            "fd_total",
            "out_size",
            "squid_version",
            "squid_host",
            "via_squid",
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

    conn["squid_version"] = squid_version
    if kid:
        conn["kid"] = kid

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
