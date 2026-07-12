"""Tests for OpenCode shared-worktree file leases.

These contracts cover atomic file-set acquisition, queued waiters, renewable
ownership, stale-owner expiry, and fencing generations. They use temporary JSON
state and no live OpenCode server or repository files.
"""

from __future__ import annotations

import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor

from scripts.opencode_file_leases import LeaseCoordinator


def load_sessions_module():
    path = __import__("pathlib").Path(__file__).resolve().parents[1] / "sessions.py"
    spec = importlib.util.spec_from_file_location("sessions_opencode_identity", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_acquire_is_atomic_and_deduplicates_waiting_request(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")

    first = coordinator.acquire("ses_a", ["b.py", "a.py"], now=10, ttl_seconds=30)
    waiting = coordinator.acquire("ses_b", ["a.py", "b.py"], now=11, ttl_seconds=30)
    repeated = coordinator.acquire("ses_b", ["b.py", "a.py"], now=12, ttl_seconds=30)

    assert first["status"] == "granted"
    assert first["files"] == ["a.py", "b.py"]
    assert waiting == repeated
    assert waiting["status"] == "waiting"
    assert waiting["position"] == 1
    assert coordinator.status(now=12)["leases"].keys() == {"a.py", "b.py"}
    assert len(coordinator.status(now=12)["queue"]) == 1


def test_release_grants_complete_waiting_set_once(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")
    first = coordinator.acquire("ses_a", ["a.py", "b.py"], now=10, ttl_seconds=30)
    coordinator.acquire("ses_b", ["a.py", "b.py"], now=11, ttl_seconds=30)

    result = coordinator.release("ses_a", now=12, ttl_seconds=30)

    assert result["released"] == ["a.py", "b.py"]
    assert result["newly_granted"] == [
        {
            "session_id": "ses_b",
            "files": ["a.py", "b.py"],
            "generation": first["generation"] + 1,
        }
    ]
    assert coordinator.release("ses_a", now=13, ttl_seconds=30)["newly_granted"] == []


def test_expiry_fences_stale_owner_and_grants_waiter(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")
    first = coordinator.acquire("ses_a", ["spec.yml"], now=10, ttl_seconds=5)
    coordinator.acquire("ses_b", ["spec.yml"], now=11, ttl_seconds=5)

    swept = coordinator.sweep(now=16, ttl_seconds=5)
    second = swept["newly_granted"][0]

    assert swept["expired_sessions"] == ["ses_a"]
    assert second["session_id"] == "ses_b"
    assert second["generation"] > first["generation"]
    assert coordinator.authorize("ses_a", ["spec.yml"], first["generation"], now=16) is False
    assert coordinator.authorize("ses_b", ["spec.yml"], second["generation"], now=16) is True


def test_heartbeat_renews_owned_files(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")
    granted = coordinator.acquire("ses_a", ["a.py"], now=10, ttl_seconds=5)

    heartbeat = coordinator.heartbeat("ses_a", now=14, ttl_seconds=5)

    assert heartbeat["renewed"] == ["a.py"]
    assert coordinator.authorize("ses_a", ["a.py"], granted["generation"], now=18) is True


def test_opencode_chat_identity_rebinds_from_older_repo_session():
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "old1": {"opencode_session_id": "ses_chat"},
            "new2": {"opencode_session_id": None},
        }
    }

    sessions.bind_opencode_session(data, "new2", "ses_chat")

    assert data["sessions"]["old1"]["opencode_session_id"] is None
    assert data["sessions"]["new2"]["opencode_session_id"] == "ses_chat"


def test_tracking_resolves_the_exact_opencode_chat_before_zellij(monkeypatch):
    sessions = load_sessions_module()
    data = {
        "old1": {"opencode_session_id": "ses_other", "zellij_session": "opencode"},
        "new2": {"opencode_session_id": "ses_chat", "zellij_session": "opencode"},
    }
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_chat")
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "opencode")

    assert sessions._resolve_session_identity(data) == "new2"


def test_unknown_opencode_chat_does_not_fall_back_to_shared_zellij(monkeypatch):
    sessions = load_sessions_module()
    data = {
        "old1": {"opencode_session_id": "ses_other", "zellij_session": "opencode"},
    }
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_unknown")
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "opencode")

    assert sessions._resolve_session_identity(data) is None


def test_tracking_uses_zellij_fallback_without_opencode_identity(monkeypatch):
    sessions = load_sessions_module()
    data = {
        "old1": {"opencode_session_id": None, "zellij_session": "claude1"},
    }
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "claude1")

    assert sessions._resolve_session_identity(data) == "old1"


def test_waiting_upgrade_treats_requesters_existing_lease_as_available(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")
    coordinator.acquire("ses_a", ["a.py"], now=10, ttl_seconds=30)
    coordinator.acquire("ses_b", ["b.py"], now=10, ttl_seconds=30)
    coordinator.acquire("ses_a", ["a.py", "b.py"], now=11, ttl_seconds=30)

    result = coordinator.release("ses_b", now=12, ttl_seconds=30)

    assert result["newly_granted"][0]["session_id"] == "ses_a"
    assert result["newly_granted"][0]["files"] == ["a.py", "b.py"]


def test_earlier_blocked_request_reserves_its_full_set_from_later_waiters(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")
    coordinator.acquire("owner", ["a.py"], now=10, ttl_seconds=30)
    coordinator.acquire("first", ["a.py", "b.py"], now=11, ttl_seconds=30)
    coordinator.acquire("later", ["b.py"], now=12, ttl_seconds=30)

    status = coordinator.status(now=12)

    assert [request["session_id"] for request in status["queue"]] == ["first", "later"]
    assert "b.py" not in status["leases"]


def test_grant_notification_remains_pending_until_acknowledged(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")
    coordinator.acquire("owner", ["a.py"], now=10, ttl_seconds=30)
    coordinator.acquire("waiter", ["a.py"], now=11, ttl_seconds=30)

    released = coordinator.release("owner", now=12, ttl_seconds=30)
    retried = coordinator.sweep(now=13, ttl_seconds=30)
    coordinator.acknowledge("waiter", released["newly_granted"][0]["generation"])
    acknowledged = coordinator.sweep(now=14, ttl_seconds=30)

    assert released["pending_notifications"] == retried["pending_notifications"]
    assert acknowledged["pending_notifications"] == []


def test_abandoned_earlier_waiter_expires_without_starving_later_request(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")
    coordinator.acquire("owner", ["a.py"], now=10, ttl_seconds=30)
    coordinator.acquire("abandoned", ["a.py", "b.py"], now=11, ttl_seconds=30, queue_ttl_seconds=5)
    coordinator.acquire("later", ["b.py"], now=12, ttl_seconds=30, queue_ttl_seconds=30)

    swept = coordinator.sweep(now=17, ttl_seconds=30)

    assert swept["expired_waiters"] == ["abandoned"]
    assert swept["newly_granted"][0]["session_id"] == "later"
    assert swept["newly_granted"][0]["files"] == ["b.py"]


def test_notification_claim_prevents_duplicate_delivery_and_recovers_after_timeout(tmp_path):
    coordinator = LeaseCoordinator(tmp_path / "leases.json")
    coordinator.acquire("owner", ["a.py"], now=10, ttl_seconds=30)
    coordinator.acquire("waiter", ["a.py"], now=11, ttl_seconds=30)
    coordinator.release("owner", now=12, ttl_seconds=30)

    first = coordinator.claim_notifications("notifier-a", now=13, claim_ttl_seconds=5)
    duplicate = coordinator.claim_notifications("notifier-b", now=14, claim_ttl_seconds=5)
    recovered = coordinator.claim_notifications("notifier-b", now=18, claim_ttl_seconds=5)

    assert [notification["session_id"] for notification in first["notifications"]] == ["waiter"]
    assert duplicate["notifications"] == []
    assert [notification["session_id"] for notification in recovered["notifications"]] == ["waiter"]


def test_concurrent_opencode_session_registration_preserves_every_record(tmp_path, monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "SESSIONS_FILE", tmp_path / "sessions.json")

    def register(index):
        return sessions.register_session_record(
            {
                "task": f"task-{index}",
                "mode": "feature",
                "tags": [],
                "started": sessions._now_iso(),
                "last_active": sessions._now_iso(),
                "modified_files": [],
                "writing": None,
                "task_id": None,
                "linear_issue_id": None,
                "zellij_session": "opencode",
                "opencode_session_id": None,
            },
            f"ses_chat{index}",
        )[0]

    with ThreadPoolExecutor(max_workers=8) as executor:
        session_ids = list(executor.map(register, range(16)))

    state = sessions._load_sessions()
    assert len(set(session_ids)) == 16
    assert len(state["sessions"]) == 16
    assert {record["opencode_session_id"] for record in state["sessions"].values()} == {
        f"ses_chat{index}" for index in range(16)
    }
