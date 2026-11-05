"""Harness ownership unit tests; no actual adapter/peer process is started."""

# contract-test-file: tooling
from pathlib import Path
import importlib.util
from types import SimpleNamespace
import pytest


def load():
    path = Path(__file__).parent / "runners/session-embed-share.py"
    spec = importlib.util.spec_from_file_location("share_lifecycle_unit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "boundary", ["selector-setup", "owner-cancel", "descendant-pipes"]
)
def test_started_group_is_reserved_then_killed_and_reaped_even_on_cancel_or_setup_error(
    monkeypatch, boundary
):
    m = load()
    events = []

    class Channel:
        closed = False

        def fileno(self):
            return 55

        def close(self):
            self.closed = True

    child = SimpleNamespace(
        pid=34567, stdin=Channel(), stdout=Channel(), stderr=Channel(), returncode=None
    )

    def waited(timeout):
        assert timeout == 1
        events.append("reap")
        child.returncode = -15

    child.wait = waited

    def popen(*args, **kw):
        assert kw["start_new_session"] is True
        assert kw["stderr"] == m.subprocess.PIPE
        events.append("spawn")
        return child

    class Selector:
        def __init__(self):
            if boundary == "selector-setup":
                raise ValueError("synthetic setup failure")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def get_map(self):
            return {1: True}

        def select(self, timeout):
            assert timeout <= 0.05
            if boundary == "owner-cancel":
                m.cancel_owner(m.signal.SIGTERM, None)
            return []

    clock = [1.0]

    def now():
        clock[0] += 0.1
        return clock[0]

    def signal_group(pid, kind):
        assert pid == child.pid
        events.append("term" if kind == m.signal.SIGTERM else "kill")

    monkeypatch.setattr(m.subprocess, "Popen", popen)
    monkeypatch.setattr(m.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(m.os, "set_blocking", lambda *args: None)

    def waitid(kind, pid, flags):
        assert pid == child.pid and flags & m.os.WNOWAIT
        return object() if boundary == "descendant-pipes" else None

    monkeypatch.setattr(m.os, "waitid", waitid)
    monkeypatch.setattr(m.os, "killpg", signal_group)
    monkeypatch.setattr(m.time, "monotonic", now)
    monkeypatch.setattr(m.time, "sleep", lambda seconds: events.append("grace"))
    with pytest.raises(ValueError):
        m.invoke(["fixed-synthetic-adapter", "--case"], {})
    assert events == ["spawn", "term", "grace", "kill", "reap"]
    assert all(channel.closed for channel in (child.stdin, child.stdout, child.stderr))


def test_cancel_before_dispatch_never_starts_successor_process(monkeypatch):
    m = load()
    m.cancel_owner(m.signal.SIGINT, None)
    monkeypatch.setattr(
        m.subprocess,
        "Popen",
        lambda *a, **kw: pytest.fail("cancelled owner dispatched"),
    )
    with pytest.raises(ValueError, match="cancelled"):
        m.invoke(["fixed-synthetic-adapter", "--case"], {})
