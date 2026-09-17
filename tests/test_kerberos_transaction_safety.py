"""Transactional and runtime recovery tests for Kerberos configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.squid import kerberos_config_service as kerberos


class _ConfigManager:
    is_modular = False
    is_valid = True
    errors: list[str] = []

    def __init__(self, tmp_path: Path, content: str) -> None:
        self.config_path = str(tmp_path / "squid.conf")
        self.config_dir = str(tmp_path / "squid.d")
        self.config_content = content
        Path(self.config_path).write_text(content, encoding="utf-8")

    def save_config(self, content: str) -> bool:
        self.config_content = content
        Path(self.config_path).write_text(content, encoding="utf-8")
        return True


class _RefreshingConfigManager(_ConfigManager):
    def load_config(self) -> bool:
        self.config_content = Path(self.config_path).read_text(encoding="utf-8")
        return True

    def _check_modular_config(self) -> None:
        return None


@pytest.fixture()
def settings() -> dict[str, object]:
    return {
        "enabled": True,
        "helper_path": "/opt/squid/negotiate_kerberos_auth",
        "keytab_path": "/etc/squid/HTTP.keytab",
        "service_principal": "HTTP/proxy.example@EXAMPLE",
        "children": 10,
        "startup": 5,
        "idle": 3,
        "acl_name": "kerberos_auth",
        "enforce_auth": True,
        "reload_squid": True,
    }


@pytest.fixture()
def bypass_preflight(monkeypatch):
    monkeypatch.setattr(
        kerberos, "_validate_prerequisites", lambda *_args, **_kwargs: {}
    )


def test_disable_rolls_back_when_validation_raises(tmp_path, monkeypatch):
    original = (
        "http_port 3128\n"
        "# BEGIN SquidStats Kerberos authentication\n"
        "auth_param negotiate program /opt/helper -k /etc/squid/HTTP.keytab "
        "-s HTTP/proxy.example@EXAMPLE\n"
        "acl kerberos_auth proxy_auth REQUIRED\n"
        "# END SquidStats Kerberos authentication\n"
        "http_access allow localnet\nhttp_access deny all\n"
    )
    manager = _ConfigManager(tmp_path, original)
    monkeypatch.setattr(kerberos, "_find_squid_runtime", lambda: None)
    monkeypatch.setattr(
        kerberos,
        "validate_squid_configuration",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("parse boom")),
    )

    with pytest.raises(kerberos.KerberosConfigurationError):
        kerberos.apply_configuration({"enabled": False}, manager)

    assert manager.config_content == original
    assert Path(manager.config_path).read_text(encoding="utf-8") == original


def test_failed_reconfigure_reloads_the_restored_configuration(
    tmp_path, monkeypatch, settings, bypass_preflight
):
    original = "http_port 3128\nhttp_access allow localnet\nhttp_access deny all\n"
    manager = _ConfigManager(tmp_path, original)
    runtime = kerberos._SquidRuntime(kind="local", executable="/usr/sbin/squid")
    calls: list[Path] = []
    monkeypatch.setattr(kerberos, "_find_squid_runtime", lambda: runtime)
    monkeypatch.setattr(
        kerberos,
        "validate_squid_configuration",
        lambda *_args, **_kwargs: {
            "available": True,
            "valid": True,
            "message": "ok",
        },
    )

    def reconfigure(config_path, _runtime):
        calls.append(Path(config_path))
        return (len(calls) > 1, "simulated failure")

    monkeypatch.setattr(kerberos, "reconfigure_squid", reconfigure)

    with pytest.raises(kerberos.KerberosConfigurationError):
        kerberos.apply_configuration(settings, manager)

    assert manager.config_content == original
    assert len(calls) == 2


def test_apply_refreshes_the_cached_manager_before_writing(
    tmp_path, monkeypatch, settings, bypass_preflight
):
    initial = "http_port 3128\nhttp_access allow oldnet\nhttp_access deny all\n"
    current = "http_port 3128\nhttp_access allow newnet\nhttp_access deny all\n"
    manager = _RefreshingConfigManager(tmp_path, initial)
    Path(manager.config_path).write_text(current, encoding="utf-8")
    monkeypatch.setattr(kerberos, "_find_squid_runtime", lambda: None)
    monkeypatch.setattr(
        kerberos,
        "validate_squid_configuration",
        lambda *_args, **_kwargs: {
            "available": True,
            "valid": True,
            "message": "ok",
        },
    )

    kerberos.apply_configuration({**settings, "reload_squid": False}, manager)

    assert "http_access allow newnet" in manager.config_content
    assert "http_access allow oldnet" not in manager.config_content
