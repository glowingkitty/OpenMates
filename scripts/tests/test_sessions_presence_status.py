#!/usr/bin/env python3
"""Live status projection contracts for sessions.py.

Fixtures combine durable repository sessions with independent ephemeral state.
Merged worktrees stay available in all-history output but never become live.
Run: python3 -m pytest scripts/tests/test_sessions_presence_status.py.
"""

# contract-test-file: tooling

from scripts import sessions


def fixtures():
    durable = {
        "sessions": {
            "a111": {"opencode_session_id": "ses-stream", "task": "stream", "workspace_state": "checkpointed", "worktree": {"status": "active", "path": "/tmp/a"}},
            "b222": {"opencode_session_id": "ses-merged", "task": "merged", "worktree": {"status": "merged", "path": "/tmp/b"}},
            "c333": {"opencode_session_id": "ses-wait", "task": "wait", "worktree": {"status": "active", "path": "/tmp/c"}},
        },
        "locks": {},
        "edit_leases": {},
    }
    presence = {
        "sessions": {
            "ses-stream": {"session_id": "ses-stream", "execution": "busy", "turn": "streaming", "attention": "none", "updated_at": sessions._now_iso()},
            "ses-wait": {"session_id": "ses-wait", "execution": "idle", "turn": "streaming", "attention": "required_question", "updated_at": sessions._now_iso()},
            "ses-idle": {"session_id": "ses-idle", "execution": "idle", "turn": "completed", "attention": "optional", "updated_at": sessions._now_iso()},
        },
        "task_claims": {},
    }
    return durable, presence


def test_default_status_groups_live_reality_and_excludes_merged_history():
    durable, presence = fixtures()
    view = sessions.presence_status_view(durable, presence)
    assert [item["opencode_session_id"] for item in view["working"]] == ["ses-stream"]
    assert [item["opencode_session_id"] for item in view["waiting_for_user"]] == ["ses-wait"]
    assert [item["opencode_session_id"] for item in view["idle_after_response"]] == ["ses-idle"]
    assert "ses-merged" not in str(view)


def test_all_view_preserves_durable_history():
    durable, presence = fixtures()
    view = sessions.presence_status_view(durable, presence, include_all=True)
    assert {item["repository_session_id"] for item in view["all"]} == {"a111", "b222", "c333"}


def test_single_session_view_follows_identity_chain():
    durable, presence = fixtures()
    view = sessions.presence_status_view(durable, presence, session_filter="a111")
    assert view["session"]["repository_session_id"] == "a111"
    assert view["session"]["opencode_session_id"] == "ses-stream"
    assert view["session"]["worktree"]["status"] == "active"
    assert view["session"]["workspace_state"] == "checkpointed"


def test_status_projects_persisted_child_role_onto_existing_presence():
    durable, presence = fixtures()
    presence["sessions"]["ses-child"] = {
        "session_id": "ses-child",
        "execution": "idle",
        "turn": "completed",
        "attention": "none",
        "child_role": "unknown",
    }
    presence["child_roles"] = {
        "ses-child": {
            "session_id": "ses-child",
            "parent_id": "ses-stream",
            "role": "reviewer",
        }
    }

    view = sessions.presence_status_view(durable, presence, session_filter="a111")

    assert view["session"]["children"][0]["opencode_session_id"] == "ses-child"
    assert view["session"]["children"][0]["child_role"] == "reviewer"


def test_infrastructure_view_exposes_active_and_recent_docker_operations(monkeypatch):
    durable, presence = fixtures()
    monkeypatch.setattr(sessions, "_list_persistent_docker_operations", lambda: [])
    durable["infrastructure"] = {
        "test_leases": {
            "run-1": {"lease_id": "run-1", "owner": "tests", "resources": ["dev-stack"]},
        },
        "docker_operations": [
            {"id": "docker-old", "status": "completed", "services": ["cms"], "completed_at": "2026-08-05T08:00:00Z"},
            {"id": "docker-live", "status": "draining_tests", "services": ["api"], "session_id": "a111"},
        ],
    }

    view = sessions.presence_status_view(durable, presence)

    assert view["infrastructure"]["active_docker_operation"]["id"] == "docker-live"
    assert view["infrastructure"]["test_leases"][0]["lease_id"] == "run-1"
    assert view["infrastructure"]["recent_docker_operations"][0]["id"] == "docker-old"


def test_resource_wait_is_visible_instead_of_looking_idle():
    durable, presence = fixtures()
    durable["sessions"]["a111"]["resource_wait"] = {
        "status": "waiting",
        "resource": "docker_rebuild",
        "owner_session_id": "b222",
        "heartbeat_at": sessions._now_iso(),
    }

    view = sessions.presence_status_view(durable, presence)

    assert [item["repository_session_id"] for item in view["waiting_for_resource"]] == ["a111"]
    assert view["working"] == []


def test_coordination_section_lists_current_sessions_without_merged_history(monkeypatch):
    durable, presence = fixtures()
    durable["locks"] = {"docker_rebuild": {"status": "IN_PROGRESS", "claimed_by": "a111", "since": "2026-08-11T00:00:00Z"}}
    durable["edit_leases"] = {"scripts/sessions.py": {"session_id": "a111", "since": "2026-08-11T00:00:00Z"}}
    view = sessions.presence_status_view(durable, presence)
    monkeypatch.setattr(sessions, "_opencode_session_titles", lambda _ids: {"ses-idle": "Completed title"})
    monkeypatch.setattr(sessions, "_opencode_current_activity_label", lambda _session_id: "tool bash running")

    text = sessions._format_coordination_section("a111", durable, view)

    assert "COORDINATION" in text
    assert "Working now (1):" in text
    assert "a111  ses-stream  busy/streaming  stream" in text
    assert "Active task: tool bash running" in text
    assert "Waiting for user (1):" in text
    assert "c333  ses-wait  idle/streaming  wait" in text
    assert "Completed in last 1h (1):" in text
    assert "unbound  ses-idle  idle/completed  Completed title" in text
    assert "docker_rebuild: held by a111" in text
    assert "a111 holds 1 file" in text
    assert "ses-merged" not in text


def test_status_session_card_is_human_readable(monkeypatch):
    durable, presence = fixtures()
    view = sessions.presence_status_view(durable, presence, session_filter="a111")
    monkeypatch.setattr(sessions, "_opencode_session_titles", lambda _ids: {})
    monkeypatch.setattr(sessions, "_opencode_current_activity_label", lambda _session_id: "tool bash running")

    text = sessions._format_status_session_card(view["session"], {}, {})

    assert "Session a111" in text
    assert "State: busy/streaming" in text
    assert "Task: stream" in text
    assert "OpenCode: ses-stream" in text
    assert "Current activity: tool bash running" in text
    assert "{" not in text
