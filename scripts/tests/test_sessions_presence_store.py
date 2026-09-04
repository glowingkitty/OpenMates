#!/usr/bin/env python3
# contract-test-file: tooling
"""Presence-store concurrency, expiry, ordering, and task-claim contracts.

The store is redirected to a temporary directory and never touches live state.
It must remain independent from durable sessions and worktree metadata.
Run: python3 -m pytest scripts/tests/test_sessions_presence_store.py.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.opencode_presence_store import PresenceStore, TaskClaimConflict


def record(session_id: str, sequence: int, **extra):
    return {
        "session_id": session_id,
        "source_id": f"source-{session_id}",
        "generation": 1,
        "sequence": sequence,
        "execution": "busy",
        "attention": "none",
        "turn": "streaming",
        "updated_at": "2026-08-05T00:00:00Z",
        "heartbeat_at": "2026-08-05T00:00:00Z",
        **extra,
    }


def test_concurrent_writers_do_not_lose_records(tmp_path):
    store = PresenceStore(
        tmp_path / "presence.json",
        project_root=tmp_path,
        now=lambda: "2026-08-05T00:00:00Z",
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: store.update(record(f"ses-{index}", 1)), range(24)))
    assert len(store.snapshot(expire=False)["sessions"]) == 24


def test_same_source_stale_sequence_is_rejected(tmp_path):
    store = PresenceStore(
        tmp_path / "presence.json",
        project_root=tmp_path,
        now=lambda: "2026-08-05T00:00:00Z",
    )
    assert store.update(record("ses-a", 2))["accepted"] is True
    assert store.update(record("ses-a", 1))["accepted"] is False
    assert store.snapshot(expire=False)["sessions"]["ses-a"]["sequence"] == 2


def test_busy_presence_expires_to_unknown_without_touching_durable_state(tmp_path):
    durable = tmp_path / "sessions.json"
    durable.write_bytes(b'{"sessions":{"keep":true}}\n')
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path, now=lambda: "2026-08-05T00:03:00Z")
    store.update(record("ses-a", 1))
    assert store.snapshot()["sessions"]["ses-a"]["execution"] == "unknown"
    assert durable.read_bytes() == b'{"sessions":{"keep":true}}\n'


def test_automatic_child_role_does_not_replace_explicit_role(tmp_path):
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path)
    store.set_child_role("ses-child", "ses-parent", "reviewer")

    marker = store.set_child_role("ses-child", "ses-parent", "read_only", if_unset=True)

    assert marker["role"] == "reviewer"
    assert store.snapshot(expire=False)["child_roles"]["ses-child"]["role"] == "reviewer"


def test_explicit_child_role_can_replace_automatic_role(tmp_path):
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path)
    store.set_child_role("ses-child", "ses-parent", "read_only", if_unset=True)

    marker = store.set_child_role("ses-child", "ses-parent", "reviewer")

    assert marker["role"] == "reviewer"


def test_task_claim_lifecycle_is_atomic_and_role_aware(tmp_path):
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path, now=lambda: "2026-08-05T00:00:00Z")
    first = store.claim_task("docs/plans/example/plan.yml", "TASK-4", "ses-a", role="implementation", ttl_seconds=60)
    assert first["owner_session_id"] == "ses-a"
    with pytest.raises(TaskClaimConflict):
        store.claim_task("docs/plans/example/plan.yml", "TASK-4", "ses-b", role="implementation", ttl_seconds=60)
    review = store.claim_task("docs/plans/example/plan.yml", "TASK-4", "ses-review", role="reviewer", ttl_seconds=60)
    assert review["role"] == "reviewer"
    renewed = store.renew_task("docs/plans/example/plan.yml", "TASK-4", "ses-a", ttl_seconds=120)
    assert renewed["expires_at"] > first["expires_at"]
    store.release_task("docs/plans/example/plan.yml", "TASK-4", "ses-a")
    assert store.claim_task("docs/plans/example/plan.yml", "TASK-4", "ses-b", role="implementation", ttl_seconds=60)["owner_session_id"] == "ses-b"


def test_expired_implementation_claim_can_be_taken_over(tmp_path):
    current = ["2026-08-05T00:00:00Z"]
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path, now=lambda: current[0])
    store.claim_task("docs/plans/example/plan.yml", "TASK-1", "ses-a", role="implementation", ttl_seconds=1)
    current[0] = "2026-08-05T00:00:02Z"
    claim = store.claim_task("docs/plans/example/plan.yml", "TASK-1", "ses-b", role="implementation", ttl_seconds=60)
    assert claim["owner_session_id"] == "ses-b"


def test_expired_claims_and_terminal_records_are_omitted_from_snapshot(tmp_path):
    current = ["2026-08-05T00:00:00Z"]
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path, now=lambda: current[0])
    store.update(record("ses-idle", 1, execution="idle", turn="completed"))
    store.claim_task("docs/plans/example/plan.yml", "TASK-1", "ses-a", role="implementation", ttl_seconds=1)
    current[0] = "2026-08-06T00:00:02Z"
    snapshot = store.snapshot()
    assert snapshot["sessions"] == {}
    assert snapshot["task_claims"] == {}


def test_normal_update_durably_prunes_expired_presence_and_child_roles(tmp_path):
    current = ["2026-08-05T00:00:00Z"]
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path, now=lambda: current[0])
    store.update(record("ses-old", 1, execution="idle", turn="completed"))
    store.set_child_role("ses-old-child", "ses-old", "read_only")

    current[0] = "2026-08-06T00:00:02Z"
    store.update(record(
        "ses-current",
        1,
        updated_at=current[0],
        heartbeat_at=current[0],
    ))

    persisted = store.snapshot(expire=False)
    assert set(persisted["sessions"]) == {"ses-current"}
    assert persisted["child_roles"] == {}
