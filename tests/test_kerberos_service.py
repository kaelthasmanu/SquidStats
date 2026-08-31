"""Tests for the transactional Squid Kerberos configuration workflow."""

from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.squid import kerberos_service as service


class PanelStructureParser(HTMLParser):
    """Records the IDs that contain each element with an ID."""

    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__()
        self.stack = []
        self.parent_ids = {}

    def handle_starttag(self, tag, attrs):
        element_id = dict(attrs).get("id")
        if element_id:
            self.parent_ids[element_id] = tuple(
                item[1] for item in self.stack if item[1]
            )
        if tag not in self._VOID_TAGS:
            self.stack.append((tag, element_id))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


class FakeConfigManager:
    def __init__(self, config_path, config_dir, *, modular=False):
        self.config_path = str(config_path)
        self.config_dir = str(config_dir)
        self.is_modular = modular
        self.is_valid = True
        self.errors = []
        self.config_content = config_path.read_text(encoding="utf-8")

    def save_config(self, content):
        with open(self.config_path, "w", encoding="utf-8") as config_file:
            config_file.write(content)
        self.config_content = content
        return True

    def save_modular_config(self, filename, content):
        with open(
            f"{self.config_dir}/{filename}", "w", encoding="utf-8"
        ) as config_file:
            config_file.write(content)
        return True


def _upload(filename="HTTP.keytab", content=b"valid keytab"):
    return SimpleNamespace(filename=filename, stream=BytesIO(content))


def _prepare(monkeypatch, tmp_path, config_content="http_access deny all\n"):
    config_path = tmp_path / "squid.conf"
    config_path.write_text(config_content, encoding="utf-8")
    keytab_path = tmp_path / "HTTP.keytab"
    monkeypatch.setattr(service.Config, "SQUID_KERBEROS_KEYTAB_PATH", str(keytab_path))
    monkeypatch.setattr(service, "_squid_binary", lambda: "/usr/sbin/squid")
    monkeypatch.setattr(service, "_get_proxy_ids", lambda: (1000, 1000))
    monkeypatch.setattr(service.os, "chown", lambda *_args: None)
    monkeypatch.setattr(
        service,
        "_keytab_permissions",
        lambda _path: {
            "exists": True,
            "mode": "0440",
            "owner": "proxy",
            "group": "proxy",
            "permissions_ok": True,
        },
    )
    monkeypatch.setattr(service, "verify_keytab_readable", lambda _path: (True, ""))
    manager = FakeConfigManager(config_path, tmp_path / "squid.d")
    return manager, config_path, keytab_path


def test_configure_requires_a_keytab(monkeypatch, tmp_path):
    manager, _config_path, _keytab_path = _prepare(monkeypatch, tmp_path)

    with pytest.raises(service.KeytabRequiredError):
        service.configure(None, manager)


def test_configure_refuses_to_start_when_squid_is_not_installed(monkeypatch, tmp_path):
    manager, _config_path, keytab_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(service, "_squid_binary", lambda: None)

    with pytest.raises(
        service.SquidNotInstalledError,
        match="KERBEROS_ERROR_SQUID_NOT_INSTALLED",
    ):
        service.configure(_upload(), manager)

    assert not keytab_path.exists()


def test_runtime_prefers_local_squid_without_querying_docker(monkeypatch):
    monkeypatch.setattr(service, "_squid_binary", lambda: "/usr/sbin/squid")

    def docker_must_not_be_queried():
        raise AssertionError("Docker must not be queried when Squid is local")

    monkeypatch.setattr(
        service, "_find_docker_squid_container", docker_must_not_be_queried
    )

    runtime = service.get_squid_runtime()

    assert runtime["kind"] == "local"
    assert runtime["local_squid"] is True
    assert runtime["docker_container"] is None


@pytest.mark.parametrize(
    ("name", "ports"),
    [
        ("squid_proxy", "0.0.0.0:3129->3129/tcp"),
        ("proxy", "0.0.0.0:3128->3128/tcp, [::]:3128->3128/tcp"),
    ],
)
def test_runtime_detects_running_docker_squid_by_name_or_port(monkeypatch, name, ports):
    monkeypatch.setattr(service, "_squid_binary", lambda: None)
    monkeypatch.setattr(service, "_docker_binary", lambda: "/usr/bin/docker")
    monkeypatch.setattr(
        service,
        "_run",
        lambda command: (
            command
            == ["/usr/bin/docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Ports}}"],
            f"6101536dbb43\t{name}\t{ports}",
        ),
    )

    runtime = service.get_squid_runtime()

    assert runtime["kind"] == "docker"
    assert runtime["local_squid"] is False
    assert runtime["docker_container"]["id"] == "6101536dbb43"
    assert runtime["docker_container"]["name"] == name
    assert runtime["message"] == "KERBEROS_STATUS_DOCKER_SQUID_FOUND"


def test_runtime_reports_no_local_or_docker_squid(monkeypatch):
    monkeypatch.setattr(service, "_squid_binary", lambda: None)
    monkeypatch.setattr(service, "_docker_binary", lambda: None)

    runtime = service.get_squid_runtime()

    assert runtime["kind"] == "none"
    assert runtime["local_squid"] is False
    assert runtime["message"] == "KERBEROS_ERROR_SQUID_NOT_FOUND"


def test_configure_applies_keytab_and_squid_directives(monkeypatch, tmp_path):
    manager, config_path, keytab_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        service, "_validate_squid_configuration", lambda _bin: (True, "")
    )

    result = service.configure(_upload(), manager)

    assert result["status"] == "success"
    assert keytab_path.read_bytes() == b"valid keytab"
    content = config_path.read_text(encoding="utf-8")
    assert "negotiate_kerberos_auth" in content
    assert "http_access allow auth" in content
    assert content.index("http_access allow auth") < content.index(
        "http_access deny all"
    )


def test_configure_copies_keytab_from_an_absolute_host_path(monkeypatch, tmp_path):
    manager, _config_path, keytab_path = _prepare(monkeypatch, tmp_path)
    source_path = tmp_path / "host.keytab"
    source_path.write_bytes(b"keytab from host")
    monkeypatch.setattr(
        service, "_validate_squid_configuration", lambda _bin: (True, "")
    )

    service.configure(None, manager, host_keytab_path=str(source_path))

    assert keytab_path.read_bytes() == b"keytab from host"


def test_configure_rejects_a_relative_host_keytab_path(monkeypatch, tmp_path):
    manager, _config_path, _keytab_path = _prepare(monkeypatch, tmp_path)

    with pytest.raises(
        service.KerberosConfigurationError,
        match="KERBEROS_ERROR_HOST_KEYTAB_PATH_INVALID",
    ):
        service.configure(None, manager, host_keytab_path="HTTP.keytab")


def _docker_runtime():
    return {
        "kind": "docker",
        "local_squid": False,
        "docker_container": {
            "id": "6101536dbb43",
            "name": "squid_proxy",
            "ports": "0.0.0.0:3128->3128/tcp",
        },
    }


def _docker_runner(commands, deployed_config, *, parse_succeeds=True):
    container_id = "6101536dbb43"
    keytab_present = False

    def run(command):
        nonlocal keytab_present
        commands.append(command)
        if command[1] == "cp":
            source, destination = command[2:]
            if source == f"{container_id}:{service.DOCKER_SQUID_CONFIG_PATH}":
                Path(destination).write_text("http_access deny all\n", encoding="utf-8")
            elif destination == f"{container_id}:{service.DOCKER_SQUID_KEYTAB_PATH}":
                keytab_present = True
            elif destination == f"{container_id}:{service.DOCKER_SQUID_CONFIG_PATH}":
                deployed_config.append(Path(source).read_text(encoding="utf-8"))
            return True, ""

        arguments = command[2:]
        if arguments == [container_id, "test", "-f", service.DOCKER_SQUID_CONFIG_PATH]:
            return True, ""
        if arguments == [container_id, "test", "-f", service.DOCKER_SQUID_KEYTAB_PATH]:
            return keytab_present, ""
        if arguments == [
            container_id,
            "stat",
            "-c",
            "%a:%U:%G",
            service.DOCKER_SQUID_KEYTAB_PATH,
        ]:
            return True, "440:proxy:proxy"
        if arguments == [
            "--user",
            "proxy",
            container_id,
            "klist",
            "-k",
            service.DOCKER_SQUID_KEYTAB_PATH,
        ]:
            return True, "HTTP/proxy.example.test@EXAMPLE.TEST"
        if arguments == [container_id, "squid", "-k", "parse"]:
            return parse_succeeds, "invalid directive" if not parse_succeeds else ""
        if arguments == [container_id, "rm", "-f", service.DOCKER_SQUID_KEYTAB_PATH]:
            keytab_present = False
            return True, ""
        return True, ""

    return run


def test_configure_docker_copies_keytab_and_validates_container(monkeypatch):
    commands = []
    deployed_config = []
    monkeypatch.setattr(service, "_docker_binary", lambda: "/usr/bin/docker")
    monkeypatch.setattr(
        service,
        "_run",
        _docker_runner(commands, deployed_config),
    )

    result = service.configure(_upload(), squid_runtime=_docker_runtime())

    assert result["status"] == "success"
    assert result["keytab_path"] == "/etc/squid/HTTP.keytab"
    keytab_copies = [
        command
        for command in commands
        if command[1] == "cp" and command[-1] == "6101536dbb43:/etc/squid/HTTP.keytab"
    ]
    assert len(keytab_copies) == 1
    assert Path(keytab_copies[0][2]).name == "HTTP.keytab"
    assert any(
        command[1] == "cp" and command[-1] == "6101536dbb43:/etc/squid/squid.conf"
        for command in commands
    )
    assert [
        "/usr/bin/docker",
        "exec",
        "6101536dbb43",
        "chown",
        "proxy:proxy",
        "/etc/squid/HTTP.keytab",
    ] in commands
    assert [
        "/usr/bin/docker",
        "exec",
        "--user",
        "proxy",
        "6101536dbb43",
        "klist",
        "-k",
        "/etc/squid/HTTP.keytab",
    ] in commands
    assert [
        "/usr/bin/docker",
        "exec",
        "6101536dbb43",
        "squid",
        "-k",
        "parse",
    ] in commands
    assert service.KERBEROS_CONFIG_START in deployed_config[-1]


def test_configure_docker_restores_files_when_squid_parse_fails(monkeypatch):
    commands = []
    deployed_config = []
    monkeypatch.setattr(service, "_docker_binary", lambda: "/usr/bin/docker")
    monkeypatch.setattr(
        service,
        "_run",
        _docker_runner(commands, deployed_config, parse_succeeds=False),
    )

    with pytest.raises(
        service.KerberosConfigurationError,
        match="KERBEROS_ERROR_SQUID_CONFIG_INVALID",
    ):
        service.configure(_upload(), squid_runtime=_docker_runtime())

    assert len(deployed_config) == 2
    assert deployed_config[-1] == "http_access deny all\n"
    assert [
        "/usr/bin/docker",
        "exec",
        "6101536dbb43",
        "rm",
        "-f",
        "/etc/squid/HTTP.keytab",
    ] in commands


def test_configure_rolls_back_when_squid_parse_fails(monkeypatch, tmp_path):
    manager, config_path, keytab_path = _prepare(monkeypatch, tmp_path)
    original_config = config_path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        service,
        "_validate_squid_configuration",
        lambda _bin: (False, "parse error"),
    )

    with pytest.raises(
        service.KerberosConfigurationError,
        match="KERBEROS_ERROR_SQUID_CONFIG_INVALID",
    ):
        service.configure(_upload(), manager)

    assert config_path.read_text(encoding="utf-8") == original_config
    assert not keytab_path.exists()


def test_configure_rejects_non_keytab_extension(monkeypatch, tmp_path):
    manager, _config_path, _keytab_path = _prepare(monkeypatch, tmp_path)

    with pytest.raises(
        service.KerberosConfigurationError,
        match="KERBEROS_ERROR_INVALID_KEYTAB_EXTENSION",
    ):
        service.configure(_upload(filename="credentials.txt"), manager)


def test_configure_activates_new_modular_auth_file(monkeypatch, tmp_path):
    config_path = tmp_path / "squid.conf"
    config_path.write_text(
        f"include {tmp_path / 'squid.d' / '120_http_access.conf'}\n",
        encoding="utf-8",
    )
    config_dir = tmp_path / "squid.d"
    config_dir.mkdir()
    (config_dir / "120_http_access.conf").write_text(
        "http_access deny all\n", encoding="utf-8"
    )
    manager = FakeConfigManager(config_path, config_dir, modular=True)
    monkeypatch.setattr(
        service.Config, "SQUID_KERBEROS_KEYTAB_PATH", str(tmp_path / "HTTP.keytab")
    )
    monkeypatch.setattr(service, "_squid_binary", lambda: "/usr/sbin/squid")
    monkeypatch.setattr(service, "_get_proxy_ids", lambda: (1000, 1000))
    monkeypatch.setattr(service.os, "chown", lambda *_args: None)
    monkeypatch.setattr(
        service,
        "_keytab_permissions",
        lambda _path: {
            "exists": True,
            "mode": "0440",
            "owner": "proxy",
            "group": "proxy",
            "permissions_ok": True,
        },
    )
    monkeypatch.setattr(service, "verify_keytab_readable", lambda _path: (True, ""))
    monkeypatch.setattr(
        service, "_validate_squid_configuration", lambda _bin: (True, "")
    )

    service.configure(_upload(), manager)

    auth_path = config_dir / service.KERBEROS_AUTH_FILENAME
    assert auth_path.exists()
    assert service.KERBEROS_CONFIG_START in auth_path.read_text(encoding="utf-8")
    assert str(auth_path) in config_path.read_text(encoding="utf-8")


def test_kerberos_panel_is_not_nested_in_ldap_panel():
    template_path = Path("templates/admin/ldap_config.html")
    parser = PanelStructureParser()
    parser.feed(template_path.read_text(encoding="utf-8"))

    assert "ldap-tab-panel" in parser.parent_ids
    assert "kerberos-tab-panel" in parser.parent_ids
    assert "ldap-tab-panel" not in parser.parent_ids["kerberos-tab-panel"]


def test_kerberos_controls_enable_for_a_detected_docker_squid():
    template = Path("templates/admin/ldap_config.html").read_text(encoding="utf-8")
    enabled_when_squid_is_available = (
        ':disabled="!kerberosStatus.squid_available || applyingKerberos"'
    )

    assert template.count(enabled_when_squid_is_available) == 3
    assert "!kerberosStatus.squid_installed || applyingKerberos" not in template


def test_kerberos_panel_warns_that_ldap_must_support_kerberos():
    template = Path("templates/admin/ldap_config.html").read_text(encoding="utf-8")

    assert "KERBEROS_LDAP_KERBEROS_REQUIRED_WARNING" in template


def test_ldap_panel_offers_kerberos_directory_authentication():
    template = Path("templates/admin/ldap_config.html").read_text(encoding="utf-8")

    assert '<option value="KERBEROS">' in template
    assert "LDAP_KERBEROS_AUTH_HELP" in template
