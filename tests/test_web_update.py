"""Tests for the web application update flow."""

from unittest.mock import Mock

from routes import main_routes
from utils import updateSquidStats


def _dashboard_context():
    return {
        "grouped_connections": {},
        "valid_users": {},
        "squid_version": "test",
        "squid_info_stats": {},
        "page_icon": "favicon.ico",
        "page_title": "Test dashboard",
        "build_time_ms": 0,
        "connection_count": 0,
        "system_type": "test",
        "proxy_statuses": [],
        "multi_proxy": False,
    }


def test_dashboard_renders_web_update_button(client, monkeypatch):
    """The desktop web update button and its update handler are present."""
    monkeypatch.setattr(
        main_routes, "_get_dashboard_context", lambda: (_dashboard_context(), None)
    )
    client.application.jinja_env.globals["csrf_token"] = lambda: "test-token"

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="web-update-btn"' in html
    assert 'onclick="confirmWebUpdate()"' in html
    assert "fetch('/update'" in html


def test_update_status_returns_web_update_state(client, monkeypatch):
    """The endpoint used by the button exposes the latest web version state."""
    monkeypatch.setattr(
        main_routes,
        "check_squid_update",
        lambda: {"available": False, "current": "6.0", "latest": None},
    )
    web_status = {
        "available": True,
        "current": "2.6.1",
        "latest": "2.7.0",
        "error": None,
    }
    monkeypatch.setattr(main_routes, "check_web_update", lambda _version: web_status)
    main_routes._update_status_cache = {"data": None, "timestamp": 0}

    response = client.get("/api/update-status")

    assert response.status_code == 200
    assert response.get_json()["web"] == web_status


def test_update_web_redirects_with_success_flash(client, monkeypatch):
    """A successful update delegates to the updater and reports success."""
    updater = Mock(return_value=True)
    monkeypatch.setattr(main_routes, "updateSquidStats", updater)

    response = client.post("/update")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    updater.assert_called_once_with()
    with client.session_transaction() as session:
        assert any(
            category == "success" and "actualizado correctamente" in message
            for category, message in session["_flashes"]
        )


def test_update_web_redirects_with_error_flash(client, monkeypatch):
    """A failed update reports an error instead of claiming success."""
    updater = Mock(return_value=False)
    monkeypatch.setattr(main_routes, "updateSquidStats", updater)

    response = client.post("/update")

    assert response.status_code == 302
    updater.assert_called_once_with()
    with client.session_transaction() as session:
        assert any(
            category == "error" and "Error al actualizar SquidStats" in message
            for category, message in session["_flashes"]
        )


def test_update_web_handles_updater_exception(client, monkeypatch):
    """An updater exception is converted into an error flash and redirect."""
    updater = Mock(side_effect=RuntimeError("update failed"))
    monkeypatch.setattr(main_routes, "updateSquidStats", updater)

    response = client.post("/update")

    assert response.status_code == 302
    updater.assert_called_once_with()
    with client.session_transaction() as session:
        assert any(
            category == "error" and "Error inesperado" in message
            for category, message in session["_flashes"]
        )


def test_check_web_update_detects_newer_release(monkeypatch):
    """A newer GitHub release is reported as available."""
    response = Mock()
    response.json.return_value = {"tag_name": "v2.7.0"}
    response.raise_for_status.return_value = None
    monkeypatch.setattr(
        updateSquidStats.requests, "get", lambda *args, **kwargs: response
    )
    monkeypatch.setattr(
        updateSquidStats,
        "_WEB_UPDATE_CACHE",
        {"data": None, "timestamp": 0},
    )

    result = updateSquidStats.check_web_update("2.6.1", force_refresh=True)

    assert result == {
        "available": True,
        "current": "2.6.1",
        "latest": "v2.7.0",
        "error": None,
    }


def test_check_web_update_handles_github_failure(monkeypatch):
    """A GitHub failure hides the indicator and exposes an error state."""

    def fail_request(*args, **kwargs):
        raise RuntimeError("GitHub unavailable")

    monkeypatch.setattr(updateSquidStats.requests, "get", fail_request)
    monkeypatch.setattr(
        updateSquidStats,
        "_WEB_UPDATE_CACHE",
        {"data": None, "timestamp": 0},
    )

    result = updateSquidStats.check_web_update("2.6.1", force_refresh=True)

    assert result["available"] is False
    assert result["current"] == "2.6.1"
    assert result["latest"] is None
    assert result["error"] == "No se pudo verificar la actualización de SquidStats"
