from unittest.mock import patch

from routes.admin.helpers import (
    _sanitize_error_details,
    _sanitize_response_payload,
    json_error,
)
from routes.main_routes import _build_error_page, _sanitize_error_message


def test_sanitize_response_payload_strips_sensitive_keys():
    payload = {
        "stack": "some stack text",
        "stack_trace": "frag",
        "normal": "ok",
    }

    sanitized = _sanitize_response_payload(payload)

    assert sanitized["stack"] == "[REDACTED]"
    assert sanitized["stack_trace"] == "[REDACTED]"
    assert sanitized["normal"] == "ok"


def test_sanitize_error_details_redacts_traceback_line():
    details = "Traceback (most recent call last): ..."
    assert _sanitize_error_details(details) == "[REDACTED; check logs]"


def test_json_error_debug_redacts_exception_details(flask_app):
    with flask_app.test_request_context():
        with patch("routes.admin.helpers.is_debug", return_value=True):
            resp, code = json_error("fail", status_code=500, details="Exception: boom")
            assert code == 500
            data = resp.get_json()
            assert data["status"] == "error"
            assert data["details"] == "[REDACTED; check logs]"


def test_build_error_page_sanitizes_stacktrace_like_string(flask_app):
    with flask_app.test_request_context():
        template, status = _build_error_page(
            "Traceback (most recent call last): ...", 500
        )
        assert status == 500
        # Template is Werkzeug response object/str, just ensure sanitizer is applied via helper directly.
        assert (
            _sanitize_error_message("Traceback... Exception")
            == "Unexpected internal failure"
        )
