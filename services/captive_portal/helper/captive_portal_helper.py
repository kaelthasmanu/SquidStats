#!/usr/bin/env python3
"""Squid ``external_acl_type`` helper for the SquidStats captive portal.

Squid invokes this script and feeds it one client IP per line (``%SRC``) on
stdin; for each line this helper must print exactly one line to stdout:
``OK`` when the IP has an active, non-expired captive-portal session, or
``ERR`` otherwise. It intentionally has no other dependencies besides the
application's own database layer so it can be deployed as-is alongside the
Flask app.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")


def _check_ip(ip: str) -> bool:
    from services.captive_portal.session_service import get_active_session

    return get_active_session(ip) is not None


def main() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            print("ERR")
            sys.stdout.flush()
            continue

        ip = line.split()[0]
        try:
            ok = _check_ip(ip)
        except Exception:  # noqa: BLE001 - must always answer Squid
            print("ERR")
            sys.stdout.flush()
            continue

        print("OK" if ok else "ERR")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
