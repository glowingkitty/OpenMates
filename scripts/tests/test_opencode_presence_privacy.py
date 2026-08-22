#!/usr/bin/env python3
# contract-test-file: tooling
"""Privacy and filesystem-boundary contracts for OpenCode presence.

Only structured identifiers, states, timestamps, capabilities, and safe relative
paths may survive sanitization. Live prompts and tool data are never fixtures.
Run: python3 -m pytest scripts/tests/test_opencode_presence_privacy.py.
"""

import json
import stat

from scripts.opencode_presence_store import PresenceStore


def test_unknown_and_sensitive_fields_are_stripped(tmp_path):
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path)
    store.update({
        "session_id": "ses-a", "source_id": "source-a", "generation": 1, "sequence": 1,
        "execution": "busy", "attention": "required_permission", "turn": "streaming",
        "pending_permission_ids": ["perm-1"], "updated_at": "2026-08-05T00:00:00Z",
        "title": "secret", "todos": ["secret"], "message": "secret", "reasoning": "secret",
        "tool_input": {"token": "secret"}, "tool_output": "secret", "patch": "secret", "env": {"KEY": "secret"},
    })
    raw = (tmp_path / "presence.json").read_text(encoding="utf-8")
    for forbidden in ("secret", "title", "todos", "message", "reasoning", "tool_input", "tool_output", "patch", "env"):
        assert forbidden not in raw
    assert json.loads(raw)["sessions"]["ses-a"]["pending_permission_ids"] == ["perm-1"]


def test_runtime_hook_hash_is_retained_as_a_bounded_identifier(tmp_path):
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path)
    runtime_hash = "a" * 64
    result = store.update({
        "session_id": "ses-a", "source_id": "source-a", "generation": 1, "sequence": 1,
        "execution": "busy", "attention": "none", "turn": "streaming",
        "hook_runtime_hash": runtime_hash, "updated_at": "2026-08-05T00:00:00Z",
    })

    assert result["record"]["hook_runtime_hash"] == runtime_hash

    rejected = store.update({
        "session_id": "ses-b", "source_id": "source-b", "generation": 1, "sequence": 1,
        "execution": "busy", "attention": "none", "turn": "streaming",
        "hook_runtime_hash": "not-a-hash", "updated_at": "2026-08-05T00:00:00Z",
    })
    assert "hook_runtime_hash" not in rejected["record"]


def test_paths_are_relative_and_traversal_safe(tmp_path):
    store = PresenceStore(tmp_path / "presence.json", project_root=tmp_path)
    result = store.update({
        "session_id": "ses-a", "source_id": "source-a", "generation": 1, "sequence": 1,
        "execution": "busy", "attention": "none", "turn": "streaming",
        "paths": [str(tmp_path / "scripts" / "sessions.py"), "../outside", "/etc/passwd"],
        "updated_at": "2026-08-05T00:00:00Z",
    })
    assert result["record"]["paths"] == ["scripts/sessions.py"]


def test_store_is_owner_only_and_project_scoped(tmp_path):
    first_root = tmp_path / "first"
    first_root.mkdir()
    store = PresenceStore(tmp_path / "presence.json", project_root=first_root)
    store.update({"session_id": "ses-a", "source_id": "source-a", "generation": 1, "sequence": 1, "execution": "idle", "attention": "optional", "turn": "completed", "updated_at": "2026-08-05T00:00:00Z"})
    assert stat.S_IMODE((tmp_path / "presence.json").stat().st_mode) == 0o600
    other_root = tmp_path / "other"
    other_root.mkdir()
    assert PresenceStore(tmp_path / "presence.json", project_root=other_root).snapshot()["sessions"] == {}


def test_valid_version_existing_records_are_resanitized_before_disclosure(tmp_path):
    state = tmp_path / "presence.json"
    state.write_text(
        json.dumps({
            "version": 1,
            "project_root": str(tmp_path.resolve()),
            "sessions": {
                "ses-a": {
                    "session_id": "ses-a", "source_id": "source-a", "generation": 1, "sequence": 1,
                    "execution": "busy", "attention": "none", "turn": "streaming",
                    "updated_at": "2026-08-05T00:00:00Z", "message": "secret", "tool_output": "secret",
                }
            },
            "task_claims": {},
            "child_roles": {},
        }),
        encoding="utf-8",
    )
    snapshot = PresenceStore(state, project_root=tmp_path).snapshot(expire=False)
    assert snapshot["sessions"]["ses-a"]["execution"] == "busy"
    assert "secret" not in json.dumps(snapshot)
    assert "message" not in snapshot["sessions"]["ses-a"]
