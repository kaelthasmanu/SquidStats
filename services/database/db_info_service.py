from loguru import logger

from config import Config
from database.database import get_engine, get_session
from services.database.admin_helpers import get_all_tables_stats


def get_tables_info():
    session = None
    try:
        engine = get_engine()
        session = get_session()
        db_type = Config.DATABASE_TYPE

        stats = get_all_tables_stats(session, engine, db_type)

        table_info = [
            {
                "name": table_name,
                "rows": info["rows"],
                "size": info["size"],
                "has_data": info["rows"] > 0,
            }
            for table_name, info in stats.items()
        ]

        return {"status": "success", "tables": table_info}, 200

    except Exception:
        logger.exception("Error getting database tables")
        return {"status": "error", "message": "Error interno del servidor"}, 500

    finally:
        if session:
            session.close()
