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


def get_all_tables_stats(session, engine, db_type):
    """
    Return {table_name: {"rows": int, "size": int}} for all tables using
    a minimal number of queries (1-2 total) instead of N*2 per-table queries.

    MySQL/MariaDB and PostgreSQL use the engine's internal statistics so the
    response is near-instant regardless of database size.  SQLite still needs
    one COUNT(*) per table but at least reuses a single reflected metadata
    object and batches the size query.
    """
    if db_type in ("MYSQL", "MARIADB"):
        result = session.execute(
            text("""
                SELECT table_name,
                       COALESCE(table_rows, 0),
                       COALESCE(data_length + index_length, 0)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_type = 'BASE TABLE'
            """)
        )
        return {row[0]: {"rows": int(row[1]), "size": int(row[2])} for row in result}

    if db_type in ("POSTGRES", "POSTGRESQL"):
        result = session.execute(
            text("""
                SELECT relname,
                       COALESCE(n_live_tup, 0),
                       pg_total_relation_size(relid)
                FROM pg_stat_user_tables
            """)
        )
        return {row[0]: {"rows": int(row[1]), "size": int(row[2])} for row in result}

    if db_type == "SQLITE":
        # Batch-fetch all table sizes in one query
        size_rows = session.execute(
            text("SELECT name, COALESCE(SUM(pgsize), 0) FROM dbstat GROUP BY name")
        ).fetchall()
        sizes = {row[0]: int(row[1]) for row in size_rows}

        # Reflect all tables once and run COUNT(*) per table
        metadata = MetaData()
        metadata.reflect(bind=engine)
        stats = {}
        for table_name, table_obj in metadata.tables.items():
            try:
                count = session.execute(
                    select(func.count()).select_from(table_obj)
                ).scalar_one()
            except Exception:
                count = 0
            stats[table_name] = {"rows": count, "size": sizes.get(table_name, 0)}
        return stats

    return {}
