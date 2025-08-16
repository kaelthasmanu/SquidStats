import logging
import os
import time
from datetime import datetime

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from config import Config
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("log_processor.log")],
)
logger = logging.getLogger(__name__)


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


# Constantes para campos y batch
BATCH_SIZE = 500
MAX_RETRIES = 3

# Modo de parseo de logs controlado por .env LOG_FORMAT: 'DETAILED' o 'DEFAULT'
LOG_FORMAT = getattr(Config, "LOG_FORMAT", "DETAILED").upper()


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


def parse_log_line(line):
    """Parse a log line based on configured LOG_FORMAT.

    - DETAILED: mantiene el comportamiento actual (pipe/space/autodetección clásica)
    - DEFAULT: usa un parser fijo del formato clásico de Squid
    """
    if LOG_FORMAT == "DEFAULT":
        return parse_log_line_default(line)

    # DETAILED (comportamiento actual)
    if "cache_object://" in line:
        return None
    if "|" in line:
        return parse_log_line_pipe_format(line)
    parts = line.split()
    # Formato clásico de Squid: timestamp elapsed ip code/status bytes method url rfc931 peerstatus/peerhost type
    if len(parts) >= 10 and (
        len(parts) > 5
        and parts[5]
        in (
            "CONNECT",
            "GET",
            "POST",
            "HEAD",
            "PUT",
            "DELETE",
            "OPTIONS",
            "TRACE",
            "PATCH",
        )
    ):
        try:
            return {
                "ip": parts[2],
                # Mantener comportamiento actual: si '-', dejar None
                "username": parts[2] if parts[2] != "-" else None,
                "url": parts[6],
                "response": int(parts[3].split("/")[-1])
                if "/" in parts[3] and parts[3].split("/")[-1].isdigit()
                else 0,
                "data_transmitted": int(parts[4]) if parts[4].isdigit() else 0,
                "method": parts[5],
                "status": parts[3],
                "is_denied": "TCP_DENIED" in parts[3],
            }
        except Exception as e:
            logger.error(f"Error parsing classic squid log line: {line.strip()} - {e}")
            return None
    # Si no es clásico, intenta el formato space
    return parse_log_line_space_format(line)


def parse_log_line_default(line: str):
    """Parser del formato por defecto de Squid (access.log nativo).

    Ejemplo:
    ts elapsed ip status bytes method url user hierarchy type
    1755283778.165 1 172.17.0.1 TCP_MISS/200 11185 GET http://... - HIER_NONE/- text/plain
    """
    try:
        parts = line.split()
        # Debe tener al menos: 10 campos; evitamos líneas internas de cache_object
        if len(parts) < 7:
            return None
        # Localiza URL (puede contener espacios sólo en casos raros, asumimos estándar)
        # En el formato típico, url está en parts[6]
        url = parts[6] if len(parts) > 6 else None
        if not url or "cache_object://" in url:
            return None

        ip = parts[2] if len(parts) > 2 else None
        status = parts[3] if len(parts) > 3 else ""
        bytes_str = parts[4] if len(parts) > 4 else "0"
        method = parts[5] if len(parts) > 5 else ""
        # Campo user suele ir en parts[7]; si es '-', usamos la IP como username
        user_field = parts[7] if len(parts) > 7 else "-"
        username = user_field if user_field != "-" else (ip or "-")

        response = 0
        if "/" in status:
            code = status.split("/")[-1]
            response = int(code) if code.isdigit() else 0

        data_transmitted = int(bytes_str) if bytes_str.isdigit() else 0

        return {
            "ip": ip,
            "username": username,
            "url": url,
            "response": response,
            "data_transmitted": data_transmitted,
            "method": method,
            "status": status,
            "is_denied": "TCP_DENIED" in status,
        }
    except Exception as e:
        logger.error(f"Error parsing DEFAULT format line: {line.strip()} - {e}")
        return None


def parse_log_line_pipe_format(line):
    parts = line.strip().split("|")
    if len(parts) < 14:
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
            "method": parts[5],
            "status": parts[13],
            "is_denied": "TCP_DENIED" in parts[13],
        }
    except Exception as e:
        logger.error(f"Error parsing line with pipe format: {line.strip()} - {e}")
        return None


def parse_log_line_space_format(line):
    try:
        parts = line.split()
        if len(parts) < 11 or parts[3] == "-":
            return None
        return {
            "ip": parts[1],
            "username": parts[3],
            "url": parts[7],
            "response": int(parts[9]) if parts[9].isdigit() else 0,
            "data_transmitted": int(parts[10]) if parts[10].isdigit() else 0,
            "method": parts[5] if len(parts) > 5 else "",
            "status": parts[6] if len(parts) > 6 else "",
            "is_denied": "TCP_DENIED" in line,
        }
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing line with space format: {line.strip()} - {e}")
        return None


def detect_log_format(log_file, sample_lines=10):
    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            pipe_count = 0
            space_count = 0

            for i, line in enumerate(f):
                if i >= sample_lines:
                    break

                if (
                    "|" in line and line.count("|") > 5
                ):  # Formato pipe típicamente tiene muchos |
                    pipe_count += 1
                elif (
                    len(line.split()) > 10
                ):  # Formato space típicamente tiene muchos campos
                    space_count += 1

            format_detected = "pipe" if pipe_count > space_count else "space"
            return format_detected

    except Exception as e:
        logger.warning(f"Error detecting format, using line detection: {e}")
        return "auto"  # Fallback a detección automática por línea


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
            logger.info(f"Reading from position: {last_position}")
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
                    log_data = parse_log_line(line)
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
            logger.info(f"Processing completed. Lines: {processed_lines}")
            logger.info(
                f"Logs inserted: {inserted_logs}, New users: {inserted_users}, Denied: {inserted_denied}"
            )
            logger.info(
                f"Time: {elapsed:.2f}s, Speed: {processed_lines / elapsed:.2f} lps"
            )
    except Exception as e:
        logger.critical(f"Critical error in process_logs: {e}", exc_info=True)
        raise
