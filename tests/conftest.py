"""
Shared fixtures for SquidStats test suite.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Override env vars BEFORE importing any project module that reads Config at import time
os.environ.setdefault("DATABASE_TYPE", "SQLITE")
os.environ.setdefault("DATABASE_STRING_CONNECTION", "sqlite:///:memory:")
os.environ.setdefault("SQUID_LOG", "/dev/null")
os.environ.setdefault("SQUID_CONFIG_PATH", "/dev/null")
os.environ.setdefault("SQUID_HOST", "127.0.0.1")
os.environ.setdefault("SQUID_PORT", "3128")

import database.database as db_module  # noqa: E402
from database.base import Base  # noqa: E402


@pytest.fixture()
def in_memory_engine():
    """Create a fresh in-memory SQLite engine per test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(in_memory_engine):
    """Provide a scoped DB session that rolls back after the test."""
    Session = sessionmaker(bind=in_memory_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def patched_db(in_memory_engine, db_session):
    """Monkey-patch the global database module to use in-memory engine/session."""
    old_engine = db_module._engine
    old_session = db_module._Session
    old_cache = db_module.dynamic_model_cache.copy()

    db_module._engine = in_memory_engine
    db_module._Session = sessionmaker(bind=in_memory_engine)
    db_module.dynamic_model_cache.clear()

    yield db_session

    db_module._engine = old_engine
    db_module._Session = old_session
    db_module.dynamic_model_cache = old_cache


@pytest.fixture()
def flask_app():
    """Minimal Flask app for testing routes (no scheduler, no migrations)."""
    from flask import Flask

    from routes import register_routes
    from utils.filters import register_filters

    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"  # noqa: S105
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SERVER_NAME"] = "localhost"
    app.config["BABEL_DEFAULT_LOCALE"] = "es"

    from flask_babel import Babel, get_locale

    Babel(app)
    app.jinja_env.globals["get_locale"] = get_locale
    app.jinja_env.globals["LANGUAGES"] = {"es": "Español", "en": "English"}

    register_filters(app)

    with patch("routes.auth_routes.csrf") as mock_csrf:
        mock_csrf.init_app = lambda _app: None
        register_routes(app)

    return app


@pytest.fixture()
def client(flask_app):
    """Flask test client."""
    return flask_app.test_client()


@pytest.fixture()
def tmp_squid_conf(tmp_path):
    """Create a temporary squid.conf for splitter tests."""
    conf = tmp_path / "squid.conf"
    conf.write_text(
        """\
# Ports
http_port 3128

# Misc
visible_hostname squid-proxy
pid_filename /var/run/squid.pid

# Cache
cache_mem 64 MB
cache_dir ufs /var/spool/squid 100 16 256

# Logs
access_log /var/log/squid/access.log
cache_log /var/log/squid/cache.log

# Security
forwarded_for off
via off

# ACLs
acl localhost src 127.0.0.1/32 ::1
acl red_local src 10.0.0.0/8

# HTTP Access
http_access allow localhost
http_access allow red_local
http_access deny all

# Refresh patterns
refresh_pattern ^ftp:		1440	20%	10080
refresh_pattern .		0	20%	4320
""",
        encoding="utf-8",
    )
    return conf
