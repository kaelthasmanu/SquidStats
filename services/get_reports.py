import datetime
from datetime import timedelta

from sqlalchemy import Column, Integer, String, desc, func, inspect
from sqlalchemy.orm import Session, relationship

from database.database import get_concat_function, get_dynamic_models


def get_important_metrics(db: Session, UserModel, LogModel):
    results = {}

    try:
        # 1. Usuarios más activos (por número de visitas)
        # Formato corregido: Paréntesis para continuar la consulta
        top_users_by_activity = (
            db.query(UserModel.username, func.count(LogModel.id).label("total_visits"))
            .join(LogModel, UserModel.id == LogModel.user_id)  # JOIN explícito
            .group_by(UserModel.username)
            .order_by(desc("total_visits"))
            .limit(20)
            .all()
        )

        results["top_users_by_activity"] = [
            {"username": user[0], "total_visits": user[1]}
            for user in top_users_by_activity
        ]

        # 2. Usuarios que más datos transfirieron
        top_users_by_data = (
            db.query(
                UserModel.username,
                func.sum(LogModel.data_transmitted).label("total_data"),
            )
            .join(LogModel, UserModel.id == LogModel.user_id)
            .group_by(UserModel.username)
            .order_by(desc("total_data"))
            .limit(20)
            .all()
        )

        results["top_users_by_data_transferred"] = [
            {"username": user[0], "total_data_bytes": user[1]}
            for user in top_users_by_data
        ]

        # 3. Páginas más visitadas
        top_pages = (
            db.query(
                LogModel.url,
                func.sum(LogModel.request_count).label("total_requests"),
                func.count(LogModel.id).label("unique_visits"),
                func.sum(LogModel.data_transmitted).label("total_data"),
            )
            .group_by(LogModel.url)
            .order_by(desc("total_requests"))
            .limit(20)
            .all()
        )

        results["top_pages"] = [
            {
                "url": page[0],
                "total_requests": page[1],
                "unique_visits": page[2],
                "total_data_bytes": page[3],
            }
            for page in top_pages
        ]

        # 4. Páginas por volumen de datos
        top_pages_data = (
            db.query(
                LogModel.url, func.sum(LogModel.data_transmitted).label("total_data")
            )
            .group_by(LogModel.url)
            .order_by(desc("total_data"))
            .limit(20)
            .all()
        )

        results["top_pages_by_data"] = [
            {"url": page[0], "total_data_bytes": page[1]} for page in top_pages_data
        ]

        # 5. Distribución de códigos HTTP
        response_distribution = (
            db.query(LogModel.response, func.count(LogModel.id).label("count"))
            .group_by(LogModel.response)
            .order_by(desc("count"))
            .all()
        )

        results["http_response_distribution"] = [
            {"response_code": resp[0], "count": resp[1]}
            for resp in response_distribution
        ]

        # 6. Usuarios por IP
        users_per_ip = (
            db.query(
                UserModel.ip,
                func.count(UserModel.id).label("user_count"),
                get_concat_function(UserModel.username).label("usernames"),
            )
            .group_by(UserModel.ip)
            .order_by(desc("user_count"))
            .filter(UserModel.ip is not None)
            .all()
        )

        results["users_per_ip"] = [
            {"ip": ip[0], "user_count": ip[1], "usernames": ip[2]}
            for ip in users_per_ip
            if ip[1] > 1
        ]

        # 7. Estadísticas globales
        total_stats = {
            "total_users": db.query(func.count(UserModel.id)).scalar() or 0,
            "total_log_entries": db.query(func.count(LogModel.id)).scalar() or 0,
            "total_data_transmitted": db.query(
                func.sum(LogModel.data_transmitted)
            ).scalar()
            or 0,
            "total_requests": db.query(func.sum(LogModel.request_count)).scalar() or 0,
        }

        results["total_stats"] = total_stats

        return results

    except Exception as e:
        # Log error but return empty structure
        print(f"Error in get_important_metrics: {str(e)}")
        return {}


def get_metrics_by_date_range(start_date: str, end_date: str, db: Session):
    try:
        # Convert string to datetime objects
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        raise ValueError("Dates must be in YYYYMMDD format")

    if end_dt < start_dt:
        raise ValueError("End date cannot be earlier than start date")

    # Preparar contenedores para resultados consolidados
    consolidated_results = {
        "top_users_by_activity": {},
        "top_users_by_data_transferred": {},
        "top_pages": {},
        "top_pages_by_data": {},
        "http_response_distribution": {},
        "users_per_ip": {},
        "total_stats": {
            "total_users": 0,
            "total_log_entries": 0,
            "total_data_transmitted": 0,
            "total_requests": 0,
        },
    }

    # Iterar por cada día en el rango
    current_dt = start_dt
    while current_dt <= end_dt:
        date_suffix = current_dt.strftime("%Y%m%d")
        try:
            # Obtener modelos dinámicos para esta fecha
            UserModel, LogModel = get_dynamic_models(date_suffix)

            # Verificar existencia de tablas
            if not has_table(db, UserModel.__tablename__) or not has_table(
                db, LogModel.__tablename__
            ):
                print(f"Tables not found for {date_suffix}, skipping...")
                current_dt += timedelta(days=1)
                continue

            # Obtener métricas para esta fecha
            daily_metrics = get_important_metrics(db, UserModel, LogModel)

            # Consolidar estadísticas totales
            if "total_stats" in daily_metrics:
                stats = daily_metrics["total_stats"]
                consolidated_results["total_stats"]["total_users"] += stats.get(
                    "total_users", 0
                )
                consolidated_results["total_stats"]["total_log_entries"] += stats.get(
                    "total_log_entries", 0
                )
                consolidated_results["total_stats"]["total_data_transmitted"] += (
                    stats.get("total_data_transmitted", 0)
                )
                consolidated_results["total_stats"]["total_requests"] += stats.get(
                    "total_requests", 0
                )

            # Lógica de consolidación para otras métricas iría aquí
            # ...

            current_dt += timedelta(days=1)
        except Exception as e:
            print(f"Error processing {date_suffix}: {str(e)}")
            current_dt += timedelta(days=1)

    return consolidated_results


def has_table(db: Session, table_name: str) -> bool:
    try:
        # Usar el inspector para verificar existencia de tabla
        inspector = inspect(db.get_bind())
        return inspector.has_table(table_name)
    except Exception as e:
        print(f"Error checking table {table_name}: {str(e)}")
        return False


def get_table_class(table_name: str, base) -> type:
    class_dict = {"__tablename__": table_name}

    # Modelo para tablas de usuarios
    if table_name.startswith("users_"):
        class_dict.update(
            {
                "id": Column(Integer, primary_key=True),
                "username": Column(String),
                "ip": Column(String),
                # Relación con logs para joins automáticos
                "logs": relationship(
                    "LogDynamic",
                    back_populates="user",
                    lazy="dynamic",  # Optimiza carga de relaciones
                ),
            }
        )
    # Modelo para tablas de logs
    elif table_name.startswith("logs_"):
        class_dict.update(
            {
                "id": Column(Integer, primary_key=True),
                "user_id": Column(Integer),
                "url": Column(String),
                "response": Column(Integer),
                "data_transmitted": Column(Integer),
                "request_count": Column(Integer),
                # Relación con usuario para joins automáticos
                "user": relationship(
                    "UserDynamic",
                    back_populates="logs",
                    lazy="joined",  # Carga inmediata para optimización
                ),
            }
        )

    return type(table_name, (base,), class_dict)
