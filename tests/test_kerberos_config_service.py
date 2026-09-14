"""Focused safety tests for managed Squid Kerberos configuration."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from services.squid import kerberos_config_service as kerberos
from services.squid.http_access_service import delete_http_access, move_http_access
from utils.admin import SquidConfigManager


class _ConfigManager:
    """Small in-memory/on-disk stand-in for ``SquidConfigManager``.

    The production service intentionally uses the manager abstraction, so this
    fixture exercises its transaction and modular-target behaviour without
    requiring a host Squid installation.
    """

    def __init__(
        self,
        tmp_path: Path,
        content: str,
        *,
        modular: bool = False,
        modules: dict[str, str] | None = None,
    ) -> None:
        self.config_path = str(tmp_path / "squid.conf")
        self.config_dir = str(tmp_path / "squid.d")
        self.config_content = content
        self.is_valid = True
        self.errors: list[str] = []
        self.is_modular = modular
        self._module_dir = Path(self.config_dir)
        self._module_dir.mkdir()
        Path(self.config_path).write_text(content, encoding="utf-8")
        for filename, module_content in (modules or {}).items():
            (self._module_dir / filename).write_text(module_content, encoding="utf-8")

    def save_config(self, content: str) -> bool:
        self.config_content = content
        Path(self.config_path).write_text(content, encoding="utf-8")
        return True

    def read_modular_config(self, filename: str) -> str | None:
        path = self._module_dir / filename
        return path.read_text(encoding="utf-8") if path.exists() else None

    def save_modular_config(self, filename: str, content: str) -> bool:
        (self._module_dir / filename).write_text(content, encoding="utf-8")
        return True

    def _active_configuration_contents(self) -> list[str]:
        """Use the production include traversal with this file-backed double."""
        return SquidConfigManager._active_configuration_contents(self)


class _RecordingConfigManager(_ConfigManager):
    """Test double that records transactional save ordering."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.saved_targets: list[str] = []

    def save_config(self, content: str) -> bool:
        self.saved_targets.append("squid.conf")
        return super().save_config(content)

    def save_modular_config(self, filename: str, content: str) -> bool:
        self.saved_targets.append(filename)
        return super().save_modular_config(filename, content)


@pytest.fixture()
def kerberos_data() -> dict[str, object]:
    """Valid settings independent of a distribution-specific helper path."""
    return {
        "enabled": True,
        "helper_path": "/opt/squid/negotiate_kerberos_auth",
        "keytab_path": "/var/run/squid/HTTP.keytab",
        "service_principal": "HTTP/inutil.cu@INUTIL.CU",
        "children": 10,
        "startup": 5,
        "idle": 3,
        "keep_alive": True,
        "strip_realm": False,
        "acl_name": "kerberos_auth",
        "enforce_auth": True,
        "reload_squid": False,
    }


@pytest.fixture()
def no_host_squid(monkeypatch):
    """Keep tests about config layout, not the local Squid installation."""
    monkeypatch.setattr(
        kerberos, "_validate_prerequisites", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        kerberos,
        "validate_squid_configuration",
        lambda *_args, **_kwargs: {
            "available": True,
            "valid": True,
            "message": "Configuración validada.",
        },
    )


def test_rendered_directives_are_literal_squid_syntax(kerberos_data):
    """Markdown escapes must never be copied into the generated config."""
    settings = kerberos.normalise_settings(kerberos_data)

    preview = kerberos.render_preview(settings)

    assert (
        "auth_param negotiate program /opt/squid/negotiate_kerberos_auth "
        "-k /var/run/squid/HTTP.keytab -s HTTP/inutil.cu@INUTIL.CU"
    ) in preview
    assert "auth_param negotiate children 10 startup=5 idle=3" in preview
    assert "auth_param negotiate keep_alive on" in preview
    assert "acl kerberos_auth proxy_auth REQUIRED" in preview
    assert "http_access deny !kerberos_auth" in preview
    assert "auth\\_param" not in preview
    assert "keep\\_alive" not in preview
    assert "\\@" not in preview


def test_service_principal_without_realm_is_supported_for_default_realm(
    kerberos_data,
):
    """The helper accepts a service/host name and resolves its default realm."""
    settings = kerberos.normalise_settings(
        {**kerberos_data, "service_principal": "HTTP/inutil.cu"}
    )

    assert settings.service_principal == "HTTP/inutil.cu"
    assert kerberos._keytab_contains_principal(
        "  1 HTTP/inutil.cu@INUTIL.CU", settings.service_principal
    )
    assert not kerberos._keytab_contains_principal(
        "  1 HTTP/inutil.cu2@INUTIL.CU", settings.service_principal
    )


def test_keytab_principal_requires_an_exact_realm_match(kerberos_data):
    """Realm case is part of a Kerberos principal, unlike the DNS hostname."""
    principal = kerberos_data["service_principal"]

    assert kerberos._keytab_contains_principal(
        "  1 HTTP/INUTIL.CU@INUTIL.CU", principal
    )
    assert not kerberos._keytab_contains_principal(
        "  1 HTTP/inutil.cu@inutil.cu", principal
    )


def test_dataclass_input_is_validated_before_rendering_or_writing():
    """Internal callers cannot bypass the squid.conf interpolation guard."""
    unsafe = kerberos.KerberosSettings(
        enabled=True,
        helper_path="/usr/lib/squid/helper\nauth_param basic program /tmp/evil",
        keytab_path="/etc/squid/HTTP.keytab",
        service_principal="HTTP/inutil.cu@INUTIL.CU",
    )

    with pytest.raises(kerberos.KerberosConfigurationError):
        kerberos.render_preview(unsafe)


def test_modular_apply_keeps_auth_and_access_rules_in_safe_modules(
    tmp_path, kerberos_data, no_host_squid
):
    """The helper/ACL and http_access rule have separate, ordered targets."""
    module_dir = tmp_path / "squid.d"
    main_content = (
        "http_port 3128\n"
        f"include {module_dir / '100_acls.conf'}\n"
        f"include {module_dir / '120_http_access.conf'}\n"
    )
    manager = _ConfigManager(
        tmp_path,
        main_content,
        modular=True,
        modules={
            "100_acls.conf": "acl localnet src 10.0.0.0/8\n",
            "120_http_access.conf": (
                "http_access allow manager localhost\n"
                "http_access deny manager\n"
                "http_access deny !Safe_ports\n"
                "http_access allow localnet\n"
                "http_access deny all\n"
            ),
        },
    )

    result = kerberos.apply_configuration(kerberos_data, manager)

    assert result["status"] == "warning"
    assert result["restart_required"] is True
    assert result["reload_required"] is True
    auth_content = manager.read_modular_config("50_auth.conf")
    access_content = manager.read_modular_config("120_http_access.conf")
    assert auth_content is not None
    assert access_content is not None
    assert "auth_param negotiate program" in auth_content
    assert "acl kerberos_auth proxy_auth REQUIRED" in auth_content
    assert "http_access" not in auth_content
    assert "http_access deny !Safe_ports" in access_content
    assert (
        access_content.index("http_access deny !Safe_ports")
        < access_content.index("http_access deny !kerberos_auth")
        < access_content.index("http_access allow localnet")
    )

    include_50 = f"include {module_dir / '50_auth.conf'}"
    include_100 = f"include {module_dir / '100_acls.conf'}"
    include_120 = f"include {module_dir / '120_http_access.conf'}"
    assert include_50 in manager.config_content
    assert manager.config_content.index(include_50) < manager.config_content.index(
        include_100
    ) < manager.config_content.index(include_120)


@pytest.mark.parametrize(
    ("quota_position", "case_name"),
    [
        (0, "before_manager"),
        (4, "after_client_allow"),
    ],
)
def test_apply_repositions_existing_proxy_auth_quota_rule_after_kerberos(
    tmp_path, kerberos_data, no_host_squid, quota_position, case_name
):
    """A pre-existing quota denial cannot preempt or bypass Kerberos."""
    http_rules = [
        "http_access allow manager localhost",
        "http_access deny manager",
        "http_access deny !Safe_ports",
        "http_access allow localnet",
        "http_access deny all",
    ]
    http_rules.insert(quota_position, "http_access deny usuarios_bloqueados")
    manager = _ConfigManager(
        tmp_path,
        "\n".join(
            [
                "http_port 3128",
                "acl usuarios_bloqueados proxy_auth -i /etc/squid/usuarios_bloqueados.txt",
                *http_rules,
                "",
            ]
        ),
    )

    kerberos.apply_configuration(kerberos_data, manager)

    content = manager.config_content
    quota_rule = "http_access deny usuarios_bloqueados"
    assert content.count(quota_rule) == 1, case_name
    assert content.index(kerberos.MANAGED_AUTH_START) < content.index(
        "acl usuarios_bloqueados proxy_auth"
    ), case_name
    assert (
        content.index("http_access allow manager localhost")
        < content.index("http_access deny !kerberos_auth")
        < content.index(kerberos.MANAGED_ACCESS_END)
        < content.index(quota_rule)
        < content.index("http_access allow localnet")
    ), case_name


def test_apply_does_not_reorder_ip_based_quota_rule(
    tmp_path, kerberos_data, no_host_squid
):
    """The quota fallback does not use proxy_auth and keeps its own policy."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "acl usuarios_bloqueados src 10.0.0.5\n"
            "http_access deny usuarios_bloqueados\n"
            "http_access allow manager localhost\n"
            "http_access deny manager\n"
            "http_access deny !Safe_ports\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )

    kerberos.apply_configuration(kerberos_data, manager)

    content = manager.config_content
    assert content.index("http_access deny usuarios_bloqueados") < content.index(
        "http_access allow manager localhost"
    )


def test_apply_rejects_a_broad_cache_manager_exception(
    tmp_path, kerberos_data, no_host_squid
):
    """A syntactically familiar exception must not bypass Kerberos for everyone."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "acl manager all\n"
            "acl localhost src 0.0.0.0/0\n"
            "http_access allow localhost manager\n"
            "http_access deny manager\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="ACL manager"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert kerberos.MANAGED_ACCESS_START not in manager.config_content


def test_modular_apply_repositions_active_proxy_auth_quota_rule(
    tmp_path, kerberos_data, no_host_squid
):
    """The quota ACL can live in the active ACL module, not just squid.conf."""
    module_dir = tmp_path / "squid.d"
    manager = _ConfigManager(
        tmp_path,
        (
            f"http_port 3128\ninclude {module_dir / '100_acls.conf'}\n"
            f"include {module_dir / '120_http_access.conf'}\n"
        ),
        modular=True,
        modules={
            "100_acls.conf": (
                "acl usuarios_bloqueados proxy_auth -i "
                "/etc/squid/usuarios_bloqueados.txt\n"
            ),
            "120_http_access.conf": (
                "http_access deny usuarios_bloqueados\n"
                "http_access allow manager localhost\n"
                "http_access deny manager\n"
                "http_access deny !Safe_ports\n"
                "http_access allow localnet\n"
                "http_access deny all\n"
            ),
        },
    )

    kerberos.apply_configuration(kerberos_data, manager)

    content = manager.read_modular_config("120_http_access.conf")
    assert content is not None
    assert manager.config_content.index(
        f"include {module_dir / '50_auth.conf'}"
    ) < manager.config_content.index(f"include {module_dir / '100_acls.conf'}")
    assert (
        content.index("http_access allow manager localhost")
        < content.index("http_access deny !kerberos_auth")
        < content.index("http_access deny usuarios_bloqueados")
        < content.index("http_access allow localnet")
    )


def test_modular_apply_writes_modules_before_including_them(
    tmp_path, kerberos_data, no_host_squid
):
    """A live Squid never sees a newly added include before its file exists."""
    module_dir = tmp_path / "squid.d"
    manager = _RecordingConfigManager(
        tmp_path,
        f"http_port 3128\ninclude {module_dir / '120_http_access.conf'}\n",
        modular=True,
        modules={
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            )
        },
    )

    kerberos.apply_configuration(kerberos_data, manager)

    assert manager.saved_targets.index("50_auth.conf") < manager.saved_targets.index(
        "squid.conf"
    )


def test_apply_is_idempotent_for_managed_modular_blocks(
    tmp_path, kerberos_data, no_host_squid
):
    """A second submission updates instead of duplicating Squid directives."""
    module_dir = tmp_path / "squid.d"
    manager = _ConfigManager(
        tmp_path,
        (f"http_port 3128\ninclude {module_dir / '120_http_access.conf'}\n"),
        modular=True,
        modules={
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            )
        },
    )

    kerberos.apply_configuration(kerberos_data, manager)
    kerberos.apply_configuration(kerberos_data, manager)

    auth_content = manager.read_modular_config("50_auth.conf")
    access_content = manager.read_modular_config("120_http_access.conf")
    assert auth_content is not None
    assert access_content is not None
    assert auth_content.count(kerberos.MANAGED_AUTH_START) == 1
    assert auth_content.count("auth_param negotiate program") == 1
    assert access_content.count(kerberos.MANAGED_ACCESS_START) == 1
    assert access_content.count("http_access deny !kerberos_auth") == 1
    assert manager.config_content.count(f"include {module_dir / '50_auth.conf'}") == 1


def test_relative_wildcard_include_is_not_duplicated(
    tmp_path, kerberos_data, no_host_squid
):
    """Relative Squid includes resolve from the directory of squid.conf."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/*.conf\n",
        modular=True,
        modules={
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            )
        },
    )

    kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content == "http_port 3128\ninclude squid.d/*.conf\n"


def test_modular_apply_rejects_http_access_in_an_unmanaged_include(
    tmp_path, kerberos_data, no_host_squid
):
    """A custom earlier allow rule must not bypass the generated challenge."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/*.conf\n",
        modular=True,
        modules={
            "90_site_access.conf": "http_access allow localnet\n",
            "120_http_access.conf": "http_access deny all\n",
        },
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="fuera"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.read_modular_config("50_auth.conf") is None
    assert manager.read_modular_config("120_http_access.conf") == "http_access deny all\n"


def test_apply_rejects_an_indirectly_loaded_auth_module(
    tmp_path, kerberos_data, no_host_squid
):
    """Do not add a duplicate direct include for a nested auth module."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "include squid.d/10_parent.conf\n"
            "include squid.d/120_http_access.conf\n"
        ),
        modular=True,
        modules={
            "10_parent.conf": "include 50_auth.conf\n",
            "50_auth.conf": "# existing auth module\n",
            "120_http_access.conf": "http_access allow localnet\nhttp_access deny all\n",
        },
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="include indirecto"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.read_modular_config("50_auth.conf") == "# existing auth module\n"


def test_apply_recognises_a_continued_wildcard_module_include(
    tmp_path, kerberos_data, no_host_squid
):
    """A continued include must not be duplicated while adding Kerberos."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\ninclude \\\n    squid.d/*.conf\n",
        modular=True,
        modules={
            "120_http_access.conf": "http_access allow localnet\nhttp_access deny all\n"
        },
    )

    kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content.count("include") == 1


def test_monolithic_apply_rejects_http_access_in_an_extensionless_include(
    tmp_path, kerberos_data, no_host_squid
):
    """An active custom include must not silently bypass the challenge."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/access_rules\nhttp_access deny all\n",
        modules={"access_rules": "http_access allow localnet\n"},
    )
    original = manager.config_content

    with pytest.raises(kerberos.KerberosConfigurationError, match="fuera de squid.conf"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content == original
    assert manager.read_modular_config("50_auth.conf") is None


def test_modular_apply_does_not_activate_a_stale_access_module(
    tmp_path, kerberos_data, no_host_squid
):
    """A conventional but inactive policy file must stay inactive."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/90_misc.conf\n",
        modular=True,
        modules={
            "90_misc.conf": "cache_mem 64 MB\n",
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            ),
        },
    )
    original = manager.config_content

    with pytest.raises(kerberos.KerberosConfigurationError, match="no está incluido"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content == original
    assert manager.read_modular_config("50_auth.conf") is None


def test_modular_apply_rejects_an_empty_active_access_module_before_main_policy(
    tmp_path, kerberos_data, no_host_squid
):
    """A generic editor must not be able to add an allow before main's challenge."""
    module_dir = tmp_path / "squid.d"
    manager = _ConfigManager(
        tmp_path,
        (
            f"http_port 3128\ninclude {module_dir / '120_http_access.conf'}\n"
            "http_access allow localnet\nhttp_access deny all\n"
        ),
        modular=True,
        modules={"120_http_access.conf": "# reserved by a legacy layout\n"},
    )
    original = manager.config_content

    with pytest.raises(kerberos.KerberosConfigurationError, match="Aunque esté vacío"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content == original
    assert manager.read_modular_config("50_auth.conf") is None


def test_apply_rejects_access_policy_with_later_security_deny(
    tmp_path, kerberos_data, no_host_squid
):
    """Do not put an allow rule ahead of a restriction it would bypass."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "acl localnet src 10.0.0.0/8\n"
            "acl blocked dstdomain .blocked.example\n"
            "http_access allow localnet\n"
            "http_access deny blocked\n"
            "http_access deny all\n"
        ),
    )
    original = manager.config_content

    with pytest.raises(kerberos.KerberosConfigurationError, match="denegaciones"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content == original
    assert kerberos.MANAGED_AUTH_START not in manager.config_content


def test_standalone_localhost_allow_does_not_bypass_kerberos(
    tmp_path, kerberos_data, no_host_squid
):
    """Only the Cache Manager exception remains before the challenge rule."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "http_access allow manager localhost\n"
            "http_access deny manager\n"
            "http_access deny !Safe_ports\n"
            "http_access allow localhost\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )

    kerberos.apply_configuration(kerberos_data, manager)

    content = manager.config_content
    assert (
        content.index("http_access deny !Safe_ports")
        < content.index("http_access deny !kerberos_auth")
        < content.index("http_access allow localhost")
    )


def test_negated_manager_allow_is_not_treated_as_a_management_exception(
    tmp_path, kerberos_data, no_host_squid
):
    """``allow !manager`` matches normal proxy traffic and needs Kerberos first."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "http_access deny !Safe_ports\n"
            "http_access allow !manager\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )

    kerberos.apply_configuration(kerberos_data, manager)

    content = manager.config_content
    assert (
        content.index("http_access deny !Safe_ports")
        < content.index("http_access deny !kerberos_auth")
        < content.index("http_access allow !manager")
    )


def test_remote_cache_manager_allow_is_not_treated_as_an_authentication_exception(
    tmp_path, kerberos_data, no_host_squid
):
    """Only the standard local Cache Manager exception may precede Kerberos."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "http_access allow manager\n"
            "http_access deny manager\n"
            "http_access deny !Safe_ports\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="denegaciones"):
        kerberos.apply_configuration(kerberos_data, manager)


def test_general_http_access_editor_cannot_break_a_managed_kerberos_rule(
    tmp_path, kerberos_data, no_host_squid
):
    """The generic rule editor keeps the dedicated authentication invariant."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )
    kerberos.apply_configuration(kerberos_data, manager)
    original = manager.config_content
    access_indices = [
        index
        for index, line in enumerate(manager.config_content.split("\n"))
        if line.startswith("http_access ")
    ]
    kerberos_rule_index = next(
        position
        for position, line_index in enumerate(access_indices)
        if manager.config_content.split("\n")[line_index]
        == "http_access deny !kerberos_auth"
    )

    assert delete_http_access(kerberos_rule_index, manager) == (
        False,
        "La regla Kerberos administrada se modifica desde Kerberos / SPNEGO, no desde HTTP Access.",
    )
    assert move_http_access(kerberos_rule_index, "down", manager)[0] is False
    assert manager.config_content == original


def test_apply_requires_a_client_authorization_rule_after_authentication(
    tmp_path, kerberos_data, no_host_squid
):
    """A challenge alone must not replace the site's access policy."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\nhttp_access deny !Safe_ports\nhttp_access deny all\n",
    )
    original = manager.config_content

    with pytest.raises(kerberos.KerberosConfigurationError, match="autorizarlos"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content == original


def test_apply_refuses_to_mix_an_existing_ntlm_helper(
    tmp_path, kerberos_data, no_host_squid
):
    """The user's NTLM alternative is not silently enabled with Kerberos."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "auth_param ntlm program /usr/bin/ntlm_auth --helper-protocol=squid-2.5-ntlmssp\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="alternativos"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert "auth_param negotiate program" not in manager.config_content
    assert kerberos.load_configuration(manager)["other_auth_schemes"] == ["ntlm"]


def test_apply_replaces_a_multiline_negotiate_configuration_as_one_directive(
    tmp_path, kerberos_data, no_host_squid
):
    """Replacing a reviewed helper cannot leave continuation arguments behind."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "auth_param negotiate program /opt/old-negotiate \\\n"
            "  -k /etc/squid/old.keytab -s HTTP/old.example@EXAMPLE\n"
            "auth_param negotiate children 3 startup=1 idle=1\n"
            "acl kerberos_auth proxy_auth REQUIRED\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )

    kerberos.apply_configuration(
        {**kerberos_data, "replace_existing_negotiate": True}, manager
    )

    assert "/opt/old-negotiate" not in manager.config_content
    assert "/etc/squid/old.keytab" not in manager.config_content
    assert manager.config_content.count("auth_param negotiate program") == 1
    assert manager.config_content.count("auth_param negotiate children") == 1


def test_apply_rejects_an_external_negotiate_directive_without_a_program(
    tmp_path, kerberos_data, no_host_squid
):
    """An external Negotiate setting can conflict even without its helper line."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/*.conf\n",
        modular=True,
        modules={
            "90_auth_options.conf": "auth_param negotiate keep_alive off\n",
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            ),
        },
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="fuera"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.read_modular_config("50_auth.conf") is None


def test_apply_does_not_duplicate_a_manual_acl_or_access_rule(
    tmp_path, kerberos_data, no_host_squid
):
    """Existing same-name policy needs an explicit, reviewable replacement."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "acl kerberos_auth proxy_auth REQUIRED\n"
            "http_access deny !kerberos_auth\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="ACL llamada"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content.count("acl kerberos_auth proxy_auth REQUIRED") == 1

    replaced = {**kerberos_data, "replace_existing_negotiate": True}
    kerberos.apply_configuration(replaced, manager)

    assert manager.config_content.count("acl kerberos_auth proxy_auth REQUIRED") == 1
    assert manager.config_content.count("http_access deny !kerberos_auth") == 1
    assert kerberos.MANAGED_AUTH_START in manager.config_content


def test_replace_finds_same_name_acl_in_the_standard_acl_module(
    tmp_path, kerberos_data, no_host_squid
):
    """Older modular layouts may keep proxy_auth ACLs in 100_acls.conf."""
    module_dir = tmp_path / "squid.d"
    manager = _ConfigManager(
        tmp_path,
        f"http_port 3128\ninclude {module_dir / '120_http_access.conf'}\n",
        modular=True,
        modules={
            "100_acls.conf": "acl kerberos_auth proxy_auth REQUIRED\n",
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            ),
        },
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="ACL llamada"):
        kerberos.apply_configuration(kerberos_data, manager)

    kerberos.apply_configuration(
        {**kerberos_data, "replace_existing_negotiate": True}, manager
    )

    assert "acl kerberos_auth proxy_auth REQUIRED" not in (
        manager.read_modular_config("100_acls.conf") or ""
    )
    assert "acl kerberos_auth proxy_auth REQUIRED" in (
        manager.read_modular_config("50_auth.conf") or ""
    )


def test_apply_rejects_a_same_name_acl_in_an_active_custom_include(
    tmp_path, kerberos_data, no_host_squid
):
    """A global Squid ACL name may not be reused from a custom module."""
    module_dir = tmp_path / "squid.d"
    custom_acl = "acl kerberos_auth src 10.0.0.0/8\n"
    manager = _ConfigManager(
        tmp_path,
        f"http_port 3128\ninclude {module_dir / '*.conf'}\n",
        modular=True,
        modules={
            "90_custom.conf": custom_acl,
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            ),
        },
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="90_custom.conf"):
        kerberos.apply_configuration(
            {**kerberos_data, "replace_existing_negotiate": True}, manager
        )

    assert manager.read_modular_config("90_custom.conf") == custom_acl
    assert manager.read_modular_config("50_auth.conf") is None


def test_disabling_removes_blocks_from_both_modular_targets(
    tmp_path, kerberos_data, no_host_squid
):
    """Removal must work even if the submitted form disables access enforcement."""
    module_dir = tmp_path / "squid.d"
    manager = _ConfigManager(
        tmp_path,
        (f"http_port 3128\ninclude {module_dir / '120_http_access.conf'}\n"),
        modular=True,
        modules={
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            )
        },
    )
    kerberos.apply_configuration(kerberos_data, manager)

    kerberos.apply_configuration(
        {"enabled": False, "enforce_auth": False, "reload_squid": False},
        manager,
    )

    auth_content = manager.read_modular_config("50_auth.conf")
    access_content = manager.read_modular_config("120_http_access.conf")
    assert auth_content is not None
    assert access_content is not None
    assert kerberos.MANAGED_AUTH_START not in auth_content
    assert kerberos.MANAGED_ACCESS_START not in access_content


def test_turning_off_enforcement_removes_an_existing_managed_access_block(
    tmp_path, kerberos_data, no_host_squid
):
    """Keeping the helper must not leave the previous challenge rule active."""
    module_dir = tmp_path / "squid.d"
    manager = _ConfigManager(
        tmp_path,
        f"http_port 3128\ninclude {module_dir / '120_http_access.conf'}\n",
        modular=True,
        modules={
            "120_http_access.conf": (
                "http_access allow localnet\nhttp_access deny all\n"
            )
        },
    )
    kerberos.apply_configuration(kerberos_data, manager)

    helper_only = {**kerberos_data, "enforce_auth": False}
    kerberos.apply_configuration(helper_only, manager)

    access_content = manager.read_modular_config("120_http_access.conf")
    assert access_content is not None
    assert kerberos.MANAGED_ACCESS_START not in access_content
    assert "http_access deny !kerberos_auth" not in access_content


def test_parse_failure_rolls_back_all_written_kerberos_changes(
    tmp_path, monkeypatch, kerberos_data, no_host_squid
):
    """An unsuccessful Squid parse leaves the configuration exactly as found."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "acl localnet src 10.0.0.0/8\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )
    original = manager.config_content
    monkeypatch.setattr(
        kerberos,
        "validate_squid_configuration",
        lambda *_args, **_kwargs: {
            "available": True,
            "valid": False,
            "message": "Squid rechazó la configuración.",
        },
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="restauró"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content == original
    assert Path(manager.config_path).read_text(encoding="utf-8") == original


def test_modular_proxy_auth_detection_supports_a_named_kerberos_acl(tmp_path):
    """Quota consumers must not fall back to IPs after a config is split."""
    module_dir = tmp_path / "squid.d"
    manager = _ConfigManager(
        tmp_path,
        f"http_port 3128\ninclude {module_dir / '50_auth.conf'}\n",
        modular=True,
        modules={
            "50_auth.conf": (
                "auth_param negotiate program /opt/squid/negotiate_kerberos_auth "
                "-k /etc/squid/HTTP.keytab -s HTTP/inutil.cu@INUTIL.CU\n"
                "acl kerberos_auth proxy_auth REQUIRED\n"
            )
        },
    )

    assert SquidConfigManager.has_proxy_authentication(manager) is True


def test_status_does_not_report_an_unincluded_auth_module_as_active(tmp_path):
    """A stale 50_auth.conf must not make the UI claim Kerberos is enabled."""
    module_dir = tmp_path / "squid.d"
    manager = _ConfigManager(
        tmp_path,
        f"http_port 3128\ninclude {module_dir / '120_http_access.conf'}\n",
        modular=True,
        modules={
            "50_auth.conf": (
                "# BEGIN SquidStats Kerberos authentication\n"
                "auth_param negotiate program /opt/squid/negotiate_kerberos_auth "
                "-k /etc/squid/HTTP.keytab -s HTTP/inutil.cu@INUTIL.CU\n"
                "acl kerberos_auth proxy_auth REQUIRED\n"
                "# END SquidStats Kerberos authentication\n"
            ),
            "120_http_access.conf": "http_access allow localnet\nhttp_access deny all\n",
        },
    )

    configuration = kerberos.load_configuration(manager)

    assert configuration["detected"] is False
    assert configuration["managed"] is False
    assert configuration["inactive_conventional_sources"] == ["50_auth.conf"]


def test_status_keeps_recovery_ui_available_for_an_incomplete_marker(tmp_path):
    """A broken hand edit must report an error instead of raising a page 500."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\n# BEGIN SquidStats Kerberos authentication\n",
    )

    status = kerberos.get_status(manager)

    assert status["configuration_error"]
    assert status["preflight"]["ready"] is False


def test_apply_rejects_an_unreadable_active_include(
    tmp_path, kerberos_data, no_host_squid
):
    """An undecodable active fragment must not be ignored during a write."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/site.conf\nhttp_access allow localnet\nhttp_access deny all\n",
    )
    active_include = Path(manager.config_dir) / "site.conf"
    active_include.write_bytes(b"\xff\xfe")
    original = manager.config_content

    with pytest.raises(kerberos.KerberosConfigurationError, match="no se pudo leer"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.config_content == original


def test_apply_does_not_replace_an_existing_unreadable_standard_module(
    tmp_path, kerberos_data, no_host_squid
):
    """A writable directory is not permission to replace unseen 50_auth.conf."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/*.conf\n",
        modular=True,
        modules={
            "50_auth.conf": "auth_param basic program /existing/helper\n",
            "120_http_access.conf": "http_access allow localnet\nhttp_access deny all\n",
        },
    )
    original = (Path(manager.config_dir) / "50_auth.conf").read_text(encoding="utf-8")
    read_module = manager.read_modular_config

    def unreadable_module(filename: str) -> str | None:
        return None if filename == "50_auth.conf" else read_module(filename)

    manager.read_modular_config = unreadable_module

    with pytest.raises(kerberos.KerberosConfigurationError, match="No se pudo leer"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert (Path(manager.config_dir) / "50_auth.conf").read_text(encoding="utf-8") == original


def test_proxy_mode_detects_intercept_on_https_port(tmp_path):
    """HTTPS listeners use the same incompatible interception modes."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\nhttps_port 3129 intercept\n",
    )

    proxy_mode = kerberos._proxy_mode_status(manager)

    assert proxy_mode["intercept_ports"] == 1
    assert proxy_mode["explicit_proxy_available"] is True


def test_proxy_mode_rejects_accelerator_only_listener(tmp_path):
    """An ``accel`` listener is reverse proxy mode, not a forward proxy."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128 accel defaultsite=proxy.example\n",
    )

    proxy_mode = kerberos._proxy_mode_status(manager)

    assert proxy_mode["reverse_proxy_ports"] == 1
    assert proxy_mode["incompatible_ports"] == 1
    assert proxy_mode["explicit_proxy_available"] is False


def test_proxy_mode_rejects_connection_auth_disabled_listener(tmp_path):
    """Negotiate requires connection-oriented authentication on the port."""
    manager = _ConfigManager(
        tmp_path,
        "https_port 3129 connection-auth=off\n",
    )

    proxy_mode = kerberos._proxy_mode_status(manager)

    assert proxy_mode["connection_auth_disabled_ports"] == 1
    assert proxy_mode["incompatible_ports"] == 1
    assert proxy_mode["explicit_proxy_available"] is False


def test_disabling_accepts_incomplete_form_values_for_recovery():
    """The disable button remains usable even after a bad form submission."""
    settings = kerberos.normalise_settings(
        {"enabled": False, "children": "not-a-number", "service_principal": ""}
    )

    assert settings.enabled is False


def test_docker_runtime_commands_never_pass_a_host_config_path():
    """Docker must parse its own mounted config, not a host-only pathname."""
    default_runtime = kerberos._SquidRuntime(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="squid_proxy",
    )
    custom_runtime = kerberos._SquidRuntime(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="squid_proxy",
        container_config_path="/etc/squid/custom.conf",
    )

    assert kerberos._squid_runtime_command(
        default_runtime, "parse", "/host/project/squid.conf"
    ) == ["/usr/bin/docker", "exec", "squid_proxy", "squid", "-k", "parse"]
    assert kerberos._squid_runtime_command(
        custom_runtime, "reconfigure", "/host/project/squid.conf"
    ) == [
        "/usr/bin/docker",
        "exec",
        "squid_proxy",
        "squid",
        "-f",
        "/etc/squid/custom.conf",
        "-k",
        "reconfigure",
    ]


def test_docker_validation_rejects_unmapped_host_config(monkeypatch, tmp_path):
    """A host path that is not mounted as Squid's container config must not run."""
    runtime = kerberos._SquidRuntime(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="squid_proxy",
        container_config_path="/etc/squid/squid.conf",
    )
    host_path = tmp_path / "squid.conf"
    host_path.write_text("http_port 3128\n", encoding="utf-8")

    monkeypatch.setattr(
        kerberos,
        "_docker_mounts",
        lambda _runtime: [(tmp_path / "other", PurePosixPath("/etc/squid/other.conf"))],
    )
    called = False

    def fail_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess.run should not be called when Docker config is unmapped")

    monkeypatch.setattr(kerberos.subprocess, "run", fail_run)

    result = kerberos.validate_squid_configuration(host_path, runtime)

    assert result["available"] is True
    assert result["valid"] is False
    assert "montado como el archivo cargado por el contenedor" in result["message"]
    assert called is False


def test_docker_reconfigure_rejects_unmapped_host_config(monkeypatch, tmp_path):
    """Reloads must stop before executing Docker when the mapped config is wrong."""
    runtime = kerberos._SquidRuntime(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="squid_proxy",
        container_config_path="/etc/squid/squid.conf",
    )
    host_path = tmp_path / "squid.conf"
    host_path.write_text("http_port 3128\n", encoding="utf-8")

    monkeypatch.setattr(
        kerberos,
        "_docker_mounts",
        lambda _runtime: [(tmp_path / "other", PurePosixPath("/etc/squid/other.conf"))],
    )
    called = False

    def fail_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess.run should not be called for an unmapped Docker config")

    monkeypatch.setattr(kerberos.subprocess, "run", fail_run)

    ok, message = kerberos.reconfigure_squid(host_path, runtime)

    assert ok is False
    assert "montado como el archivo cargado por el contenedor" in message
    assert called is False


def test_docker_apply_uses_a_relative_include_visible_to_host_and_container(
    tmp_path, kerberos_data, monkeypatch
):
    """A generated include must remain readable after the host app restarts."""
    module_dir = tmp_path / "squid.d"
    manager = _RecordingConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/120_http_access.conf\n",
        modular=True,
        modules={
            "120_http_access.conf": "http_access allow localnet\nhttp_access deny all\n"
        },
    )
    runtime = kerberos._SquidRuntime(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="squid_proxy",
        container_config_path="/etc/squid/squid.conf",
    )
    monkeypatch.setattr(kerberos, "_find_squid_runtime", lambda: runtime)
    monkeypatch.setattr(
        kerberos,
        "_docker_mounts",
        lambda _runtime: [
            (Path(manager.config_path), PurePosixPath("/etc/squid/squid.conf")),
            (module_dir, PurePosixPath("/etc/squid/squid.d")),
        ],
    )
    monkeypatch.setattr(
        kerberos,
        "_validate_prerequisites",
        lambda *_args, **_kwargs: {"config": {"writable": True}},
    )
    monkeypatch.setattr(
        kerberos,
        "validate_squid_configuration",
        lambda *_args, **_kwargs: {
            "available": True,
            "valid": True,
            "message": "Configuración validada.",
        },
    )

    kerberos.apply_configuration(kerberos_data, manager)

    assert "include squid.d/50_auth.conf" in manager.config_content
    assert str(module_dir / "50_auth.conf") not in manager.config_content


def test_docker_apply_refuses_an_unmapped_changed_module(
    tmp_path, kerberos_data, monkeypatch
):
    """Do not write host-only module changes that the container cannot load."""
    manager = _RecordingConfigManager(
        tmp_path,
        "http_port 3128\ninclude squid.d/120_http_access.conf\n",
        modular=True,
        modules={
            "120_http_access.conf": "http_access allow localnet\nhttp_access deny all\n"
        },
    )
    runtime = kerberos._SquidRuntime(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="squid_proxy",
        container_config_path="/etc/squid/squid.conf",
    )
    monkeypatch.setattr(kerberos, "_find_squid_runtime", lambda: runtime)
    monkeypatch.setattr(
        kerberos,
        "_docker_mounts",
        lambda _runtime: [
            (Path(manager.config_path), PurePosixPath("/etc/squid/squid.conf"))
        ],
    )
    monkeypatch.setattr(
        kerberos,
        "_validate_prerequisites",
        lambda *_args, **_kwargs: {"config": {"writable": True}},
    )

    with pytest.raises(kerberos.KerberosConfigurationError, match="ruta Docker segura"):
        kerberos.apply_configuration(kerberos_data, manager)

    assert manager.saved_targets == []


def test_docker_preflight_checks_helper_and_keytab_inside_the_container(
    tmp_path, kerberos_data, monkeypatch
):
    """The host does not need to see container-only Kerberos paths."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "cache_effective_user proxy\n"
            "http_access allow localnet\n"
            "http_access deny all\n"
        ),
    )
    runtime = kerberos._SquidRuntime(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="squid_proxy",
        container_config_path="/etc/squid/squid.conf",
    )
    seen_tests: list[tuple[str, str, str | None]] = []

    def docker_test(_runtime, option, path, *, user=None):
        seen_tests.append((option, path, user))
        return True

    monkeypatch.setattr(kerberos, "_docker_test", docker_test)
    def docker_exec(_runtime, arguments, **_kwargs):
        if arguments == ["squid", "-v"]:
            output = "Squid Cache: Version 7.7\n"
        elif arguments[:3] == ["stat", "-c", "%a"]:
            output = "0640\n"
        else:
            output = "HTTP/inutil.cu@INUTIL.CU\n"
        return CompletedProcess(
            args=arguments, returncode=0, stdout=output, stderr=""
        )

    monkeypatch.setattr(kerberos, "_docker_exec", docker_exec)
    monkeypatch.setattr(
        kerberos,
        "_docker_mounts",
        lambda _runtime: [
            (Path(manager.config_path), PurePosixPath("/etc/squid/squid.conf"))
        ],
    )

    preflight = kerberos.get_preflight(
        manager, kerberos.normalise_settings(kerberos_data), runtime
    )

    assert preflight["ready"] is True
    assert preflight["runtime"] == {
        "available": True,
        "kind": "docker",
        "container": "squid_proxy",
    }
    assert preflight["helper"]["checked_in_runtime"] is True
    assert preflight["keytab"]["checked_in_runtime"] is True
    assert preflight["squid_version"]["version"] == "7.7"
    assert ("-r", "/var/run/squid/HTTP.keytab", "proxy") in seen_tests


def test_preflight_uses_a_detected_compiled_default_squid_user(
    tmp_path, kerberos_data, monkeypatch
):
    """A normal package default still permits a meaningful permissions check."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\nhttp_access allow localnet\nhttp_access deny all\n",
    )
    runtime = kerberos._SquidRuntime(kind="local", executable="/usr/sbin/squid")
    checked_users: list[str | None] = []
    monkeypatch.setattr(
        kerberos,
        "_squid_version_status",
        lambda _runtime: {
            "checked": True,
            "version": "7.7",
            "supports_auth_param": True,
            "default_user": "proxy",
        },
    )
    monkeypatch.setattr(
        kerberos,
        "_helper_status",
        lambda _path, _runtime, user: {
            "check_available": True,
            "exists": True,
            "executable": True,
            "squid_user": user,
        },
    )

    def keytab_status(_path, _principal, user, _runtime):
        checked_users.append(user)
        return {
            "check_available": True,
            "exists": True,
            "regular_file": True,
            "application_readable": True,
            "checked_in_runtime": False,
            "squid_user": user,
            "squid_user_readable": True,
            "world_readable": False,
            "spn_checked": True,
            "spn_present": True,
        }

    monkeypatch.setattr(kerberos, "_keytab_status", keytab_status)

    preflight = kerberos.get_preflight(
        manager, kerberos.normalise_settings(kerberos_data), runtime
    )

    assert preflight["squid_user"] == "proxy"
    assert preflight["squid_user_source"] == "build_default"
    assert checked_users == ["proxy"]
    assert any("predeterminado compilado" in warning for warning in preflight["warnings"])


@pytest.mark.parametrize(
    "version_output, expected_user",
    [
        ("--with-default-user=proxy", "proxy"),
        ("'--with-default-user=\"squid\"'", "squid"),
        ("--with-default-user=not/a/user", None),
    ],
)
def test_default_squid_user_parser_accepts_only_safe_users(version_output, expected_user):
    assert kerberos._default_squid_user(version_output) == expected_user


def test_preflight_requires_an_identifiable_squid_user(
    tmp_path, kerberos_data, monkeypatch
):
    """Do not claim a keytab is ready when Squid's account is unknown."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\nhttp_access allow localnet\nhttp_access deny all\n",
    )
    runtime = kerberos._SquidRuntime(kind="local", executable="/usr/sbin/squid")
    monkeypatch.setattr(
        kerberos,
        "_squid_version_status",
        lambda _runtime: {
            "checked": True,
            "version": "7.7",
            "supports_auth_param": True,
            "default_user": None,
        },
    )
    monkeypatch.setattr(
        kerberos,
        "_helper_status",
        lambda *_args: {
            "check_available": True,
            "exists": True,
            "executable": True,
        },
    )
    monkeypatch.setattr(
        kerberos,
        "_keytab_status",
        lambda *_args: {
            "check_available": True,
            "exists": True,
            "regular_file": True,
            "application_readable": True,
            "checked_in_runtime": False,
            "squid_user": None,
            "squid_user_readable": None,
            "world_readable": False,
            "spn_checked": True,
            "spn_present": True,
        },
    )

    preflight = kerberos.get_preflight(
        manager, kerberos.normalise_settings(kerberos_data), runtime
    )

    assert preflight["ready"] is False
    assert any("usuario efectivo de Squid" in error for error in preflight["errors"])


def test_preflight_rejects_an_unavailable_explicit_runtime_even_without_reload(
    tmp_path, kerberos_data, monkeypatch
):
    """Manual reload does not make an explicitly selected absent runtime safe."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\nhttp_access allow localnet\nhttp_access deny all\n",
    )
    monkeypatch.setenv("SQUID_RUNTIME", "docker")
    monkeypatch.setattr(kerberos, "_find_squid_runtime", lambda: None)
    monkeypatch.setattr(kerberos, "_docker_runtime", lambda: None)

    preflight = kerberos.get_preflight(
        manager,
        kerberos.normalise_settings({**kerberos_data, "reload_squid": False}),
    )

    assert preflight["ready"] is False
    assert any("SQUID_RUNTIME=docker" in error for error in preflight["errors"])


def test_preflight_rejects_a_keytab_writable_by_its_group(
    tmp_path, kerberos_data, monkeypatch
):
    """A secret key must not be modifiable by non-owner accounts."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\ncache_effective_user proxy\n"
            "http_access allow localnet\nhttp_access deny all\n"
        ),
    )
    runtime = kerberos._SquidRuntime(kind="local", executable="/usr/sbin/squid")
    monkeypatch.setattr(
        kerberos,
        "_squid_version_status",
        lambda _runtime: {
            "checked": True,
            "version": "7.7",
            "supports_auth_param": True,
            "default_user": None,
        },
    )
    monkeypatch.setattr(
        kerberos,
        "_helper_status",
        lambda *_args: {
            "check_available": True,
            "exists": True,
            "executable": True,
        },
    )
    monkeypatch.setattr(
        kerberos,
        "_keytab_status",
        lambda *_args: {
            "check_available": True,
            "exists": True,
            "regular_file": True,
            "application_readable": True,
            "checked_in_runtime": False,
            "squid_user": "proxy",
            "squid_user_readable": True,
            "world_readable": False,
            "group_writable": True,
            "world_writable": False,
            "spn_checked": True,
            "spn_present": True,
        },
    )

    preflight = kerberos.get_preflight(
        manager, kerberos.normalise_settings(kerberos_data), runtime
    )

    assert preflight["ready"] is False
    assert any("modificable" in error for error in preflight["errors"])


def test_preflight_rejects_squid_v8_auth_param_configuration(
    tmp_path, kerberos_data, monkeypatch
):
    """Squid v8 removes the auth_param directive used by this feature."""
    manager = _ConfigManager(
        tmp_path,
        "http_port 3128\nhttp_access allow localnet\nhttp_access deny all\n",
    )
    runtime = kerberos._SquidRuntime(kind="local", executable="/usr/sbin/squid")
    monkeypatch.setattr(
        kerberos,
        "_helper_status",
        lambda *_args: {
            "check_available": True,
            "exists": True,
            "executable": True,
        },
    )
    monkeypatch.setattr(
        kerberos,
        "_keytab_status",
        lambda *_args: {
            "check_available": True,
            "exists": True,
            "regular_file": True,
            "application_readable": True,
            "checked_in_runtime": False,
            "squid_user": None,
            "squid_user_readable": None,
            "world_readable": False,
            "spn_checked": True,
            "spn_present": True,
        },
    )
    monkeypatch.setattr(
        kerberos,
        "_squid_version_status",
        lambda _runtime: {
            "checked": True,
            "version": "8.0",
            "supports_auth_param": False,
        },
    )

    preflight = kerberos.get_preflight(
        manager, kerberos.normalise_settings(kerberos_data), runtime
    )

    assert any("v8" in error for error in preflight["errors"])


def test_disabling_uses_the_same_selected_runtime_for_validation(
    tmp_path, monkeypatch
):
    """A Docker preference must also apply while removing managed blocks."""
    manager = _ConfigManager(
        tmp_path,
        (
            "http_port 3128\n"
            "# BEGIN SquidStats Kerberos authentication\n"
            "# END SquidStats Kerberos authentication\n"
        ),
    )
    runtime = kerberos._SquidRuntime(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="squid_proxy",
        container_config_path="/etc/squid/squid.conf",
    )
    seen_runtime = None

    def validate(_path, received_runtime):
        nonlocal seen_runtime
        seen_runtime = received_runtime
        return {"available": True, "valid": True, "message": "Configuración validada."}

    monkeypatch.setattr(kerberos, "_find_squid_runtime", lambda: runtime)
    monkeypatch.setattr(kerberos, "validate_squid_configuration", validate)
    monkeypatch.setattr(
        kerberos,
        "_docker_mounts",
        lambda _runtime: [
            (Path(manager.config_path), PurePosixPath("/etc/squid/squid.conf"))
        ],
    )

    kerberos.apply_configuration({"enabled": False}, manager)

    assert seen_runtime is runtime


def test_debian_manual_write_mode_reports_preview_only_and_blocks_all_writes(
    tmp_path, monkeypatch
):
    """A hardened package must fail before even a disable operation writes."""
    original = (
        "http_port 3128\n"
        "# BEGIN SquidStats Kerberos authentication\n"
        "# END SquidStats Kerberos authentication\n"
    )
    manager = _RecordingConfigManager(tmp_path, original)
    monkeypatch.setenv(kerberos._SQUID_CONFIG_WRITE_MODE_ENV, "manual")
    monkeypatch.setattr(kerberos, "_find_squid_runtime", lambda: None)
    monkeypatch.setattr(
        kerberos,
        "_squid_version_status",
        lambda _runtime: {
            "checked": False,
            "version": None,
            "supports_auth_param": None,
            "default_user": None,
        },
    )

    preflight = kerberos.get_preflight(
        manager, kerberos.normalise_settings({"enabled": False})
    )

    assert preflight["config"]["write_mode"] == "manual"
    assert preflight["config"]["writable"] is False
    assert any("modo manual" in error for error in preflight["errors"])

    with pytest.raises(kerberos.KerberosConfigurationError, match="modo manual"):
        kerberos.apply_configuration({"enabled": False}, manager)

    assert manager.saved_targets == []
    assert manager.config_content == original


def test_manual_write_mode_explains_the_block_even_if_unix_checks_are_invalid(
    tmp_path, monkeypatch
):
    """ProtectSystem commonly makes the manager fail its Unix W_OK check."""
    manager = _RecordingConfigManager(tmp_path, "http_port 3128\n")
    manager.is_valid = False
    monkeypatch.setenv(kerberos._SQUID_CONFIG_WRITE_MODE_ENV, "manual")

    with pytest.raises(kerberos.KerberosConfigurationError, match="modo manual"):
        kerberos._apply_configuration({"enabled": False}, manager)

    assert manager.saved_targets == []


@pytest.mark.parametrize(
    ("configured_mode", "expected_mode"),
    [(None, "managed"), ("managed", "managed"), ("manual", "manual"), ("typo", "manual")],
)
def test_squid_config_write_mode_fails_closed_for_unrecognised_values(
    monkeypatch, configured_mode, expected_mode
):
    if configured_mode is None:
        monkeypatch.delenv(kerberos._SQUID_CONFIG_WRITE_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(kerberos._SQUID_CONFIG_WRITE_MODE_ENV, configured_mode)

    assert kerberos._squid_config_write_mode() == expected_mode


def test_debian_unit_declares_manual_squid_write_mode():
    unit = (Path(__file__).parents[1] / "debian" / "squidstats.service").read_text(
        encoding="utf-8"
    )

    assert "ProtectSystem=full" in unit
    assert "Environment=SQUIDSTATS_SQUID_CONFIG_WRITE_MODE=manual" in unit


@pytest.mark.parametrize(
    "field, value",
    [
        ("helper_path", "/usr/lib/squid/helper\nauth_param basic program evil"),
        ("keytab_path", "/etc/squid/key tab"),
        ("service_principal", "HTTP/inutil.cu\\@INUTIL.CU"),
        ("acl_name", "kerberos auth"),
        ("acl_name", "all"),
    ],
)
def test_enabled_configuration_rejects_values_that_could_change_squid_syntax(
    kerberos_data, field, value
):
    """Form values are not interpolated into squid.conf until strictly validated."""
    with pytest.raises(kerberos.KerberosConfigurationError):
        kerberos.normalise_settings({**kerberos_data, field: value})


def test_kerberos_admin_frontend_and_preview_api_require_admin(client):
    """The configuration UI exposes all fields only to administrators."""
    client.application.jinja_env.globals["csrf_token"] = lambda: "test-token"
    assert client.get("/admin/api/kerberos/status").status_code == 401

    with patch(
        "services.auth.auth_service.AuthService.get_current_user",
        return_value={"role": "user"},
    ):
        assert client.get("/admin/api/kerberos/status").status_code == 403

    with patch(
        "services.auth.auth_service.AuthService.get_current_user",
        return_value={"role": "admin", "username": "admin"},
    ):
        page = client.get("/admin/kerberos-config")
        preview = client.post(
            "/admin/api/kerberos/preview",
            json={
                "enabled": True,
                "helper_path": "/usr/lib/squid/negotiate_kerberos_auth",
                "keytab_path": "/etc/squid/HTTP.keytab",
                "service_principal": "HTTP/inutil.cu@INUTIL.CU",
                "enforce_auth": True,
            },
        )

    assert page.status_code == 200
    assert b"service_principal" in page.data
    assert b"keytab_path" in page.data
    assert preview.status_code == 200
    assert preview.headers["Cache-Control"] == "private, no-cache"
    assert preview.headers["X-Content-Type-Options"] == "nosniff"
    assert preview.get_json()["preview"].endswith(
        "# END SquidStats Kerberos access rule\n"
    )


def test_split_config_apis_require_an_administrator(client):
    """A normal authenticated user must not rewrite Squid around Kerberos."""
    assert client.post("/admin/api/split-config", json={}).status_code == 401
    assert client.get("/admin/api/get-split-files").status_code == 401

    with patch(
        "services.auth.auth_service.AuthService.get_current_user",
        return_value={"role": "user", "username": "operator"},
    ):
        assert client.post("/admin/api/split-config", json={}).status_code == 403
        assert client.get("/admin/api/get-split-files").status_code == 403


def test_kerberos_frontend_shows_config_source_and_docker_mount_status(client):
    """Admin diagnostics distinguish a Docker mount mismatch from a valid config."""
    client.application.jinja_env.globals["csrf_token"] = lambda: "test-token"
    status = {
        "settings": kerberos.default_settings().to_dict(),
        "detected": True,
        "managed": False,
        "source": "/etc/squid/conf.d/custom & <manual>.conf",
        "unmanaged_negotiate": True,
        "other_auth_schemes": [],
        "inactive_conventional_sources": ["50_auth.conf"],
        "configuration_error": None,
        "preview": "# preview\n",
        "preflight": {
            "ready": False,
            "errors": [],
            "warnings": [],
            "config": {
                "path": "/srv/squid/squid.conf",
                "writable": True,
                "write_mode": "manual",
                "modular": True,
            },
            "helper": None,
            "keytab": None,
            "proxy_mode": {"explicit_proxy_available": True},
            "squid_user": "proxy",
            "runtime": {
                "available": True,
                "kind": "docker",
                "container": "squid_proxy",
            },
            "docker_config": {
                "checked": True,
                "mapped": False,
                "container_config_path": "/etc/squid/squid.conf",
                "container_path": "/etc/squid/other.conf",
                "symlink": True,
            },
            "squid_version": {
                "checked": True,
                "version": "7.7",
                "supports_auth_param": True,
            },
            "squid_binary_available": True,
        },
    }

    with (
        patch(
            "services.auth.auth_service.AuthService.get_current_user",
            return_value={"role": "admin", "username": "admin"},
        ),
        patch("routes.admin.kerberos_config.get_status", return_value=status),
    ):
        page = client.get("/admin/kerberos-config")
        api = client.get("/admin/api/kerberos/status")

    page_text = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Fuente Kerberos" in page_text
    assert "custom &amp; &lt;manual&gt;.conf" in page_text
    assert "custom &lt;manual&gt;.conf" not in page_text
    assert "módulos que no están incluidos activamente" in page_text
    assert "50_auth.conf" in page_text
    assert "Destino administrado" in page_text
    assert "50_auth.conf + 120_http_access.conf" in page_text
    assert "Solo manual" in page_text
    assert "Este despliegue está en modo manual para squid.conf" in page_text
    assert 'disabled aria-disabled="true"' in page_text
    assert "Montaje Docker" in page_text
    assert "No coincide" in page_text
    assert "/etc/squid/other.conf" in page_text
    assert "enlace simbólico" in page_text
    assert api.status_code == 200
    assert api.headers["Cache-Control"] == "private, no-cache"
    assert api.headers["X-Content-Type-Options"] == "nosniff"
    assert api.get_json()["kerberos"]["preflight"]["docker_config"]["mapped"] is False
