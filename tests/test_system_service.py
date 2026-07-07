from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch

from services.system.system_service import (
    DOCKER_CONTAINER_NAME,
    _docker_container_exists,
    reload_squid,
    restart_squid,
)


def test_docker_container_exists_returns_true_when_container_present():
    with patch("services.system.system_service._get_bin", return_value="/usr/bin/docker"), patch(
        "services.system.system_service.subprocess.run"
    ) as mock_run:
        mock_run.return_value = CompletedProcess(
            args=["/usr/bin/docker", "ps"], returncode=0, stdout=f"{DOCKER_CONTAINER_NAME}\n"
        )

        assert _docker_container_exists("/usr/bin/docker", DOCKER_CONTAINER_NAME) is True
        mock_run.assert_called_once()


def test_restart_squid_falls_back_to_docker_restart_when_systemctl_fails():
    def fake_get_bin(name: str):
        return "/bin/systemctl" if name == "systemctl" else "/usr/bin/docker"

    def fake_run(args, check, capture_output, text, timeout):
        if args[0] == "/bin/systemctl":
            raise CalledProcessError(returncode=1, cmd=args, output="", stderr="failed")
        if args[:3] == ["/usr/bin/docker", "ps", "--filter"]:
            return CompletedProcess(args=args, returncode=0, stdout=f"{DOCKER_CONTAINER_NAME}\n")
        if args[:2] == ["/usr/bin/docker", "restart"]:
            return CompletedProcess(args=args, returncode=0, stdout="")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    with patch("services.system.system_service._get_bin", side_effect=fake_get_bin), patch(
        "services.system.system_service.subprocess.run", side_effect=fake_run
    ) as mock_run:
        success, message, details = restart_squid()

        assert success is True
        assert "restarted successfully" in message.lower()
        assert details is None
        assert mock_run.call_count == 3


def test_reload_squid_uses_docker_reconfigure_when_systemctl_not_available():
    def fake_get_bin(name: str):
        return None if name == "systemctl" else "/usr/bin/docker"

    def fake_run(args, check, capture_output, text, timeout):
        if args[:3] == ["/usr/bin/docker", "ps", "--filter"]:
            return CompletedProcess(args=args, returncode=0, stdout=f"{DOCKER_CONTAINER_NAME}\n")
        if args[:3] == ["/usr/bin/docker", "exec", DOCKER_CONTAINER_NAME]:
            return CompletedProcess(args=args, returncode=0, stdout="")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    with patch("services.system.system_service._get_bin", side_effect=fake_get_bin), patch(
        "services.system.system_service.subprocess.run", side_effect=fake_run
    ):
        success, message, details = reload_squid()

        assert success is True
        assert "reconfigure" in message.lower()
        assert details is None
