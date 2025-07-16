import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc

from database.database import SystemMetrics, get_session

logger = logging.getLogger(__name__)


class MetricsService:
    @staticmethod
    def save_system_metrics(
        cpu_usage: str,
        ram_usage_bytes: int,
        swap_usage_bytes: int,
        net_sent_bytes_sec: int,
        net_recv_bytes_sec: int,
    ) -> bool:
        try:
            session = get_session()

            # Crear nueva métrica con timestamp local
            local_tz = datetime.now().astimezone().tzinfo
            metric = SystemMetrics(
                timestamp=datetime.now(local_tz),
                cpu_usage=cpu_usage,
                ram_usage_bytes=ram_usage_bytes,
                swap_usage_bytes=swap_usage_bytes,
                net_sent_bytes_sec=net_sent_bytes_sec,
                net_recv_bytes_sec=net_recv_bytes_sec,
            )

            session.add(metric)
            session.commit()
            session.close()

            # Limpiar métricas antiguas (más de 24 horas)
            MetricsService.cleanup_old_metrics()

            logger.info("Métricas del sistema guardadas correctamente")
            return True

        except Exception as e:
            logger.error(f"Error al guardar métricas del sistema: {e}")
            if session:
                session.rollback()
                session.close()
            return False

    @staticmethod
    def get_metrics_last_24_hours() -> list[dict[str, Any]]:
        try:
            session = get_session()

            # Calcular timestamp de 24 horas atrás con zona horaria local
            local_tz = datetime.now().astimezone().tzinfo
            twenty_four_hours_ago = datetime.now(local_tz) - timedelta(hours=24)

            # Consultar métricas de las últimas 24 horas
            metrics = (
                session.query(SystemMetrics)
                .filter(SystemMetrics.timestamp >= twenty_four_hours_ago)
                .order_by(SystemMetrics.timestamp)
                .all()
            )

            session.close()

            # Convertir a lista de diccionarios con timestamps en zona horaria local
            result = []
            for metric in metrics:
                # Asegurar que el timestamp tenga información de zona horaria
                if metric.timestamp.tzinfo is None:
                    # Si no tiene zona horaria, asumir que es local
                    local_timestamp = metric.timestamp.replace(tzinfo=local_tz)
                else:
                    local_timestamp = metric.timestamp

                result.append(
                    {
                        "id": metric.id,
                        "timestamp": local_timestamp.isoformat(),
                        "cpu_usage": metric.cpu_usage,
                        "ram_usage_bytes": metric.ram_usage_bytes,
                        "swap_usage_bytes": metric.swap_usage_bytes,
                        "net_sent_bytes_sec": metric.net_sent_bytes_sec,
                        "net_recv_bytes_sec": metric.net_recv_bytes_sec,
                    }
                )

            logger.info(f"Recuperadas {len(result)} métricas de las últimas 24 horas")
            return result

        except Exception as e:
            logger.error(f"Error al obtener métricas de las últimas 24 horas: {e}")
            if session:
                session.close()
            return []

    @staticmethod
    def get_metrics_today() -> list[dict[str, Any]]:
        try:
            session = get_session()

            # Obtener inicio del día actual con zona horaria local
            local_tz = datetime.now().astimezone().tzinfo
            today_start = datetime.now(local_tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            # Consultar métricas del día actual
            metrics = (
                session.query(SystemMetrics)
                .filter(SystemMetrics.timestamp >= today_start)
                .order_by(SystemMetrics.timestamp)
                .all()
            )

            session.close()

            # Convertir a lista de diccionarios con timestamps en zona horaria local
            result = []
            for metric in metrics:
                # Asegurar que el timestamp tenga información de zona horaria
                if metric.timestamp.tzinfo is None:
                    # Si no tiene zona horaria, asumir que es local
                    local_timestamp = metric.timestamp.replace(tzinfo=local_tz)
                else:
                    local_timestamp = metric.timestamp

                result.append(
                    {
                        "id": metric.id,
                        "timestamp": local_timestamp.isoformat(),
                        "cpu_usage": metric.cpu_usage,
                        "ram_usage_bytes": metric.ram_usage_bytes,
                        "swap_usage_bytes": metric.swap_usage_bytes,
                        "net_sent_bytes_sec": metric.net_sent_bytes_sec,
                        "net_recv_bytes_sec": metric.net_recv_bytes_sec,
                    }
                )

            logger.info(f"Recuperadas {len(result)} métricas del día actual")
            return result

        except Exception as e:
            logger.error(f"Error al obtener métricas del día actual: {e}")
            if session:
                session.close()
            return []

    @staticmethod
    def cleanup_old_metrics() -> bool:
        try:
            session = get_session()

            # Calcular timestamp de 24 horas atrás con zona horaria local
            local_tz = datetime.now().astimezone().tzinfo
            twenty_four_hours_ago = datetime.now(local_tz) - timedelta(hours=24)

            # Eliminar métricas antiguas
            deleted_count = (
                session.query(SystemMetrics)
                .filter(SystemMetrics.timestamp < twenty_four_hours_ago)
                .delete()
            )

            session.commit()
            session.close()

            if deleted_count > 0:
                logger.info(f"Eliminadas {deleted_count} métricas antiguas")

            return True

        except Exception as e:
            logger.error(f"Error al limpiar métricas antiguas: {e}")
            if session:
                session.rollback()
                session.close()
            return False

    @staticmethod
    def get_latest_metric() -> dict[str, Any] | None:
        try:
            session = get_session()

            # Obtener la métrica más reciente
            metric = (
                session.query(SystemMetrics)
                .order_by(desc(SystemMetrics.timestamp))
                .first()
            )

            session.close()

            if metric:
                # Asegurar que el timestamp tenga información de zona horaria
                local_tz = datetime.now().astimezone().tzinfo
                if metric.timestamp.tzinfo is None:
                    # Si no tiene zona horaria, asumir que es local
                    local_timestamp = metric.timestamp.replace(tzinfo=local_tz)
                else:
                    local_timestamp = metric.timestamp

                return {
                    "id": metric.id,
                    "timestamp": local_timestamp.isoformat(),
                    "cpu_usage": metric.cpu_usage,
                    "ram_usage_bytes": metric.ram_usage_bytes,
                    "swap_usage_bytes": metric.swap_usage_bytes,
                    "net_sent_bytes_sec": metric.net_sent_bytes_sec,
                    "net_recv_bytes_sec": metric.net_recv_bytes_sec,
                }

            return None

        except Exception as e:
            logger.error(f"Error al obtener la métrica más reciente: {e}")
            if session:
                session.close()
            return None
