"""Disk-only context contract: all Tasks, worker scope, deltas and silence.

Temporary cache/config fixtures stand in for the foreground CLI's private files.
No CLI requests, model invocations or live project hook changes occur here.
The renderer must preserve blockers and every full title without final-text gates.
See docs/plans/codex-tasks-orchestration/plan.yml.
"""

import json
from scripts import codex_cached_context as cached

THREAD = "00000000-0000-0000-0000-000000000001"
WORKER = "00000000-0000-0000-0000-000000000002"


def test_complete_start_then_silent_unchanged_tools_and_one_task_delta(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENMATES_STATE_DIR", str(tmp_path / "cli"))
    snapshot = tmp_path / "snapshot.json"
    tasks = [
        {
            "task_id": str(i),
            "short_id": f"TASK-{i}",
            "title": f"Work {i}",
            "status": "todo",
            "external_chat": {"provider": "codex", "id": THREAD},
            "description": "detail " * 500,
            "latest_activity": "activity " * 500,
            "blocked_reason": "Approval pending",
        }
        for i in range(12)
    ]
    data = {
        "schema_version": 1,
        "project_id": "project",
        "connection": "connected",
        "tasks": tasks,
    }
    snapshot.write_text(json.dumps(data))
    config = {"snapshots": [str(snapshot)]}
    output = cached.context(tmp_path, "session", THREAD, "SessionStart", config)
    for task in tasks:
        assert task["title"] in output
    assert "Approval pending" in output
    assert "detail " * 500 not in output
    assert cached.context(tmp_path, "session", THREAD, "PostToolUse", config) == ""
    assert cached.context(tmp_path, "session", THREAD, "Stop", config) == ""
    tasks[4]["status"] = "in_progress"
    snapshot.write_text(json.dumps(data))
    delta = cached.context(tmp_path, "session", THREAD, "PostToolUse", config)
    assert "Work 4" in delta and "in_progress" in delta
    assert "Work 5" not in delta


def test_orchestrator_sees_its_workers_but_no_unrelated_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_STATE_DIR", str(tmp_path / "cli"))
    registry = tmp_path / "logs/codex-orchestration/session/state.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "coordinator": THREAD,
                "workers": {WORKER: {"title": "Landing - Header", "status": "idle"}},
            }
        )
    )
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "project",
                "connection": "connected",
                "tasks": [
                    {
                        "task_id": "1",
                        "title": "Header work",
                        "status": "todo",
                        "external_chat": {"provider": "codex", "id": WORKER},
                    },
                    {
                        "task_id": "2",
                        "title": "Unrelated work",
                        "status": "todo",
                        "external_chat": {"provider": "codex", "id": "elsewhere"},
                    },
                ],
            }
        )
    )
    output = cached.context(
        tmp_path, "session", THREAD, "SessionStart", {"snapshots": [str(snapshot)]}
    )
    assert (
        '"Landing - Header"' in output and WORKER in output and "Header work" in output
    )
    assert "Unrelated work" not in output
    assert "wait_threads" in output and "read_thread" in output
    assert "Every user-facing response must include" not in output


def test_new_user_turn_after_tools_gets_full_context_but_initial_overlap_does_not(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENMATES_STATE_DIR", str(tmp_path / "cli"))
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "project",
                "connection": "stopped",
                "tasks": [],
            }
        )
    )
    config = {"snapshots": [str(path)]}
    assert cached.context(tmp_path, "session", THREAD, "SessionStart", config)
    assert cached.context(tmp_path, "session", THREAD, "UserPromptSubmit", config) == ""
    assert cached.context(tmp_path, "session", THREAD, "PostToolUse", config) == ""
    assert "Split complex workflows" in cached.context(
        tmp_path, "session", THREAD, "UserPromptSubmit", config
    )


def test_context_omits_dependency_storage_fields_and_retry_bookkeeping():
    row = cached.render_row(
        {
            "task_id": "one",
            "title": "Work",
            "status": "blocked",
            "dependencies": [
                {
                    "target_kind": "task",
                    "target_id": "two",
                    "target_status": "done",
                    "hashed_user_id": "private-index",
                    "created_at": 123,
                }
            ],
        }
    )
    assert "task:two [done]" in row
    assert "private-index" not in row and "created_at" not in row
    event = {
        "kind": "dependency_ready",
        "state": "pending",
        "data": {"task_id": "one", "title": "Work"},
        "message_id": "delivery-internal",
        "retry_at": 123,
    }
    rendered = cached.render_event(event)
    assert 'Dependency ready: "Work"' in rendered
    event["retry_at"] = 456
    assert cached.render_event(event) == rendered
    assert "delivery-internal" not in rendered
