import pytest

from config import Config
from database.database import (
    _clean_connection_string,
    _parse_server_database_name,
    get_database_url,
)


def test_connection_string_removes_accidental_outer_quotes():
    connection_string = '"mysql+pymysql://user:password@localhost:3306/squidstatsdb"'

    assert (
        _clean_connection_string(connection_string)
        == "mysql+pymysql://user:password@localhost:3306/squidstatsdb"
    )


def test_server_database_name_removes_trailing_quote():
    parsed_url, database_name = _parse_server_database_name(
        "mysql+pymysql://user:password@localhost:3306/squidstatsdb\""
    )

    assert parsed_url.scheme == "mysql+pymysql"
    assert database_name == "squidstatsdb"


def test_get_database_url_uses_cleaned_mysql_connection_string(monkeypatch):
    monkeypatch.setattr(Config, "DATABASE_TYPE", "MYSQL")
    monkeypatch.setattr(
        Config,
        "DATABASE_STRING_CONNECTION",
        '"mysql+pymysql://user:password@localhost:3306/squidstatsdb"',
    )

    assert get_database_url() == (
        "mysql+pymysql://user:password@localhost:3306/squidstatsdb"
    )


def test_server_database_name_rejects_unsafe_identifier():
    with pytest.raises(ValueError, match="unsupported characters"):
        _parse_server_database_name(
            "mysql+pymysql://user:password@localhost:3306/squidstatsdb;DROP"
        )
