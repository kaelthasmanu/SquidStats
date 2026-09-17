"""Focused Docker-runtime regression tests for quota file synchronization."""

from types import SimpleNamespace

from services.quota import quota_service


def test_blocked_user_copy_uses_selected_docker_container(monkeypatch):
    """Do not send quota state to the legacy hard-coded squid_proxy name."""
    calls = []
    runtime = SimpleNamespace(
        kind="docker",
        executable="/usr/bin/docker",
        container_name="configured-squid",
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(quota_service, "_find_squid_runtime", lambda: runtime)
    monkeypatch.setattr(quota_service.subprocess, "run", fake_run)

    assert quota_service._sync_blocked_file_to_docker(
        "/etc/squid/usuarios_bloqueados.txt"
    )
    assert calls == [
        (
            [
                "/usr/bin/docker",
                "cp",
                "/etc/squid/usuarios_bloqueados.txt",
                "configured-squid:/etc/squid/usuarios_bloqueados.txt",
            ],
            {"check": True, "capture_output": True, "timeout": 10},
        )
    ]


def test_blocked_user_copy_does_not_target_docker_for_local_runtime(monkeypatch):
    """A local runtime must not mutate an unrelated Docker container."""
    runtime = SimpleNamespace(
        kind="local", executable="/usr/sbin/squid", container_name=None
    )
    monkeypatch.setattr(quota_service, "_find_squid_runtime", lambda: runtime)
    monkeypatch.setattr(
        quota_service.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert not quota_service._sync_blocked_file_to_docker(
        "/etc/squid/usuarios_bloqueados.txt"
    )
