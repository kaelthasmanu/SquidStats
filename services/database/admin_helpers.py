import os

from sqlalchemy import MetaData, Table, func, select, text


def load_env_vars():
    env_vars = {}
    env_file = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key] = value.strip('"')
    return env_vars


def save_env_vars(env_vars):
    env_file = os.path.join(os.getcwd(), ".env")
    with open(env_file, "w") as f:
        for key, value in env_vars.items():
            f.write(f'{key}="{value}"\n')


def get_table_row_count(session, engine, table_name):
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)

    return session.execute(select(func.count()).select_from(table)).scalar_one()


def get_table_size(session, db_type, table_name):
    if db_type == "SQLITE":
        result = session.execute(
            text("SELECT SUM(pgsize) FROM dbstat WHERE name = :name"),
            {"name": table_name},
        )
        return result.scalar() or 0

    if db_type in ("MYSQL", "MARIADB"):
        result = session.execute(
            text("""
                SELECT data_length + index_length
                FROM information_schema.tables
                WHERE table_name = :name
                AND table_schema = DATABASE()
            """),
            {"name": table_name},
        )
        return result.scalar() or 0

    if db_type in ("POSTGRES", "POSTGRESQL"):
        result = session.execute(
            text("SELECT pg_total_relation_size(:name)"),
            {"name": table_name},
        )
        return result.scalar() or 0

    return 0
