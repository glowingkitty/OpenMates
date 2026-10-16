# contract-test-file: infrastructure
"""Persistent coordinator ownership from a cron environment."""

from pathlib import Path

from scripts import ci_coordinator_service as service


def test_persistent_unit_has_restart_and_boot_ownership(tmp_path):
    root = tmp_path
    (root / "scripts").mkdir()
    (root / "scripts/ci_coordinator.py").write_text("runtime_seed = True\n")
    unit = service.render_unit(root)
    assert f"WorkingDirectory={root}" in unit
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


def managed_service(monkeypatch, tmp_path, *, marker_current=True):
    import subprocess
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts/ci_coordinator.py").write_text("runtime_seed = True\n")
    (root / "scripts/ci_preparation_transport.py").write_text("download_runtime = True\n")
    unit = tmp_path / service.UNIT_NAME
    unit.write_text(service.render_unit(root))
    state = {"marker": service.code_fingerprint(root) if marker_current else None, "calls": []}
    monkeypatch.setattr(service, "lingering_enabled", lambda: True)
    monkeypatch.setattr(service, "running_code_fingerprint", lambda pid: state["marker"] if pid == 42 else None)

    def manager(*args):
        state["calls"].append(args)
        stdout = ""
        if args[:1] == ("show",):
            stdout = str(unit) if "FragmentPath" in args else "42"
        if args == ("enable", "--now", service.UNIT_NAME):
            state["marker"] = service.code_fingerprint(root)
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(service, "manager", manager)
    return root, unit, state


def test_legacy_daemon_cannot_pass_check_with_runtime_seed_source(monkeypatch, tmp_path):
    root, unit, state = managed_service(monkeypatch, tmp_path, marker_current=False)
    # Unit and source advertise seed-capable code, but the old daemon loaded
    # before runtime_seed existed. An active/matching unit alone is insufficient.
    assert any("loaded code missing or stale" in failure for failure in service.check(root, unit))
    assert state["marker"] is None


def test_fresh_service_install_is_noop(monkeypatch, tmp_path):
    root, unit, state = managed_service(monkeypatch, tmp_path)
    assert service.install(root, unit) == []
    assert not any(call[0] in {"stop", "daemon-reload", "enable"} for call in state["calls"])


def test_stale_runtime_seed_dispatcher_reloads_under_lock_preserving_queue(monkeypatch, tmp_path):
    import sqlite3
    root, unit, state = managed_service(monkeypatch, tmp_path)
    queue = root / "logs/ci-coordinator/queue.sqlite3"
    queue.parent.mkdir(parents=True)
    with sqlite3.connect(queue) as db:
        db.execute("CREATE TABLE jobs (id TEXT, state TEXT, runtime_seed TEXT)")
        db.executemany("INSERT INTO jobs VALUES (?, ?, ?)", [("queued", "queued", "requested"), ("running", "running", "requested")])
    original_queue = queue.read_bytes()
    (root / "scripts/ci_coordinator.py").write_text("runtime_seed = 'dispatch new requested seed'\n")
    lock_events = []
    monkeypatch.setattr(service.fcntl, "flock", lambda fd, operation: lock_events.append(operation))
    assert service.install(root, unit) == []
    assert lock_events == [service.fcntl.LOCK_EX]
    actions = [call for call in state["calls"] if call[0] in {"stop", "daemon-reload", "enable"}]
    assert actions == [("stop", service.UNIT_NAME), ("daemon-reload",), ("enable", "--now", service.UNIT_NAME)]
    assert state["marker"] == service.code_fingerprint(root)
    assert queue.read_bytes() == original_queue


def test_transport_change_invalidates_loaded_capability(monkeypatch, tmp_path):
    root, unit, state = managed_service(monkeypatch, tmp_path)
    (root / "scripts/ci_preparation_transport.py").write_text("download_runtime = 'changed'\n")
    assert any("loaded code missing or stale" in failure for failure in service.check(root, unit))


def test_reads_only_startup_fingerprint_without_exposing_environment(monkeypatch):
    import io
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: io.BytesIO(b"SECRET=private\0OPENMATES_CI_CODE_FINGERPRINT=abc\0"))
    assert service.running_code_fingerprint(42) == "abc"
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: io.BytesIO(b"SECRET=private\0"))
    assert service.running_code_fingerprint(42) is None
