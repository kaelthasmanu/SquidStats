import logging
from datetime import datetime

from database.database import Metrics, get_session


def save_metrics_to_db(system_info, bytes_sent_sec, bytes_recv_sec, size_to_bytes):
    logger = logging.getLogger(__name__)
    try:
        db_session = get_session()
        new_metric = Metrics(
            timestamp=datetime.now(),
            cpu_usage=float(system_info["cpu"]["usage"].replace("%", "")),
            ram_usage_bytes=size_to_bytes(system_info["ram"]["used"]),
            swap_usage_bytes=size_to_bytes(system_info["swap"]["used"]),
            net_sent_bytes_sec=int(bytes_sent_sec),
            net_recv_bytes_sec=int(bytes_recv_sec),
        )
        db_session.add(new_metric)
        db_session.commit()
        db_session.close()
    except Exception as e:
        logger.error(f"Error al guardar métricas en la BD: {str(e)}")
