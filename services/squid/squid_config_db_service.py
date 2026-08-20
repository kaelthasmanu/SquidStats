from database.database import get_session
from database.models.models import SquidConfig

SQUID_ENV_KEYS = {
    "SQUID_HOST",
    "SQUID_PORT",
    "SQUID_HOSTS",
    "SQUID_LOG",
    "SQUID_CACHE_LOG",
    "SQUID_CONFIG_PATH",
    "ACL_FILES_DIR",
}

SQUID_ENV_TO_DB_FIELD = {
    "SQUID_HOST": "squid_host",
    "SQUID_PORT": "squid_port",
    "SQUID_HOSTS": "squid_hosts",
    "SQUID_LOG": "squid_log",
    "SQUID_CACHE_LOG": "squid_cache_log",
    "SQUID_CONFIG_PATH": "squid_config_path",
    "ACL_FILES_DIR": "acl_files_dir",
}


def save_squid_env_vars_to_db(env_vars: dict[str, str]) -> None:
    """Save Squid-related environment variables into the squid_config DB row."""
    if not env_vars:
        return

    session = get_session()
    try:
        row = session.query(SquidConfig).first()
        if row is None:
            row = SquidConfig()
            session.add(row)

        changed = False
        for env_key, value in env_vars.items():
            if env_key not in SQUID_ENV_KEYS:
                continue

            db_field = SQUID_ENV_TO_DB_FIELD.get(env_key)
            if db_field is None:
                continue

            if env_key == "SQUID_PORT":
                try:
                    cast_value = int(value)
                except (TypeError, ValueError):
                    cast_value = 3128
                if getattr(row, db_field) != cast_value:
                    setattr(row, db_field, cast_value)
                    changed = True
            else:
                if getattr(row, db_field) != value:
                    setattr(row, db_field, value)
                    changed = True

        if changed:
            session.commit()
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def load_squid_config_from_db() -> dict[str, str]:
    """Load Squid-related configuration values from the squid_config DB row."""
    session = get_session()
    try:
        row = session.query(SquidConfig).first()
        if not row:
            return {}

        return {
            "SQUID_HOST": str(row.squid_host or ""),
            "SQUID_PORT": str(row.squid_port or ""),
            "SQUID_HOSTS": str(row.squid_hosts or ""),
            "SQUID_LOG": str(row.squid_log or ""),
            "SQUID_CACHE_LOG": str(row.squid_cache_log or ""),
            "SQUID_CONFIG_PATH": str(row.squid_config_path or ""),
            "ACL_FILES_DIR": str(row.acl_files_dir or ""),
        }
    finally:
        session.close()


def filter_squid_env_keys(env_vars: dict[str, str]) -> dict[str, str]:
    """Return only Squid-related env vars from the provided mapping."""
    return {k: v for k, v in env_vars.items() if k in SQUID_ENV_KEYS}
