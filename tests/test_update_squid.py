"""Tests for Squid update errors exposed to the frontend."""

from routes import main_routes
from utils import updateSquid


def test_update_squid_reports_missing_wget(monkeypatch):
    """A missing wget binary produces a safe, actionable failure message."""
    monkeypatch.setattr(
        updateSquid.platform,
        "freedesktop_os_release",
        lambda: {"ID": "ubuntu", "VERSION_CODENAME": "jammy"},
    )
    monkeypatch.setattr(updateSquid.shutil, "which", lambda _name: None)

    success, message = updateSquid.update_squid()

    assert success is False
    assert message == updateSquid.WGET_NOT_INSTALLED_MESSAGE


def test_install_returns_missing_wget_error_as_json(client, monkeypatch):
    """AJAX callers receive the reason instead of an invisible flash redirect."""
    monkeypatch.setattr(
        main_routes,
        "update_squid",
        lambda: (False, updateSquid.WGET_NOT_INSTALLED_MESSAGE),
    )

    response = client.post("/install", headers={"Accept": "application/json"})

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "error",
        "message": updateSquid.WGET_NOT_INSTALLED_MESSAGE,
    }


def test_install_returns_success_as_json(client, monkeypatch):
    """AJAX callers get an explicit success result before the page reloads."""
    monkeypatch.setattr(main_routes, "update_squid", lambda: (True, None))

    response = client.post("/install", headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
