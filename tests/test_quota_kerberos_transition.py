"""Regression tests for quota ACL transitions around proxy authentication."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from services.quota import quota_service
from utils.admin import SquidConfigManager as RealSquidConfigManager


class _ConfigManager:
    """Minimal file-backed manager for one quota transition."""

    is_valid = True
    is_modular = False
    errors: list[str] = []

    def __init__(self, tmp_path: Path, content: str, *, proxy_auth: bool) -> None:
        self.config_path = str(tmp_path / "squid.conf")
        self.config_dir = str(tmp_path / "squid.d")
        self.config_content = content
        self.proxy_auth = proxy_auth
        Path(self.config_path).write_text(content, encoding="utf-8")

    def load_config(self) -> bool:
        self.config_content = Path(self.config_path).read_text(encoding="utf-8")
        return True

    def _check_modular_config(self) -> None:
        return None

    def has_proxy_authentication(self) -> bool:
        return self.proxy_auth

    def save_config(self, content: str) -> bool:
        self.config_content = content
        Path(self.config_path).write_text(content, encoding="utf-8")
        return True


def _configure_transition(monkeypatch, tmp_path, manager, blocked_file, *, valid=True):
    """Patch host-only validation/runtime dependencies for a focused test."""

    class _ManagerFactory:
        _atomic_write = staticmethod(RealSquidConfigManager._atomic_write)

        def __new__(cls):
            return manager

    @contextmanager
    def lock(_config_path):
        yield

    monkeypatch.setattr(quota_service, "SquidConfigManager", _ManagerFactory)
    monkeypatch.setattr(quota_service, "squid_config_write_lock", lock)
    monkeypatch.setattr(quota_service, "_BLOCKED_USERS_PATH", str(blocked_file))
    monkeypatch.setattr(
        quota_service,
        "_find_squid_runtime",
        lambda: SimpleNamespace(kind="local", executable="squid"),
    )
    monkeypatch.setattr(
        quota_service.SquidConfigSplitter,
        "_validate_squid_config",
        lambda _self: {"success": valid, "error_message": "invalid"},
    )
    monkeypatch.setattr(quota_service, "reconfigure_squid", lambda *_args: (True, "ok"))


def test_enabling_kerberos_replaces_src_quota_representation(tmp_path, monkeypatch):
    """A source include must not survive next to the proxy_auth quota ACL."""
    blocked_file = tmp_path / "usuarios_bloqueados.txt"
    blocked_file.write_text("acl usuarios_bloqueados src 10.20.30.40\n", encoding="utf-8")
    manager = _ConfigManager(
        tmp_path,
        "\n".join(
            [
                "http_port 3128",
                f"include {blocked_file}",
                f'acl usuarios_bloqueados proxy_auth -i "{blocked_file}"',
                "http_access deny usuarios_bloqueados",
                "http_access allow localnet",
                "http_access deny all",
                "",
            ]
        ),
        proxy_auth=True,
    )
    _configure_transition(monkeypatch, tmp_path, manager, blocked_file)

    changed, existing = quota_service._sync_blocked_users_and_squid_rules(
        str(blocked_file), {"alice@EXAMPLE.TEST"}
    )

    assert changed is True
    assert existing == set()
    assert blocked_file.read_text(encoding="utf-8") == "alice@EXAMPLE.TEST\n"
    assert (
        f'acl usuarios_bloqueados proxy_auth -i "{blocked_file}"'
        in manager.config_content
    )
    assert f"include {blocked_file}" not in manager.config_content
    assert "acl usuarios_bloqueados src" not in manager.config_content
    assert manager.config_content.count("acl usuarios_bloqueados") == 1


def test_disabling_kerberos_replaces_proxy_auth_quota_representation(tmp_path, monkeypatch):
    """A plain identity list must be converted before its source include exists."""
    blocked_file = tmp_path / "usuarios_bloqueados.txt"
    blocked_file.write_text("alice@EXAMPLE.TEST\n", encoding="utf-8")
    manager = _ConfigManager(
        tmp_path,
        "\n".join(
            [
                "http_port 3128",
                f'acl usuarios_bloqueados proxy_auth -i "{blocked_file}"',
                f"include {blocked_file}",
                "http_access deny usuarios_bloqueados",
                "http_access allow localnet",
                "http_access deny all",
                "",
            ]
        ),
        proxy_auth=False,
    )
    _configure_transition(monkeypatch, tmp_path, manager, blocked_file)

    changed, existing = quota_service._sync_blocked_users_and_squid_rules(
        str(blocked_file), {"10.20.30.40"}
    )

    assert changed is True
    assert existing == set()
    assert blocked_file.read_text(encoding="utf-8") == (
        "acl usuarios_bloqueados src 10.20.30.40\n"
    )
    assert f"include {blocked_file}" in manager.config_content
    assert (
        f'acl usuarios_bloqueados proxy_auth -i "{blocked_file}"'
        not in manager.config_content
    )
    assert manager.config_content.count("usuarios_bloqueados") == 2


def test_failed_kerberos_quota_transition_restores_config_and_list(tmp_path, monkeypatch):
    """Validation failure rolls back both halves of the mode migration."""
    blocked_file = tmp_path / "usuarios_bloqueados.txt"
    original_list = "acl usuarios_bloqueados src 10.20.30.40\n"
    blocked_file.write_text(original_list, encoding="utf-8")
    original_config = "\n".join(
        [
            "http_port 3128",
            f"include {blocked_file}",
            "http_access deny usuarios_bloqueados",
            "http_access allow localnet",
            "http_access deny all",
            "",
        ]
    )
    manager = _ConfigManager(tmp_path, original_config, proxy_auth=True)
    _configure_transition(monkeypatch, tmp_path, manager, blocked_file, valid=False)

    changed, _existing = quota_service._sync_blocked_users_and_squid_rules(
        str(blocked_file), {"alice@EXAMPLE.TEST"}
    )

    assert changed is False
    assert manager.config_content == original_config
    assert Path(manager.config_path).read_text(encoding="utf-8") == original_config
    assert blocked_file.read_text(encoding="utf-8") == original_list


def test_src_value_file_drops_plain_or_injected_identity_lines(tmp_path):
    """The source include accepts only complete generated src ACL directives."""
    blocked_file = tmp_path / "usuarios_bloqueados.txt"
    blocked_file.write_text(
        "alice@EXAMPLE.TEST\n# operator note\n", encoding="utf-8"
    )

    changed, _existing = quota_service._sync_blocked_users_file(
        str(blocked_file), {"10.20.30.40", "bad\nhttp_access allow all"}, True
    )

    assert changed is True
    content = blocked_file.read_text(encoding="utf-8")
    assert "alice@EXAMPLE.TEST" not in content
    assert "http_access" not in content
    assert content == "# operator note\nacl usuarios_bloqueados src 10.20.30.40\n"
