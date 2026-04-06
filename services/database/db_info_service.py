from loguru import logger
from sqlalchemy import text

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


def get_db_health():
    """Return a health snapshot of the database.

    For SQLite, runs PRAGMA quick_check(1) on every call so corruption is
    detected automatically without the user having to click the integrity
    check button.  The query stops after the *first* error it finds, keeping
    latency acceptable even on large databases.
    """
    session = None
    try:
        engine = get_engine()
        session = get_session()
        db_type = Config.DATABASE_TYPE

        health = {
            "db_type": db_type,
            "table_count": 0,
            "total_rows": 0,
            "total_size_bytes": 0,
            "extra": {},
        }

        if db_type == "SQLITE":
            # ── Read header-level PRAGMAs first (safe on any DB state) ──
            page_size = session.execute(text("PRAGMA page_size")).scalar() or 0
            page_count = session.execute(text("PRAGMA page_count")).scalar() or 0
            freelist_count = (
                session.execute(text("PRAGMA freelist_count")).scalar() or 0
            )
            journal_mode = (
                session.execute(text("PRAGMA journal_mode")).scalar() or "unknown"
            )
            auto_vacuum_val = (
                session.execute(text("PRAGMA auto_vacuum")).scalar() or 0
            )
            _av = {0: "None", 1: "Full", 2: "Incremental"}
            fragmentation_pct = (
                round(freelist_count / page_count * 100, 2) if page_count else 0.0
            )

            health["total_size_bytes"] = page_size * page_count

            # ── Corruption probe: quick_check stops at the first bad page ──
            corruption = False
            corruption_detail = None
            try:
                qc_rows = session.execute(
                    text("PRAGMA quick_check(1)")
                ).fetchall()
                if not qc_rows or qc_rows[0][0] != "ok":
                    corruption = True
                    corruption_detail = (
                        qc_rows[0][0]
                        if qc_rows
                        else "Sin respuesta del PRAGMA"
                    )
            except Exception as qc_err:
                corruption = True
                corruption_detail = str(qc_err)

            health["extra"] = {
                "page_size": page_size,
                "page_count": page_count,
                "freelist_count": freelist_count,
                "journal_mode": journal_mode,
                "auto_vacuum": _av.get(auto_vacuum_val, str(auto_vacuum_val)),
                "fragmentation_pct": fragmentation_pct,
                "corruption": corruption,
                "corruption_detail": corruption_detail,
            }

            # ── Table stats (may fail on severely corrupted DBs) ──
            try:
                stats = get_all_tables_stats(session, engine, db_type)
                health["table_count"] = len(stats)
                health["total_rows"] = sum(v["rows"] for v in stats.values())
            except Exception:
                logger.warning(
                    "Could not read SQLite table stats — database may be corrupted"
                )

        elif db_type in ("MYSQL", "MARIADB"):
            stats = get_all_tables_stats(session, engine, db_type)
            health["table_count"] = len(stats)
            health["total_rows"] = sum(v["rows"] for v in stats.values())
            size = (
                session.execute(
                    text(
                        "SELECT COALESCE(SUM(data_length + index_length), 0)"
                        " FROM information_schema.tables WHERE table_schema = DATABASE()"
                    )
                ).scalar()
                or 0
            )
            version = session.execute(text("SELECT VERSION()")).scalar() or "unknown"
            health["total_size_bytes"] = int(size)
            health["extra"] = {"version": version}

        elif db_type in ("POSTGRES", "POSTGRESQL"):
            stats = get_all_tables_stats(session, engine, db_type)
            health["table_count"] = len(stats)
            health["total_rows"] = sum(v["rows"] for v in stats.values())
            size = (
                session.execute(
                    text("SELECT pg_database_size(current_database())")
                ).scalar()
                or 0
            )
            version = (
                session.execute(text("SELECT version()")).scalar() or "unknown"
            )
            health["total_size_bytes"] = int(size)
            health["extra"] = {"version": " ".join(version.split()[:2])}

        return {"status": "success", "health": health}, 200

    except Exception:
        logger.exception("Error getting DB health")
        return {"status": "error", "message": "Error interno del servidor"}, 500

    finally:
        if session:
            session.close()


def run_integrity_check():
    """Run a quick integrity check. Uses PRAGMA quick_check for SQLite."""
    session = None
    try:
        session = get_session()
        db_type = Config.DATABASE_TYPE

        errors = []

        if db_type == "SQLITE":
            rows = session.execute(text("PRAGMA quick_check")).fetchall()
            errors = [r[0] for r in rows if r[0] != "ok"]

        elif db_type in ("MYSQL", "MARIADB"):
            tables = session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
                )
            ).fetchall()
            for (t,) in tables:
                rows = session.execute(text(f"CHECK TABLE `{t}` FAST QUICK")).fetchall()
                for row in rows:
                    if row[3] not in ("OK", "note"):
                        errors.append(f"{t}: {row[3]}")

        else:
            session.execute(text("SELECT 1"))

        return {
            "status": "success",
            "integrity": {
                "ok": not errors,
                "errors": errors[:10],
                "error_count": len(errors),
            },
        }, 200

    except Exception:
        logger.exception("Error running integrity check")
        return {"status": "error", "message": "Error al ejecutar la verificación"}, 500

    finally:
        if session:
            session.close()
