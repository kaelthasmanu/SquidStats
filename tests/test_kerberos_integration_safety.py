"""Regression tests for Kerberos interactions with generic config features."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.quota.quota_service import _ensure_quota_http_rule
from services.squid.acls_service import add_acl, delete_acl, edit_acl
from services.squid.http_access_service import edit_http_access
from utils.admin import SquidConfigManager, _replacement_ownership


class _AclManager:
    """Minimal monolithic manager for the generic ACL editor tests."""

    is_modular = False

    def __init__(self, content: str, acls: list[dict]) -> None:
        self.config_content = content
        self._acls = acls
        self.saved: list[str] = []

    def get_acls(self):
        return self._acls

    def save_config(self, content: str) -> bool:
        self.saved.append(content)
        self.config_content = content
        return True


class _AuthStatusManager:
    """Use the production active-include scanner with fixture files."""

    _active_configuration_contents = SquidConfigManager._active_configuration_contents
    has_proxy_authentication = SquidConfigManager.has_proxy_authentication

    def __init__(self, config_path, content: str) -> None:
        self.config_path = str(config_path)
        self.config_content = content
        self.is_valid = True


class _RefreshingAclManager(_AclManager):
    """A long-lived editor manager whose on-disk config changed meanwhile."""

    def __init__(self, config_path, initial_content: str, current_content: str) -> None:
        super().__init__(initial_content, [{"name": "manager", "line_number": 1}])
        self.config_path = str(config_path)
        config_path.write_text(current_content, encoding="utf-8")

    def load_config(self) -> bool:
        self.config_content = Path(self.config_path).read_text(encoding="utf-8")
        return True

    def _check_modular_config(self) -> None:
        return None


def test_generic_acl_editor_cannot_mutate_managed_kerberos_identity_acl():
    content = (
        "# BEGIN SquidStats Kerberos authentication\n"
        "auth_param negotiate program /opt/helper -k /etc/squid/HTTP.keytab "
        "-s HTTP/proxy.example@EXAMPLE\n"
        "acl kerberos_auth proxy_auth REQUIRED\n"
        "# END SquidStats Kerberos authentication\n"
    )
    manager = _AclManager(
        content,
        [{"name": "kerberos_auth", "line_number": 3}],
    )

    assert add_acl("kerberos_auth", "src", ["10.0.0.0/8"], [], "", manager)[
        0
    ] is False
    assert edit_acl(
        0, "other_name", "src", ["10.0.0.0/8"], [], "", manager
    )[0] is False
    assert delete_acl(0, manager)[0] is False
    assert manager.saved == []


def test_generic_acl_editor_cannot_rename_an_acl_to_the_managed_name():
    content = (
        "# BEGIN SquidStats Kerberos authentication\n"
        "acl kerberos_auth proxy_auth REQUIRED\n"
        "# END SquidStats Kerberos authentication\n"
        "acl office src 10.0.0.0/8\n"
    )
    manager = _AclManager(content, [{"name": "office", "line_number": 4}])

    ok, _message = edit_acl(
        0,
        "kerberos_auth",
        "src",
        ["10.0.0.0/8"],
        [],
        "",
        manager,
    )

    assert ok is False
    assert manager.saved == []


def test_generic_acl_editor_cannot_broaden_the_pre_kerberos_manager_exception():
    """The manager/localhost ACLs are part of the managed access invariant."""
    content = "\n".join(
        [
            "acl manager proto cache_object",
            "acl localhost src 127.0.0.1/32 ::1",
            "# BEGIN SquidStats Kerberos access rule",
            "http_access deny !kerberos_auth",
            "# END SquidStats Kerberos access rule",
        ]
    )
    manager = _AclManager(
        content,
        [
            {"name": "manager", "line_number": 1},
            {"name": "localhost", "line_number": 2},
        ],
    )

    assert add_acl("manager", "all", [""], [], "", manager)[0] is False
    assert edit_acl(0, "manager", "all", [""], [], "", manager)[0] is False
    assert delete_acl(1, manager)[0] is False
    assert manager.saved == []


def test_acl_editor_rechecks_kerberos_after_waiting_for_the_config_lock(tmp_path):
    """A stale request cannot broaden manager after a Kerberos apply wins."""
    initial = "acl manager proto cache_object\n"
    current = "\n".join(
        [
            initial.rstrip(),
            "# BEGIN SquidStats Kerberos access rule",
            "http_access deny !kerberos_auth",
            "# END SquidStats Kerberos access rule",
        ]
    )
    manager = _RefreshingAclManager(tmp_path / "squid.conf", initial, current)

    ok, _message = edit_acl(0, "manager", "all", [""], [], "", manager)

    assert ok is False
    assert manager.saved == []


def test_proxy_auth_quota_rule_stays_after_manager_and_kerberos_blocks():
    lines = [
        "http_access allow manager localhost",
        "http_access deny manager",
        "http_access deny !Safe_ports",
        "# BEGIN SquidStats Kerberos access rule",
        "http_access deny !kerberos_auth",
        "# END SquidStats Kerberos access rule",
        "http_access allow localnet",
        "http_access deny all",
    ]

    updated = _ensure_quota_http_rule(
        lines, "http_access deny usuarios_bloqueados", use_src=False
    )

    assert updated.index("http_access allow manager localhost") < updated.index(
        "http_access deny usuarios_bloqueados"
    )
    assert updated.index("# END SquidStats Kerberos access rule") < updated.index(
        "http_access deny usuarios_bloqueados"
    ) < updated.index("http_access allow localnet")


def test_proxy_auth_quota_rule_respects_reversed_manager_exception():
    """The Cache Manager ACL order is conjunctive, so either order is safe."""
    lines = [
        "http_access allow localhost manager",
        "http_access deny manager",
        "http_access deny !Safe_ports",
        "http_access allow localnet",
        "http_access deny all",
    ]

    updated = _ensure_quota_http_rule(
        lines, "http_access deny usuarios_bloqueados", use_src=False
    )

    assert updated.index("http_access allow localhost manager") < updated.index(
        "http_access deny usuarios_bloqueados"
    ) < updated.index("http_access allow localnet")


def test_existing_proxy_auth_quota_rule_is_repositioned_safely():
    lines = [
        "http_access deny usuarios_bloqueados",
        "http_access allow manager localhost",
        "http_access deny manager",
        "# BEGIN SquidStats Kerberos access rule",
        "http_access deny !kerberos_auth",
        "# END SquidStats Kerberos access rule",
        "http_access allow localnet",
        "http_access deny all",
    ]

    updated = _ensure_quota_http_rule(
        lines, "http_access deny usuarios_bloqueados", use_src=False
    )

    assert updated.count("http_access deny usuarios_bloqueados") == 1
    assert updated.index("http_access deny usuarios_bloqueados") > updated.index(
        "# END SquidStats Kerberos access rule"
    )


def test_http_editor_cannot_turn_a_pre_kerberos_rule_into_a_client_allow():
    """Editing a neighboring rule must not bypass the managed challenge."""
    manager = _AclManager(
        "\n".join(
            [
                "http_access allow manager localhost",
                "http_access deny manager",
                "# BEGIN SquidStats Kerberos access rule",
                "http_access deny !kerberos_auth",
                "# END SquidStats Kerberos access rule",
                "http_access allow localnet",
                "http_access deny all",
            ]
        ),
        [],
    )

    ok, message = edit_http_access(0, "allow", ["localnet"], "", manager)

    assert ok is False
    assert "antes del desafío Kerberos" in message
    assert manager.saved == []


def test_http_editor_keeps_an_undocumented_rule_without_an_empty_comment():
    """The generic editor must still save ordinary HTTP rules unchanged."""
    manager = _AclManager("http_access allow localnet", [])

    ok, _message = edit_http_access(0, "allow", ["office"], "", manager)

    assert ok is True
    assert manager.config_content == "http_access allow office"
    assert "# " not in manager.config_content


def test_http_editor_accepts_the_conventional_reversed_manager_exception():
    """``allow localhost manager`` is just as narrow as the other order."""
    manager = _AclManager(
        "\n".join(
            [
                "http_access allow localhost manager",
                "http_access deny manager",
                "# BEGIN SquidStats Kerberos access rule",
                "http_access deny !kerberos_auth",
                "# END SquidStats Kerberos access rule",
                "http_access allow localnet",
                "http_access deny all",
            ]
        ),
        [],
    )

    ok, _message = edit_http_access(3, "allow", ["office"], "", manager)

    assert ok is True
    assert "http_access allow office" in manager.config_content


def test_proxy_auth_status_ignores_a_stale_unincluded_auth_module(tmp_path):
    module_dir = tmp_path / "squid.d"
    module_dir.mkdir()
    (module_dir / "50_auth.conf").write_text(
        "auth_param negotiate program /opt/helper\n"
        "acl kerberos_auth proxy_auth REQUIRED\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "squid.conf"
    config_path.write_text(
        f"include {module_dir / '120_http_access.conf'}\n", encoding="utf-8"
    )
    manager = _AuthStatusManager(config_path, config_path.read_text(encoding="utf-8"))

    assert manager.has_proxy_authentication() is False

    config_path.write_text(f"include {module_dir / '*.conf'}\n", encoding="utf-8")
    manager.config_content = config_path.read_text(encoding="utf-8")

    assert manager.has_proxy_authentication() is True


def test_modular_detection_supports_a_continued_include_directive(tmp_path):
    """Kerberos must select modules when Squid wraps an include line."""
    module_dir = tmp_path / "squid.d"
    module_dir.mkdir()
    manager = SquidConfigManager.__new__(SquidConfigManager)
    manager.config_path = str(tmp_path / "squid.conf")
    manager.config_dir = str(module_dir)
    manager.config_content = "http_port 3128\ninclude \\\n    squid.d/*.conf\n"
    manager.is_modular = False

    manager._check_modular_config()

    assert manager.is_modular is True
    assert manager.config_dir == str(module_dir)


def test_atomic_writes_preserve_existing_squid_config_permissions(tmp_path):
    config_path = tmp_path / "squid.conf"
    config_path.write_text("before\n", encoding="utf-8")
    os.chmod(config_path, 0o640)

    SquidConfigManager._atomic_write(str(config_path), "after\n")

    result = config_path.stat()
    assert config_path.read_text(encoding="utf-8") == "after\n"
    assert stat.S_IMODE(result.st_mode) == 0o640


def test_unprivileged_atomic_replacement_preserves_an_allowed_squid_group(
    monkeypatch,
):
    """Directory ACLs must not force an impossible root-owner fchown."""
    metadata = SimpleNamespace(st_uid=0, st_gid=4567, st_mode=0o640)
    monkeypatch.setattr("utils.admin.os.geteuid", lambda: 1234)
    monkeypatch.setattr("utils.admin.os.getegid", lambda: 1234)
    monkeypatch.setattr("utils.admin.os.getgroups", lambda: [4567])

    assert _replacement_ownership(metadata) == (-1, 4567)


def test_unprivileged_atomic_replacement_rejects_unreadable_foreign_group(
    monkeypatch,
):
    """Do not replace a protected file with one Squid may no longer read."""
    metadata = SimpleNamespace(st_uid=0, st_gid=4567, st_mode=0o640)
    monkeypatch.setattr("utils.admin.os.geteuid", lambda: 1234)
    monkeypatch.setattr("utils.admin.os.getegid", lambda: 1234)
    monkeypatch.setattr("utils.admin.os.getgroups", lambda: [])

    with pytest.raises(PermissionError, match="conservar el grupo"):
        _replacement_ownership(metadata)


def test_atomic_writes_make_new_generated_config_modules_readable(tmp_path):
    module_path = tmp_path / "50_auth.conf"

    SquidConfigManager._atomic_write(str(module_path), "# generated\n")

    assert stat.S_IMODE(module_path.stat().st_mode) == 0o644


def test_atomic_write_preserves_a_squid_config_symlink(tmp_path):
    target = tmp_path / "actual-squid.conf"
    target.write_text("before\n", encoding="utf-8")
    config_path = tmp_path / "squid.conf"
    config_path.symlink_to(target.name)

    SquidConfigManager._atomic_write(str(config_path), "after\n")

    assert config_path.is_symlink()
    assert target.read_text(encoding="utf-8") == "after\n"


def test_stale_main_config_snapshot_is_not_overwritten(tmp_path):
    """A second writer must reload instead of erasing a Kerberos update."""
    config_path = tmp_path / "squid.conf"
    config_path.write_text("newer Kerberos config\n", encoding="utf-8")
    manager = SquidConfigManager.__new__(SquidConfigManager)
    manager.config_path = str(config_path)
    manager.config_content = "older config\n"
    manager._modular_content_snapshots = {}
    manager.is_valid = True

    assert manager.save_config("unrelated change\n") is False
    assert config_path.read_text(encoding="utf-8") == "newer Kerberos config\n"


def test_stale_modular_snapshot_is_not_overwritten(tmp_path):
    """The shared save path also protects 120_http_access.conf."""
    module_path = tmp_path / "120_http_access.conf"
    module_path.write_text("newer Kerberos challenge\n", encoding="utf-8")
    manager = SquidConfigManager.__new__(SquidConfigManager)
    manager.config_path = str(tmp_path / "squid.conf")
    manager.config_dir = str(tmp_path)
    manager._modular_content_snapshots = {
        "120_http_access.conf": "older access policy\n"
    }
    manager.is_valid = True

    assert manager.save_modular_config("120_http_access.conf", "quota snapshot\n") is False
    assert module_path.read_text(encoding="utf-8") == "newer Kerberos challenge\n"
