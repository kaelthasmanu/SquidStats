from loguru import logger
from sqlalchemy import inspect

from config import Config
from database.database import get_engine, get_session
from services.database.admin_helpers import get_table_row_count, get_table_size


def get_tables_info():
    session = None
    try:
        engine = get_engine()
        inspector = inspect(engine)
        session = get_session()
        db_type = Config.DATABASE_TYPE

        tables = inspector.get_table_names()
        table_info = []

        for table_name in tables:
            try:
                rows = get_table_row_count(session, engine, table_name)
                size = get_table_size(session, db_type, table_name)

                table_info.append(
                    {
                        "name": table_name,
                        "rows": rows,
                        "size": size,
                        "has_data": rows > 0,
                    }
                )

            except Exception as e:
                logger.warning(f"Error processing table {table_name}: {e}")
                table_info.append(
                    {"name": table_name, "rows": 0, "size": 0, "has_data": False}
                )

        return {"status": "success", "tables": table_info}, 200

    except Exception:
        logger.exception("Error getting database tables")
        resp = {"status": "error", "message": "Error interno del servidor"}
        return resp, 500

    finally:
        if session:
            session.close()
