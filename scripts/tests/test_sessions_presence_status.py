#!/usr/bin/env python3
"""Live status projection contracts for sessions.py.

Fixtures combine durable repository sessions with independent ephemeral state.
Merged worktrees stay available in all-history output but never become live.
Run: python3 -m pytest scripts/tests/test_sessions_presence_status.py.
"""

from scripts import sessions


def fixtures():
    durable = {
        "sessions": {
            "a111": {"opencode_session_id": "ses-stream", "task": "stream", "worktree": {"status": "active", "path": "/tmp/a"}},
            "b222": {"opencode_session_id": "ses-merged", "task": "merged", "worktree": {"status": "merged", "path": "/tmp/b"}},
            "c333": {"opencode_session_id": "ses-wait", "task": "wait", "worktree": {"status": "active", "path": "/tmp/c"}},
        },
        "locks": {},
        "edit_leases": {},
    }
    presence = {
        "sessions": {
            "ses-stream": {"session_id": "ses-stream", "execution": "busy", "turn": "streaming", "attention": "none"},
            "ses-wait": {"session_id": "ses-wait", "execution": "idle", "turn": "streaming", "attention": "required_question"},
            "ses-idle": {"session_id": "ses-idle", "execution": "idle", "turn": "completed", "attention": "optional"},
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


def test_infrastructure_view_exposes_active_and_recent_docker_operations():
    durable, presence = fixtures()
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
