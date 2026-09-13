"""Regression tests for quota scheduler/runtime integration."""

from __future__ import annotations

from contextlib import contextmanager

from services.quota import quota_scheduler


class _Scheduler:
    def __init__(self) -> None:
        self.tasks = {}

    def task(self, *_args, **kwargs):
        def register(function):
            self.tasks[kwargs["id"]] = function
            return function

        return register


class _ConfigManager:
    is_valid = True
    config_path = "/selected/squid.conf"


def test_periodic_quota_reload_uses_the_selected_squid_runtime(monkeypatch):
    """The scheduler must not reload systemd/default Docker by accident."""
    scheduler = _Scheduler()
    selected_runtime = object()
    calls = []
    events = []

    @contextmanager
    def config_lock(config_path):
        events.append(("lock", "enter", config_path))
        try:
            yield
        finally:
            events.append(("lock", "exit", config_path))

    def reconfigure(config_path, runtime):
        calls.append((config_path, runtime))
        events.append(("reload", config_path, runtime))
        return True, "ok"

    monkeypatch.setattr(quota_scheduler, "SquidConfigManager", _ConfigManager)
    monkeypatch.setattr(quota_scheduler, "_find_squid_runtime", lambda: selected_runtime)
    monkeypatch.setattr(quota_scheduler, "squid_config_write_lock", config_lock)
    monkeypatch.setattr(
        quota_scheduler,
        "reconfigure_squid",
        reconfigure,
    )
    monkeypatch.setattr(quota_scheduler.Path, "exists", lambda _path: False)

    quota_scheduler.register_quota_scheduler_tasks(scheduler)
    scheduler.tasks["reload_squid_if_quota_enabled"]()

    assert calls == [("/selected/squid.conf", selected_runtime)]
    assert events == [
        ("lock", "enter", "/selected/squid.conf"),
        ("reload", "/selected/squid.conf", selected_runtime),
        ("lock", "exit", "/selected/squid.conf"),
    ]
