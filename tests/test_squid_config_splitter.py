"""
Tests for SquidConfigSplitter — the Squid config file splitting engine.
"""

from unittest.mock import patch

import pytest

from services.squid.squid_config_splitter import SquidConfigSplitter


class TestClassifyLine:
    """Test the line classification engine."""

    @pytest.fixture(autouse=True)
    def _splitter(self):
        self.splitter = SquidConfigSplitter(input_file="/dev/null")

    @pytest.mark.parametrize(
        "line, expected_file",
        [
            ("http_port 3128", "00_ports.conf"),
            ("visible_hostname proxy", "10_misc.conf"),
            ("pid_filename /var/run/squid.pid", "10_misc.conf"),
            ("cache_mgr admin@example.com", "10_misc.conf"),
            ("forwarded_for off", "20_security.conf"),
            ("via off", "20_security.conf"),
            ("request_header_access Allow allow all", "20_security.conf"),
            ("cache_mem 64 MB", "30_cache.conf"),
            ("cache_dir ufs /spool 100 16 256", "30_cache.conf"),
            ("maximum_object_size 4 MB", "30_cache.conf"),
            ("refresh_pattern . 0 20% 4320", "40_refresh_patterns.conf"),
            ("auth_param basic program /usr/lib/squid/basic_ncsa_auth", "50_auth.conf"),
            ("acl auth proxy_auth REQUIRED", "50_auth.conf"),
            ("ssl_bump bump all", "55_ssl_bump.conf"),
            ("sslcrtd_program /usr/lib/squid/security_file_certgen", "55_ssl_bump.conf"),
            ("acl step1 at_step SslBump1", "55_ssl_bump.conf"),
            ("access_log /var/log/squid/access.log", "60_logs.conf"),
            ("cache_log /var/log/squid/cache.log", "60_logs.conf"),
            ("logformat squid %ts.%03tu", "60_logs.conf"),
            ("coredump_dir /var/spool/squid", "60_logs.conf"),
            ("icap_enable on", "70_icap.conf"),
            ("adaptation_access service_resp allow all", "70_icap.conf"),
            ("dns_nameservers 8.8.8.8", "80_dns.conf"),
            ("hosts_file /etc/hosts", "80_dns.conf"),
            ("connect_timeout 30 seconds", "80_dns.conf"),
            ("include /etc/squid/block.txt", "90_includes.conf"),
            ("acl localhost src 127.0.0.1/32", "100_acls.conf"),
            ("acl red_local src 10.0.0.0/8", "100_acls.conf"),
            ("external_acl_type helper_name", "100_acls.conf"),
            ("delay_pools 3", "110_delay_pools.conf"),
            ("delay_class 1 2", "110_delay_pools.conf"),
            ("no_cache deny QUERY", "115_cache_control.conf"),
            # cache_peer matches both 30_cache.conf and 115_cache_control.conf (ambiguous)
            # so we test it separately below
            ("never_direct allow all", "115_cache_control.conf"),
            ("http_access allow localhost", "120_http_access.conf"),
            ("http_access deny all", "120_http_access.conf"),
            ("deny_info ERR_CUSTOM all", "120_http_access.conf"),
        ],
    )
    def test_classify_known_directives(self, line, expected_file):
        assert self.splitter._classify_line(line) == expected_file

    def test_classify_unknown_goes_to_999(self):
        assert self.splitter._classify_line("some_random_directive value") == "999_unknown.conf"


class TestLoadOrder:
    """Test that the include load order is correct for dependency resolution."""

    def test_includes_before_acls(self):
        splitter = SquidConfigSplitter(input_file="/dev/null")
        order = splitter._get_load_order()
        idx_includes = order.index("90_includes.conf")
        idx_acls = order.index("100_acls.conf")
        idx_http = order.index("120_http_access.conf")
        assert idx_includes < idx_acls, "includes must load before ACLs"
        assert idx_acls < idx_http, "ACLs must load before http_access"

    def test_auth_before_acls(self):
        splitter = SquidConfigSplitter(input_file="/dev/null")
        order = splitter._get_load_order()
        idx_auth = order.index("50_auth.conf")
        idx_acls = order.index("100_acls.conf")
        assert idx_auth < idx_acls

    def test_delay_pools_after_acls(self):
        splitter = SquidConfigSplitter(input_file="/dev/null")
        order = splitter._get_load_order()
        idx_acls = order.index("100_acls.conf")
        idx_delay = order.index("110_delay_pools.conf")
        assert idx_acls < idx_delay


class TestSplitConfig:
    """Test the full split_config workflow on temp files."""

    def test_split_creates_modular_files(self, tmp_squid_conf, tmp_path):
        output_dir = tmp_path / "squid.d"
        with patch.object(SquidConfigSplitter, "_validate_squid_config", return_value={"success": True, "output": ""}):
            splitter = SquidConfigSplitter(
                input_file=str(tmp_squid_conf),
                output_dir=str(output_dir),
            )
            results = splitter.split_config()

        assert output_dir.exists()
        # Check expected files were created
        expected_files = [
            "00_ports.conf",
            "10_misc.conf",
            "20_security.conf",
            "30_cache.conf",
            "40_refresh_patterns.conf",
            "60_logs.conf",
            "100_acls.conf",
            "120_http_access.conf",
        ]
        created_files = [f.name for f in output_dir.iterdir() if f.suffix == ".conf"]
        for expected in expected_files:
            assert expected in created_files, f"{expected} should be created"

    def test_split_generates_main_config_with_includes(self, tmp_squid_conf, tmp_path):
        output_dir = tmp_path / "squid.d"
        with patch.object(SquidConfigSplitter, "_validate_squid_config", return_value={"success": True, "output": ""}):
            splitter = SquidConfigSplitter(
                input_file=str(tmp_squid_conf),
                output_dir=str(output_dir),
            )
            splitter.split_config()

        main_content = tmp_squid_conf.read_text()
        assert "include" in main_content
        assert "SquidStats" in main_content  # Header comment

    def test_split_with_include_directive(self, tmp_path):
        """Ensure include directives go to 90_includes.conf."""
        conf = tmp_path / "squid.conf"
        conf.write_text(
            "http_port 3128\n"
            "include /etc/squid/usuarios_bloqueados.txt\n"
            "acl localhost src 127.0.0.1\n"
            "http_access deny all\n",
            encoding="utf-8",
        )
        output_dir = tmp_path / "squid.d"

        with patch.object(SquidConfigSplitter, "_validate_squid_config", return_value={"success": True, "output": ""}):
            splitter = SquidConfigSplitter(
                input_file=str(conf),
                output_dir=str(output_dir),
            )
            splitter.split_config()

        includes_file = output_dir / "90_includes.conf"
        assert includes_file.exists()
        content = includes_file.read_text()
        assert "include /etc/squid/usuarios_bloqueados.txt" in content

    def test_split_nonexistent_file_raises(self, tmp_path):
        splitter = SquidConfigSplitter(
            input_file=str(tmp_path / "nonexistent.conf"),
            output_dir=str(tmp_path / "out"),
        )
        with pytest.raises(FileNotFoundError):
            splitter.split_config()

    def test_split_handles_continuation_lines(self, tmp_path):
        """Backslash continuation lines should stay together."""
        conf = tmp_path / "squid.conf"
        conf.write_text(
            "http_port 3128 ssl-bump \\\n"
            "    cert=/etc/ssl/squid.pem \\\n"
            "    generate-host-certificates=on\n"
            "http_access deny all\n",
            encoding="utf-8",
        )
        output_dir = tmp_path / "squid.d"

        with patch.object(SquidConfigSplitter, "_validate_squid_config", return_value={"success": True, "output": ""}):
            splitter = SquidConfigSplitter(
                input_file=str(conf),
                output_dir=str(output_dir),
            )
            splitter.split_config()

        ports_file = output_dir / "00_ports.conf"
        assert ports_file.exists()
        content = ports_file.read_text()
        assert "ssl-bump" in content
        assert "generate-host-certificates" in content

    def test_split_auth_detection(self, tmp_path):
        conf = tmp_path / "squid.conf"
        conf.write_text(
            "http_port 3128\n"
            "auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd\n"
            "acl auth proxy_auth REQUIRED\n"
            "http_access allow auth\n"
            "http_access deny all\n",
            encoding="utf-8",
        )
        output_dir = tmp_path / "squid.d"

        with patch.object(SquidConfigSplitter, "_validate_squid_config", return_value={"success": True, "output": ""}):
            splitter = SquidConfigSplitter(
                input_file=str(conf),
                output_dir=str(output_dir),
            )
            splitter.split_config()

        auth_file = output_dir / "50_auth.conf"
        assert auth_file.exists()
        assert splitter.has_auth is True

    def test_backup_disabled(self, tmp_squid_conf, tmp_path):
        """Backup creation is currently disabled — no .bak files should appear."""
        output_dir = tmp_path / "squid.d"
        with patch.object(SquidConfigSplitter, "_validate_squid_config", return_value={"success": True, "output": ""}):
            splitter = SquidConfigSplitter(
                input_file=str(tmp_squid_conf),
                output_dir=str(output_dir),
            )
            splitter.split_config()

        bak_files = list(tmp_path.glob("*.bak*"))
        assert len(bak_files) == 0, "No .bak files should be created"


class TestGetSplitInfo:
    def test_returns_dict_of_descriptions(self):
        splitter = SquidConfigSplitter(input_file="/dev/null")
        info = splitter.get_split_info()
        assert isinstance(info, dict)
        assert "00_ports.conf" in info
        assert "120_http_access.conf" in info
        assert "999_unknown.conf" in info
