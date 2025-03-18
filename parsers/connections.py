import re
from collections import defaultdict

def parse_raw_data(raw_data):
    """
    Parses raw data obtained from Squid and returns a detailed list of connections.
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
    Groups connections by users.
    """
    grouped = defaultdict(list)
    for connection in connections:
        grouped[connection["username"]].append(connection)
    return grouped
