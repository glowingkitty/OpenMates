# contract-test-file: infrastructure
"""Persistent coordinator ownership from a cron environment."""

from pathlib import Path

from scripts import ci_coordinator_service as service


def test_persistent_unit_has_restart_and_boot_ownership():
    root = Path("/srv/OpenMates")
    unit = service.render_unit(root)
    assert "WorkingDirectory=/srv/OpenMates" in unit
    assert "scripts/ci_coordinator.py serve" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    assert "systemd-run" not in unit


def test_user_manager_env_connects_to_linger_bus_without_login_shell(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    environment = service.user_manager_env(uid=1001)
    assert environment["XDG_RUNTIME_DIR"] == "/run/user/1001"
    assert environment["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1001/bus"
