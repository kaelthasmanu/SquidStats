import os
import re

from loguru import logger

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(line):
    return ANSI_ESCAPE_RE.sub("", line)


def read_logs(log_files, max_lines, debug=False):
    """Read last `max_lines` from each file in `log_files`.

    Returns a dict mapping basename -> list-of-lines.
    """
    logs = {}
    for log_file in log_files:
        try:
            with open(log_file, errors="replace") as f:
                lines = f.readlines()
                cleaned = [
                    _strip_ansi(line.rstrip("\n")) for line in lines[-max_lines:]
                ]
                logs[os.path.basename(log_file)] = cleaned
        except FileNotFoundError:
            logs[os.path.basename(log_file)] = ["Log file not found"]
        except Exception as e:
            logger.exception("Error reading log file %s", log_file)
            if debug:
                logs[os.path.basename(log_file)] = [f"Error reading log: {str(e)}"]
            else:
                logs[os.path.basename(log_file)] = ["Error reading log"]

    return logs
