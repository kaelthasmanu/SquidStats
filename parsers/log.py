import os
import re
import time
from datetime import datetime

from loguru import logger
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from database.database import (
    Base,
    DeniedLog,
    LogMetadata,
    get_dynamic_models,
    get_dynamic_table_names,
    get_engine,
    get_session,
    table_exists,
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
    r'^\S+\s+(?P<ip>\S+)\s+(?P<identity>\S+)\s+(?P<username>\S+)\s+'
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
                "data_transmitted": _bytes_transmitted(
                    quoted_match.group("bytes")
                ),
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
        logger.debug("Unable to parse space DETAILED line: {} ({})", line.strip(), error)
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
        logger.warning("Unable to detect log format; using per-line detection: {}", error)
        return FORMAT_AUTO


def process_logs(log_file):
    if not os.path.exists(log_file):
        logger.error(f"File not found: {log_file}")
        return
    engine = get_engine()
    user_table, log_table = get_dynamic_table_names()
    if not (table_exists(engine, user_table) and table_exists(engine, log_table)):
        logger.warning(
            f"User/log tables for date suffix '{datetime.now().strftime('%Y%m%d')}' do not exist. Attempting to recreate..."
        )
        try:
            Base.metadata.create_all(engine, checkfirst=True)
            logger.info("Tables created successfully.")
        except Exception as e:
            logger.error(f"Error creating dynamic tables: {e}")
            return
    try:
        current_inode = get_file_inode(log_file)
        file_size = os.path.getsize(log_file)
        date_suffix = datetime.now().strftime("%Y%m%d")
        DynamicUser, DynamicLog = get_dynamic_models(date_suffix)
        with DatabaseManager() as session:
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
            detected_format = detect_log_format(
                log_file, start_position=last_position
            )
            logger.info(
                "Detected Squid log format: {}",
                detected_format,
            )
            # logger.info(f"Reading from position: {last_position}")
            user_cache = {}
            logs_to_insert, new_users_to_insert, denied_to_insert = [], [], []
            processed_lines = inserted_logs = inserted_users = inserted_denied = 0
            start_time = time.time()

            def commit_batch():
                nonlocal inserted_logs, inserted_users, inserted_denied
                retry_count = 0
                user_table, log_table = get_dynamic_table_names()
                while retry_count < MAX_RETRIES:
                    try:
                        if new_users_to_insert:
                            session.bulk_save_objects(new_users_to_insert)
                            session.flush()
                            for user in new_users_to_insert:
                                user_cache[(user.username, user.ip)] = user.id
                            inserted_users += len(new_users_to_insert)
                            new_users_to_insert.clear()
                        if logs_to_insert:
                            session.bulk_insert_mappings(DynamicLog, logs_to_insert)
                            inserted_logs += len(logs_to_insert)
                            logs_to_insert.clear()
                        if denied_to_insert:
                            session.bulk_save_objects(denied_to_insert)
                            inserted_denied += len(denied_to_insert)
                            denied_to_insert.clear()
                        session.commit()
                        return True
                    except IntegrityError as e:
                        logger.warning(
                            f"Integrity error (retry {retry_count + 1}): {e}"
                        )
                        session.rollback()
                        retry_count += 1
                        if new_users_to_insert:
                            for user in new_users_to_insert:
                                key = (user.username, user.ip)
                                if key in user_cache:
                                    del user_cache[key]
                    except OperationalError as e:
                        if "database is locked" in str(e).lower():
                            retry_count += 1
                            logger.warning(
                                f"Database locked, retrying ({retry_count}/{MAX_RETRIES})..."
                            )
                            session.rollback()
                            time.sleep(0.5 * retry_count)
                        else:
                            logger.error(f"Database error: {e}")
                            session.rollback()
                            break
                    except SQLAlchemyError as e:
                        logger.error(f"Database error: {e}")
                        session.rollback()
                        break
                return False

            with open(log_file, encoding="utf-8", errors="replace") as f:
                f.seek(last_position)
                current_position = last_position
                for line in f:
                    processed_lines += 1
                    current_position += len(line.encode("utf-8"))
                    log_data = parse_log_line(line, format_hint=detected_format)
                    if not log_data:
                        continue
                    if log_data["is_denied"]:
                        denied_entry = DeniedLog(
                            username=log_data["username"],
                            ip=log_data["ip"],
                            url=log_data["url"],
                            method=log_data.get("method", ""),
                            status=log_data.get("status", ""),
                            response=log_data.get("response"),
                            data_transmitted=log_data.get("data_transmitted", 0),
                            created_at=datetime.now(),
                        )
                        denied_to_insert.append(denied_entry)
                        if len(denied_to_insert) >= BATCH_SIZE:
                            if commit_batch():
                                logger.info(
                                    f"Batch denied_logs inserted successfully. Records: {BATCH_SIZE}"
                                )
                            else:
                                logger.error(
                                    "Error committing denied batch. Continuing with next batch"
                                )
                        continue
                    user_key = (log_data["username"], log_data["ip"])
                    user_id = user_cache.get(user_key)
                    if user_id is None:
                        existing_user = (
                            session.query(DynamicUser)
                            .filter_by(username=log_data["username"], ip=log_data["ip"])
                            .first()
                        )
                        if existing_user:
                            user_id = existing_user.id
                            user_cache[user_key] = user_id
                        else:
                            new_user = DynamicUser(
                                username=log_data["username"], ip=log_data["ip"]
                            )
                            new_users_to_insert.append(new_user)
                            user_cache[user_key] = None
                            user_id = None
                    if user_id is None:
                        if not commit_batch():
                            logger.error(
                                "Critical error committing batch. Aborting batch"
                            )
                            continue
                        existing_user = (
                            session.query(DynamicUser)
                            .filter_by(username=log_data["username"], ip=log_data["ip"])
                            .first()
                        )
                        if existing_user:
                            user_id = existing_user.id
                            user_cache[user_key] = user_id
                        else:
                            logger.error(
                                f"Usuario no creado: {user_key}. Saltando línea"
                            )
                            continue
                    logs_to_insert.append(
                        {
                            "user_id": user_id,
                            "url": log_data["url"],
                            "response": log_data["response"],
                            "request_count": 1,
                            "data_transmitted": log_data["data_transmitted"],
                            "created_at": datetime.now(),
                        }
                    )
                    if len(logs_to_insert) >= BATCH_SIZE:
                        if not commit_batch():
                            logger.error(
                                "Error committing batch. Continuing with next batch"
                            )
            # Commit any remaining items that didn't fill a full batch
            if logs_to_insert or new_users_to_insert or denied_to_insert:
                if not commit_batch():
                    logger.error("Final commit_batch failed for remaining items")
            if not metadata:
                metadata = LogMetadata()
                session.add(metadata)
            metadata.last_position = current_position
            metadata.last_inode = current_inode
            # Align with LogMetadata model's column
            metadata.updated_at = datetime.now()
            session.commit()
            elapsed = time.time() - start_time
            # logger.info(f"Processing completed. Lines: {processed_lines}")
            logger.info(
                f"Logs inserted: {inserted_logs}, New users: {inserted_users}, Denied: {inserted_denied}"
            )
            logger.info(
                f"Time: {elapsed:.2f}s, Speed: {processed_lines / elapsed:.2f} lps"
            )
    except Exception as e:
        logger.critical(f"Critical error in process_logs: {e}", exc_info=True)
        raise
