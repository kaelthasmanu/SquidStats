import os
import re
import time
from collections import defaultdict
from datetime import datetime
from math import isfinite

from loguru import logger
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from database.database import (
    DeniedLog,
    LogMetadata,
    get_dynamic_models,
    get_dynamic_table_names,
    get_engine,
    get_session,
)


class DatabaseManager:
    def __init__(self, engine=None, session=None):
        self.engine = engine if engine else get_engine()
        self.session = session if session else get_session()

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.session.commit()
                logger.info("Commit successful")
            else:
                self.session.rollback()
                logger.error(f"Rollback due to error: {exc_val}")
        except SQLAlchemyError as e:
            logger.error(f"Error during commit/rollback: {e}")
            self.session.rollback()
        finally:
            self.session.close()


# Constants for fields and batch
BATCH_SIZE = 500
MAX_RETRIES = 3

# Supported Squid access-log families.  Detection is automatic; these names
# are also used as parser hints after sampling a file.
FORMAT_AUTO = "AUTO"
FORMAT_DEFAULT = "DEFAULT"
FORMAT_DETAILED = "DETAILED"

HTTP_METHODS = frozenset(
    {
        "CONNECT",
        "DELETE",
        "GET",
        "HEAD",
        "OPTIONS",
        "PATCH",
        "POST",
        "PUT",
        "TRACE",
        "NONE",
    }
)

DETAILED_REQUEST_RE = re.compile(
    r"^\S+\s+(?P<ip>\S+)\s+(?P<identity>\S+)\s+(?P<username>\S+)\s+"
    r"\[[^\]]*\]\s+"
    r'"(?P<method>\S+)\s+(?P<url>.*?)\s+HTTP/(?P<http_version>[^"]+)"\s+'
    r"(?P<status>\S+)\s+(?P<bytes>\S+)(?:\s+.*)?$"
)


def find_last_parent_proxy(log_file: str, lines_to_check: int = 5000) -> str | None:
    if not os.path.exists(log_file):
        return None

    try:
        with open(log_file, "rb") as f:
            f.seek(0, os.SEEK_END)
            end_pos = f.tell()
            line_count = 0
            while line_count < lines_to_check + 1 and f.tell() > 0:
                try:
                    f.seek(-1, os.SEEK_CUR)
                    char = f.read(1)
                    if char == b"\n":
                        line_count += 1
                    f.seek(-1, os.SEEK_CUR)
                except OSError:
                    f.seek(0)
                    break

            last_lines_raw = f.read(end_pos - f.tell())

        last_lines = (
            last_lines_raw.decode("utf-8", errors="replace").strip().splitlines()
        )

        for line in reversed(last_lines):
            log_data = parse_log_line(line)
            if log_data and log_data.get("parent_ip"):
                return log_data["parent_ip"]

    except Exception as e:
        logger.error(f"Error reading last lines of log: {e}", exc_info=False)

    return None


def get_table_names():
    today = datetime.now().strftime("%Y%m%d")
    return f"user_{today}", f"log_{today}", "log_metadata"


def get_file_inode(filepath):
    try:
        return os.stat(filepath).st_ino
    except FileNotFoundError:
        logger.error(f"File not found: {filepath}")
        raise
    except Exception as e:
        logger.error(f"Error accessing file: {e}")
        raise


def get_log_datetime(line: str) -> datetime | None:
    """Return the timestamp stored in a Squid access-log line.

    All access-log formats supported by this parser put the Unix timestamp in
    the first field.  Keeping this separate from the parsed payload lets us
    preserve the parser's public response shape while still routing imported
    entries to the correct daily table.
    """
    if not isinstance(line, str) or not line.strip():
        return None

    try:
        timestamp_token = line.lstrip("\ufeff").split(None, 1)[0]
        timestamp = float(timestamp_token.split("|", 1)[0])
        if not isfinite(timestamp) or timestamp < 0:
            return None
        return datetime.fromtimestamp(timestamp)
    except (IndexError, TypeError, ValueError, OSError, OverflowError):
        return None


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _is_integer(value: str) -> bool:
    return value.isdigit()


def _response_code(status: str) -> int:
    code = status.rsplit("/", 1)[-1]
    return int(code) if code.isdigit() else 0


def _bytes_transmitted(value: str) -> int:
    return int(value) if _is_integer(value) else 0


def _is_default_line(parts: list[str]) -> bool:
    """Recognize Squid's native access.log layout without parsing it twice."""
    return bool(
        len(parts) >= 7
        and _is_number(parts[0])
        and _is_number(parts[1])
        and "/" in parts[3]
        and _is_integer(parts[3].rsplit("/", 1)[-1])
        and (parts[4] == "-" or _is_integer(parts[4]))
        and parts[5].upper() in HTTP_METHODS
    )


def _is_pipe_line(line: str) -> bool:
    parts = line.strip().split("|")
    return bool(
        len(parts) >= 14
        and _is_number(parts[0])
        and _is_integer(parts[8])
        and _is_integer(parts[9])
        and parts[5].upper() in HTTP_METHODS
    )


def _is_space_detailed_line(parts: list[str]) -> bool:
    """Recognize the legacy whitespace-separated DETAILED layout."""
    return bool(
        len(parts) >= 11
        and _is_number(parts[0])
        and parts[5].upper() in HTTP_METHODS
        and _is_integer(parts[9])
        and _is_integer(parts[10])
    )


def _is_quoted_detailed_line(line: str):
    match = DETAILED_REQUEST_RE.match(line.strip())
    return bool(match and match.group("method").upper() in HTTP_METHODS)


def _detect_line_format(line: str) -> str | None:
    if not isinstance(line, str) or not line.strip():
        return None

    if _is_pipe_line(line):
        return FORMAT_DETAILED

    parts = line.split()
    if _is_default_line(parts):
        return FORMAT_DEFAULT

    if _is_quoted_detailed_line(line) or _is_space_detailed_line(parts):
        return FORMAT_DETAILED

    return None


def _ignore_log_line(line: str) -> bool:
    line_lower = line.lower()
    return (
        "cache_object://" in line_lower
        or "error:transaction-end-before-headers" in line_lower
        or "error:invalid-request" in line_lower
    )


def parse_log_line(line: str, format_hint: str = FORMAT_AUTO):
    """Parse one line using a detected format or safe per-line detection."""
    if not isinstance(line, str) or not line.strip():
        return None

    try:
        if _ignore_log_line(line):
            return None
    except Exception as error:
        logger.debug("Unexpected error pre-filtering log line: {}", error)
        return None

    normalized_hint = (format_hint or FORMAT_AUTO).upper()
    if normalized_hint == FORMAT_DEFAULT:
        return parse_log_line_default(line)
    if normalized_hint == FORMAT_DETAILED:
        return parse_log_line_detailed(line)

    detected_format = _detect_line_format(line)
    if detected_format == FORMAT_DEFAULT:
        return parse_log_line_default(line)
    if detected_format == FORMAT_DETAILED:
        return parse_log_line_detailed(line)
    return None


def parse_log_line_default(line: str):
    """Parse Squid's standard format.

    ``timestamp elapsed client_ip result/status bytes method url user
    hierarchy content-type``
    """
    try:
        if _ignore_log_line(line):
            return None
        parts = line.split()
        if not _is_default_line(parts):
            return None

        status = parts[3]
        ip = parts[2]
        user_field = parts[7] if len(parts) > 7 else "-"
        username = user_field if user_field != "-" else ip
        return {
            "ip": ip,
            "username": username if username != "-" else None,
            "url": parts[6],
            "response": _response_code(status),
            "data_transmitted": _bytes_transmitted(parts[4]),
            "method": parts[5].upper(),
            "status": status,
            "is_denied": "TCP_DENIED" in status,
        }
    except (IndexError, TypeError, ValueError) as error:
        logger.debug("Unable to parse DEFAULT log line: {} ({})", line.strip(), error)
        return None


def parse_log_line_detailed(line: str):
    """Parse the supported legacy DETAILED variants."""
    if _ignore_log_line(line):
        return None
    if _is_pipe_line(line):
        return parse_log_line_pipe_format(line)

    quoted_match = DETAILED_REQUEST_RE.match(line.strip())
    if quoted_match:
        try:
            identity = quoted_match.group("identity")
            username = quoted_match.group("username")
            ip = quoted_match.group("ip")
            if username == "-":
                username = identity if identity != "-" else ip
            if username == "-":
                username = None
            status = quoted_match.group("status")
            return {
                "ip": ip,
                "username": username,
                "url": quoted_match.group("url"),
                "response": _response_code(status),
                "data_transmitted": _bytes_transmitted(quoted_match.group("bytes")),
                "method": quoted_match.group("method").upper(),
                "status": status,
                "is_denied": "TCP_DENIED" in line,
            }
        except (IndexError, TypeError, ValueError) as error:
            logger.debug(
                "Unable to parse quoted DETAILED log line: {} ({})",
                line.strip(),
                error,
            )
            return None

    return parse_log_line_space_format(line)


def parse_log_line_pipe_format(line):
    parts = line.strip().split("|")
    if not _is_pipe_line(line):
        return None
    try:
        username = parts[3]
        if username == "-":
            return None
        return {
            "ip": parts[1],
            "username": username,
            "url": parts[6],
            "response": int(parts[8]),
            "data_transmitted": int(parts[9]),
            "method": parts[5].upper(),
            "status": parts[13],
            "is_denied": "TCP_DENIED" in parts[13],
        }
    except (IndexError, TypeError, ValueError) as error:
        logger.debug("Unable to parse pipe log line: {} ({})", line.strip(), error)
        return None


def parse_log_line_space_format(line):
    """Parse the legacy whitespace-separated DETAILED variant."""
    try:
        parts = line.split()
        if not _is_space_detailed_line(parts) or parts[3] == "-":
            return None
        status = parts[4]
        return {
            "ip": parts[1],
            "username": parts[3],
            "url": parts[6],
            "response": int(parts[9]),
            "data_transmitted": int(parts[10]),
            "method": parts[5].upper(),
            "status": status,
            "is_denied": "TCP_DENIED" in line,
        }
    except (IndexError, TypeError, ValueError) as error:
        logger.debug(
            "Unable to parse space DETAILED line: {} ({})", line.strip(), error
        )
        return None


def detect_log_format(log_file, sample_lines=32, start_position=0):
    """Detect DEFAULT or DETAILED by validating a small sample of lines."""
    try:
        with open(log_file, encoding="utf-8", errors="replace") as file:
            if start_position:
                file.seek(start_position)

            counts = {FORMAT_DEFAULT: 0, FORMAT_DETAILED: 0}
            for _ in range(sample_lines):
                line = file.readline()
                if not line:
                    break
                detected = _detect_line_format(line)
                if detected:
                    counts[detected] += 1

            # A tail containing only malformed/ignored lines should not force
            # a wrong format.  Retry from the beginning in that case.
            if not any(counts.values()) and start_position:
                file.seek(0)
                for _ in range(sample_lines):
                    line = file.readline()
                    if not line:
                        break
                    detected = _detect_line_format(line)
                    if detected:
                        counts[detected] += 1

            if not any(counts.values()):
                return FORMAT_AUTO

            if counts[FORMAT_DEFAULT] > counts[FORMAT_DETAILED]:
                return FORMAT_DEFAULT
            if counts[FORMAT_DETAILED] > counts[FORMAT_DEFAULT]:
                return FORMAT_DETAILED
            return FORMAT_AUTO
    except OSError as error:
        logger.warning(
            "Unable to detect log format; using per-line detection: {}", error
        )
        return FORMAT_AUTO


def _new_import_summary() -> dict:
    return {
        "processed_lines": 0,
        "parsed_lines": 0,
        "skipped_lines": 0,
        "inserted_logs": 0,
        "inserted_users": 0,
        "inserted_denied": 0,
        "dates": [],
    }


def _date_summary(date_summaries: dict, date_suffix: str) -> dict:
    if date_suffix not in date_summaries:
        user_table, log_table = get_dynamic_table_names(date_suffix)
        date_summaries[date_suffix] = {
            "date": date_suffix,
            "user_table": user_table,
            "log_table": log_table,
            "inserted_logs": 0,
            "inserted_users": 0,
            "inserted_denied": 0,
        }
    return date_summaries[date_suffix]


def _ingest_log_file(log_file, session, start_position: int = 0) -> tuple[dict, int]:
    """Ingest a log file into the daily tables selected by each line's date."""
    summary = _new_import_summary()
    date_summaries = {}
    models_by_date = {}
    user_cache = {}
    pending_users = defaultdict(list)
    pending_logs = defaultdict(list)
    pending_denied = []
    pending_stats = defaultdict(lambda: {"logs": 0, "users": 0, "denied": 0})
    start_time = time.time()

    detected_format = detect_log_format(log_file, start_position=start_position)
    logger.info("Detected Squid log format: {}", detected_format)

    def get_models(date_suffix):
        if date_suffix not in models_by_date:
            models = get_dynamic_models(date_suffix)
            if not models or not models[0] or not models[1]:
                raise RuntimeError(
                    f"Could not create daily tables for date suffix {date_suffix}"
                )
            models_by_date[date_suffix] = models
        return models_by_date[date_suffix]

    def commit_batch():
        if not pending_users and not pending_logs and not pending_denied:
            return

        for retry_count in range(MAX_RETRIES):
            try:
                for _date_suffix, users in pending_users.items():
                    if users:
                        session.add_all(users)
                session.flush()

                for date_suffix, entries in pending_logs.items():
                    if not entries:
                        continue
                    _, dynamic_log = get_models(date_suffix)
                    mappings = []
                    for user_ref, mapping in entries:
                        user_id = (
                            user_ref.id if not isinstance(user_ref, int) else user_ref
                        )
                        mappings.append({**mapping, "user_id": user_id})
                    session.bulk_insert_mappings(dynamic_log, mappings)

                if pending_denied:
                    session.add_all(pending_denied)
                session.commit()

                for date_suffix, users in pending_users.items():
                    count = len(users)
                    if count:
                        summary["inserted_users"] += count
                        _date_summary(date_summaries, date_suffix)[
                            "inserted_users"
                        ] += count
                for date_suffix, entries in pending_logs.items():
                    count = len(entries)
                    if count:
                        summary["inserted_logs"] += count
                        _date_summary(date_summaries, date_suffix)["inserted_logs"] += (
                            count
                        )
                for date_suffix, stats in pending_stats.items():
                    if stats["denied"]:
                        summary["inserted_denied"] += stats["denied"]
                        _date_summary(date_summaries, date_suffix)[
                            "inserted_denied"
                        ] += stats["denied"]

                pending_users.clear()
                pending_logs.clear()
                pending_denied.clear()
                pending_stats.clear()
                return
            except IntegrityError as error:
                session.rollback()
                logger.warning(
                    "Integrity error importing batch (retry {}/{}): {}",
                    retry_count + 1,
                    MAX_RETRIES,
                    error,
                )
            except OperationalError as error:
                session.rollback()
                if "database is locked" not in str(error).lower():
                    raise
                logger.warning(
                    "Database locked while importing; retrying ({}/{})",
                    retry_count + 1,
                    MAX_RETRIES,
                )
                time.sleep(0.5 * (retry_count + 1))
            except SQLAlchemyError:
                session.rollback()
                raise

        raise RuntimeError("Could not commit a log import batch")

    current_position = start_position
    with open(log_file, encoding="utf-8", errors="replace") as file:
        file.seek(start_position)
        for line in file:
            summary["processed_lines"] += 1
            current_position += len(line.encode("utf-8"))

            log_data = parse_log_line(line, format_hint=detected_format)
            log_datetime = get_log_datetime(line)
            if not log_data or log_datetime is None:
                summary["skipped_lines"] += 1
                continue

            summary["parsed_lines"] += 1
            date_suffix = log_datetime.strftime("%Y%m%d")
            DynamicUser, _ = get_models(date_suffix)
            date_stats = pending_stats[date_suffix]
            date_stats["denied"] += int(bool(log_data.get("is_denied")))

            # Some Squid formats use '-' for unauthenticated users.  The IP is
            # the stable fallback used by the DEFAULT parser as well.
            username = log_data.get("username") or log_data.get("ip") or "-"
            ip = log_data.get("ip") or "-"

            if log_data.get("is_denied"):
                pending_denied.append(
                    DeniedLog(
                        username=username,
                        ip=ip,
                        url=log_data.get("url") or "-",
                        method=log_data.get("method") or "",
                        status=log_data.get("status") or "",
                        response=log_data.get("response"),
                        data_transmitted=log_data.get("data_transmitted", 0),
                        created_at=log_datetime,
                    )
                )
            else:
                user_key = (date_suffix, username, ip)
                user_ref = user_cache.get(user_key)
                if user_ref is None:
                    existing_user = (
                        session.query(DynamicUser)
                        .filter_by(username=username, ip=ip)
                        .first()
                    )
                    if existing_user:
                        user_ref = existing_user.id
                    else:
                        user_ref = DynamicUser(
                            username=username,
                            ip=ip,
                            created_at=log_datetime,
                        )
                        pending_users[date_suffix].append(user_ref)
                        date_stats["users"] += 1
                    user_cache[user_key] = user_ref

                pending_logs[date_suffix].append(
                    (
                        user_ref,
                        {
                            "url": log_data.get("url") or "-",
                            "response": log_data.get("response", 0),
                            "request_count": 1,
                            "data_transmitted": log_data.get("data_transmitted", 0),
                            "created_at": log_datetime,
                        },
                    )
                )
                date_stats["logs"] += 1

            if (
                sum(len(items) for items in pending_logs.values())
                + sum(len(items) for items in pending_users.values())
                + len(pending_denied)
                >= BATCH_SIZE
            ):
                commit_batch()

    commit_batch()
    summary["dates"] = [date_summaries[key] for key in sorted(date_summaries)]
    elapsed = time.time() - start_time
    logger.info(
        "Logs inserted: {}, New users: {}, Denied: {} ({} lines in {:.2f}s)",
        summary["inserted_logs"],
        summary["inserted_users"],
        summary["inserted_denied"],
        summary["processed_lines"],
        elapsed,
    )
    return summary, current_position


def import_logs(log_file):
    """Import a complete log file, routing entries to their daily tables.

    Unlike :func:`process_logs`, this function intentionally does not read or
    update ``log_metadata``.  It is therefore safe for an administrator to
    import a rotated or historical file without changing the live tailer's
    cursor.
    """
    if not os.path.exists(log_file):
        raise FileNotFoundError(log_file)

    session = get_session()
    try:
        summary, _ = _ingest_log_file(log_file, session)
        if summary["parsed_lines"] == 0:
            raise ValueError("The log file contains no valid Squid access entries")
        return summary
    except Exception:
        session.rollback()
        logger.exception("Critical error importing log file")
        raise
    finally:
        session.close()


def process_logs(log_file):
    """Process only the new tail of the live log and update its cursor."""
    if not os.path.exists(log_file):
        logger.error(f"File not found: {log_file}")
        return _new_import_summary()

    current_inode = get_file_inode(log_file)
    file_size = os.path.getsize(log_file)
    session = get_session()
    try:
        metadata = session.query(LogMetadata).first()
        last_position = metadata.last_position if metadata else 0
        if metadata:
            if metadata.last_inode != current_inode:
                logger.info(
                    f"Inode changed: {metadata.last_inode} -> {current_inode}. Resetting position."
                )
                last_position = 0
            elif file_size < last_position:
                logger.warning(
                    f"File truncated (size: {file_size} < position: {last_position})"
                )
                last_position = 0

        summary, current_position = _ingest_log_file(
            log_file, session, start_position=last_position
        )
        if metadata is None:
            metadata = LogMetadata()
            session.add(metadata)
        metadata.last_position = current_position
        metadata.last_inode = current_inode
        metadata.updated_at = datetime.now()
        session.commit()
        return summary
    except Exception as error:
        session.rollback()
        logger.critical(f"Critical error in process_logs: {error}", exc_info=True)
        raise
    finally:
        session.close()
