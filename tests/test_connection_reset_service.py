from unittest.mock import patch

from services.squid.connection_reset_service import reset_client_connections


def test_reset_rejects_invalid_ip_without_running_a_command():
    with patch("services.squid.connection_reset_service.subprocess.run") as mock_run:
        success, message, details = reset_client_connections("not-an-ip")

    assert success is False
    assert "válida" in message
    assert details is None
    mock_run.assert_not_called()


def test_reset_uses_conntrack_for_linux_clients():
    with (
        patch(
            "services.squid.connection_reset_service.platform.system",
            return_value="Linux",
        ),
        patch(
            "services.squid.connection_reset_service.shutil.which",
            return_value="/usr/sbin/conntrack",
        ),
        patch("services.squid.connection_reset_service.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        success, message, details = reset_client_connections("192.0.2.10")

    assert success is True
    assert "conntrack" in message
    assert details is None
    assert mock_run.call_args.args[0] == [
        "/usr/sbin/conntrack",
        "-D",
        "-s",
        "192.0.2.10",
    ]


def test_reset_reports_unsupported_platform():
    with patch(
        "services.squid.connection_reset_service.platform.system",
        return_value="Windows",
    ):
        success, message, details = reset_client_connections("192.0.2.10")

    assert success is False
    assert "soportado" in message
    assert details is None
