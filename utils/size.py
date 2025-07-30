def size_to_bytes(size_str):
    if not size_str:
        return 0
    parts = size_str.strip().split()
    if len(parts) != 2:
        return 0
    value, unit = float(parts[0]), parts[1].upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }
    return int(value * multipliers.get(unit, 1))


def humanize_bytes(bytes_value):
    if not bytes_value or bytes_value == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(bytes_value)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"

    if size == int(size):
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.1f} {units[unit_index]}"
