import os
import sys
from pathlib import Path
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import inspect

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from database.database import get_session, LogMetadata, User, Log, Base, get_engine


class DatabaseManager:
    def __init__(self):
        self.engine = get_engine()
        self.session = get_session()
        self._verify_tables()

    def _verify_tables(self):
        inspector = inspect(self.engine)
        current_tables = inspector.get_table_names()
        required_tables = [LogMetadata.__tablename__] + list(get_table_names())

        missing_tables = [t for t in required_tables if t not in current_tables]
        if missing_tables:
            print(f"Creando tablas faltantes: {missing_tables}")
            Base.metadata.create_all(self.engine)

    def __enter__(self):
        self._verify_tables()
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()


def get_table_names():
    today = datetime.now().strftime("%Y%m%d")
    return f"users_{today}", f"logs_{today}", "log_metadata"


def get_file_inode(filepath):
    try:
        return os.stat(filepath).st_ino
    except FileNotFoundError:
        raise SystemExit(f"Error: Archivo {filepath} no encontrado")
    except Exception as e:
        raise SystemExit(f"Error accediendo al archivo: {str(e)}")


def parse_log_line(line):
    try:
        parts = line.split(" ")
        if "TCP_DENIED/HIER_NONE" not in parts[17]:
            ip = parts[1]
            username = parts[3]
            url = parts[7]
            response = parts[9]
            data = parts[10]

            return {
                'ip': ip,
                'username': username,
                'url': f"{url}",
                'response': int(response) if response.isdigit() else 0,
                'data_transmitted': int(data) if data.isdigit() else 0
            }
    except (IndexError, ValueError) as e:
        print(f"Error parseando línea: {str(e)}")
        return None


def process_logs(log_file):
    with DatabaseManager() as session:
        try:
            metadata = session.query(LogMetadata).first()
            current_inode = get_file_inode(log_file)
            last_position = 0

            if metadata:
                if metadata.last_inode != current_inode:
                    metadata.last_position = 0
                    session.commit()
                last_position = metadata.last_position

            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(last_position)

                batch_size = 100
                current_batch = []
                processed_lines = 0

                for line in f:
                    processed_lines += 1
                    log_data = parse_log_line(line)

                    if not log_data:
                        continue

                    try:
                        user = session.query(User).filter_by(
                            username=log_data['username']
                        ).first()

                        if not user:
                            user = User(
                                username=log_data['username'],
                                ip=log_data['ip']
                            )
                            session.add(user)
                            session.flush()

                        log_entry = session.query(Log).filter_by(
                            user_id=user.id,
                            url=log_data['url']
                        ).first()

                        if log_entry:
                            log_entry.request_count += 1
                            log_entry.data_transmitted += log_data['data_transmitted']
                        else:
                            new_log = Log(
                                user_id=user.id,
                                url=log_data['url'],
                                response=log_data['response'],
                                request_count=1,
                                data_transmitted=log_data['data_transmitted']
                            )
                            session.add(new_log)
                        if processed_lines % batch_size == 0:
                            session.commit()

                    except SQLAlchemyError as e:
                        session.rollback()
                        print(f"Error en línea: {str(e)}")
                        continue

                session.commit()
                new_position = f.tell()

                if metadata:
                    metadata.last_position = new_position
                    metadata.last_inode = current_inode
                else:
                    session.add(LogMetadata(
                        last_position=new_position,
                        last_inode=current_inode
                    ))
                session.commit()

                print(f"Procesamiento completo. Nueva posición: {new_position}")
                print(f"Total líneas procesadas: {processed_lines}")

        except Exception as e:
            session.rollback()
            print(f"Error crítico: {str(e)}")
            raise