"""
Tests for log line parsers (parsers/log.py).
"""

from parsers.log import (
    FORMAT_AUTO,
    FORMAT_DEFAULT,
    FORMAT_DETAILED,
    detect_log_format,
    parse_log_line,
    parse_log_line_default,
    parse_log_line_pipe_format,
    parse_log_line_space_format,
)


class TestParseLogLineDetailed:
    """Tests for DETAILED (default) log parsing mode."""

    def test_classic_squid_format(self):
        line = (
            "1609459200.000      1 192.168.1.100 TCP_MISS/200 1234 "
            "GET http://example.com/page user1 HIER_DIRECT/93.184.216.34 text/html"
        )
        result = parse_log_line(line)
        assert result is not None
        assert result["ip"] == "192.168.1.100"
        assert result["url"] == "http://example.com/page"
        assert result["response"] == 200
        assert result["data_transmitted"] == 1234
        assert result["method"] == "GET"
        assert result["is_denied"] is False

    def test_denied_entry(self):
        line = (
            "1609459200.000      1 10.0.0.5 TCP_DENIED/403 500 "
            "GET http://blocked.com/ user2 HIER_NONE/- text/html"
        )
        result = parse_log_line(line)
        assert result is not None
        assert result["is_denied"] is True
        assert result["response"] == 403

    def test_cache_object_ignored(self):
        line = "1609459200.000 cache_object://localhost/info"
        result = parse_log_line(line)
        assert result is None

    def test_error_transaction_ignored(self):
        line = (
            "1609459200.000      0 10.0.0.1 TAG_NONE/0 0 "
            "NONE error:transaction-end-before-headers HIER_NONE/- -"
        )
        result = parse_log_line(line)
        assert result is None

    def test_error_invalid_request_ignored(self):
        line = "1609459200.000 error:invalid-request something"
        result = parse_log_line(line)
        assert result is None

    def test_empty_line_returns_none(self):
        assert parse_log_line("") is None

    def test_malformed_line_returns_none(self):
        assert parse_log_line("this is not a log line") is None


class TestPipeFormat:
    def test_valid_pipe_line(self):
        line = "1609459200|192.168.1.1|3128|user1|TCP_MISS|GET|http://example.com|host|200|1024|text/html|0|0|TCP_MISS/200"
        result = parse_log_line_pipe_format(line)
        assert result is not None
        assert result["username"] == "user1"
        assert result["ip"] == "192.168.1.1"
        assert result["url"] == "http://example.com"
        assert result["response"] == 200
        assert result["data_transmitted"] == 1024

    def test_anonymous_user_returns_none(self):
        line = "1609459200|192.168.1.1|3128|-|TCP_MISS|GET|http://example.com|host|200|1024|text/html|0|0|TCP_MISS/200"
        result = parse_log_line_pipe_format(line)
        assert result is None

    def test_short_pipe_line_returns_none(self):
        line = "a|b|c"
        result = parse_log_line_pipe_format(line)
        assert result is None


class TestSpaceFormat:
    def test_valid_space_line(self):
        line = "1609459200.000 192.168.1.1 3128 user1 TCP_MISS GET http://example.com host 0 200 1024"
        result = parse_log_line_space_format(line)
        assert result is not None
        assert result["username"] == "user1"
        assert result["ip"] == "192.168.1.1"

    def test_anonymous_returns_none(self):
        line = "1609459200.000 192.168.1.1 3128 - TCP_MISS GET http://example.com host 0 200 1024"
        result = parse_log_line_space_format(line)
        assert result is None

    def test_short_line_returns_none(self):
        line = "1609459200.000 192.168.1.1"
        result = parse_log_line_space_format(line)
        assert result is None


class TestDefaultFormat:
    def test_valid_default_line(self):
        line = (
            "1609459200.000      1 192.168.1.100 TCP_MISS/200 1234 "
            "GET http://example.com/page user1 HIER_DIRECT/93.184.216.34 text/html"
        )
        result = parse_log_line_default(line)
        assert result is not None
        assert result["url"] == "http://example.com/page"
        assert result["response"] == 200
        assert result["data_transmitted"] == 1234

    def test_short_line_returns_none(self):
        assert parse_log_line_default("a b c") is None

    def test_cache_object_returns_none(self):
        line = (
            "1609459200.000      1 192.168.1.100 TCP_MISS/200 1234 "
            "GET cache_object://localhost/info user1 HIER_DIRECT/93.184.216.34 text/html"
        )
        result = parse_log_line_default(line)
        assert result is None


class TestAutomaticFormatDetection:
    def test_detects_default_file_format(self, tmp_path):
        log_file = tmp_path / "access.log"
        log_file.write_text(
            "1609459200.000 1 192.168.1.100 TCP_MISS/200 1234 "
            "GET http://example.com/page user1 HIER_DIRECT/- text/html\n",
            encoding="utf-8",
        )

        assert detect_log_format(log_file) == FORMAT_DEFAULT

    def test_detects_detailed_file_format(self, tmp_path):
        log_file = tmp_path / "access.log"
        log_file.write_text(
            "1609459200.000 192.168.1.100 - user1 "
            "[20/Aug/2026:14:00:00 -0400] "
            '"GET http://example.com/page HTTP/1.1" 200 1234 '
            "GET http://example.com/page 192.168.1.100 text/html "
            "- TCP_MISS/200 1234\n",
            encoding="utf-8",
        )

        assert detect_log_format(log_file) == FORMAT_DETAILED

        result = parse_log_line(
            log_file.read_text(encoding="utf-8").strip(),
            format_hint=FORMAT_DETAILED,
        )
        assert result == {
            "ip": "192.168.1.100",
            "username": "user1",
            "url": "http://example.com/page",
            "response": 200,
            "data_transmitted": 1234,
            "method": "GET",
            "status": "200",
            "is_denied": False,
        }

    def test_unknown_file_falls_back_to_per_line_detection(self, tmp_path):
        log_file = tmp_path / "access.log"
        log_file.write_text("not a Squid access log\n", encoding="utf-8")

        assert detect_log_format(log_file) == FORMAT_AUTO
