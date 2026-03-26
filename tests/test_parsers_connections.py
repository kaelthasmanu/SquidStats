"""
Tests for the connections parser (parsers/connections.py).
"""

import pytest

from parsers.connections import parse_raw_data, group_by_user


class TestParseRawData:
    def test_empty_input_returns_empty(self):
        assert parse_raw_data("") == []
        assert parse_raw_data(None) == []

    def test_header_only_returns_empty(self):
        raw = "HTTP/1.1 200 OK\r\nServer: squid/6.1\r\n\r\n"
        result = parse_raw_data(raw)
        assert result == []

    def test_parses_connection_block(self):
        raw = (
            "HTTP/1.1 200 OK\r\nServer: squid/6.1\r\n\r\n"
            "Connection: 0x12345\n"
            "    FD 10\n"
            "    uri http://example.com\n"
            "    username testuser\n"
            "    logType TCP_MISS\n"
            "    remote: 192.168.1.1:12345\n"
            "    local: 127.0.0.1:3128\n"
        )
        result = parse_raw_data(raw)
        assert len(result) >= 1
        conn = result[0]
        assert conn.get("uri") == "http://example.com"
        assert conn.get("username") == "testuser"

    def test_extracts_squid_version(self):
        raw = (
            "HTTP/1.1 200 OK\r\nServer: squid/6.10\r\n\r\n"
            "Connection: 0x1\n"
            "    FD 1\n"
            "    uri http://test.com\n"
            "    username user1\n"
        )
        result = parse_raw_data(raw)
        assert len(result) >= 1
        assert result[0].get("squid_version") == "6.10"


class TestGroupByUser:
    def test_groups_connections(self):
        connections = [
            {"username": "user1", "uri": "http://a.com", "data_read": 100, "data_written": 50},
            {"username": "user1", "uri": "http://b.com", "data_read": 200, "data_written": 100},
            {"username": "user2", "uri": "http://c.com", "data_read": 50, "data_written": 25},
        ]
        grouped = group_by_user(connections)
        assert "user1" in grouped
        assert "user2" in grouped
        assert len(grouped["user1"]["connections"]) == 2
        assert len(grouped["user2"]["connections"]) == 1

    def test_empty_list(self):
        grouped = group_by_user([])
        assert grouped == {}
