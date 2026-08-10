#!/usr/bin/env python3
"""Failure containment contracts for ephemeral OpenCode presence.

Presence corruption or filesystem failure is visible but cannot mutate durable
session coordination, edit leases, stale-read hashes, or worktree metadata.
Run: python3 -m pytest scripts/tests/test_opencode_presence_failure_containment.py.
"""

from scripts.opencode_presence_store import PresenceStore, PresenceStoreError


def test_corruption_is_diagnostic_and_durable_state_is_unchanged(tmp_path):
    durable = tmp_path / "sessions.json"
    durable.write_bytes(b'{"sessions":{"safe":true}}\n')
    state = tmp_path / "presence.json"
    state.write_text("not-json", encoding="utf-8")
    store = PresenceStore(state, project_root=tmp_path)
    snapshot = store.snapshot()
    assert snapshot["sessions"] == {}
    assert snapshot["diagnostics"][0]["code"] == "corrupt_store"
    assert durable.read_bytes() == b'{"sessions":{"safe":true}}\n'


def test_unavailable_store_raises_visible_presence_error(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("file", encoding="utf-8")
    store = PresenceStore(blocked / "presence.json", project_root=tmp_path)
    try:
        store.update({"session_id": "ses-a", "source_id": "s", "generation": 1, "sequence": 1, "execution": "busy", "attention": "none", "turn": "streaming", "updated_at": "2026-08-05T00:00:00Z"})
    except PresenceStoreError as error:
        assert "presence" in str(error).lower()
    else:
        raise AssertionError("unavailable presence store did not report failure")


def test_recovery_rebuilds_only_from_new_events(tmp_path):
    state = tmp_path / "presence.json"
    state.write_text("not-json", encoding="utf-8")
    store = PresenceStore(state, project_root=tmp_path)
    store.update({"session_id": "ses-new", "source_id": "s", "generation": 1, "sequence": 1, "execution": "busy", "attention": "none", "turn": "streaming", "updated_at": "2026-08-05T00:00:00Z"})
    assert set(store.snapshot(expire=False)["sessions"]) == {"ses-new"}
