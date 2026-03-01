import re

from loguru import logger
from sqlalchemy import MetaData, Table, inspect

from database.database import get_engine


def delete_table_data(table_name: str):
    """Delete all rows from `table_name` after validation.

    Returns tuple `(response_dict, status_code)` ready to jsonify/return.
    """
    if not table_name:
        return {"status": "error", "message": "Nombre de tabla no proporcionado"}, 400

    if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
        return {"status": "error", "message": "Nombre de tabla inválido"}, 400

    if table_name in ("admin_users", "alembic_version"):
        return {
            "status": "error",
            "message": "No se puede eliminar estas tablas críticas",
        }, 400

    try:
        engine = get_engine()
        inspector = inspect(engine)

        if table_name not in inspector.get_table_names():
            return {"status": "error", "message": "La tabla no existe"}, 404

        metadata = MetaData()
        table = Table(table_name, metadata, autoload_with=engine)
        with engine.connect() as conn:
            conn.execute(table.delete())
            conn.commit()

        return {
            "status": "success",
            "message": "Datos de la tabla eliminados correctamente",
        }, 200

    except Exception:
        logger.exception("Error deleting data from table %s", table_name)
        return {"status": "error", "message": "Error interno del servidor"}, 500
