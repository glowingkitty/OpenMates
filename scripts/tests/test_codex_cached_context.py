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


# contract-test: tooling
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


# contract-test: tooling
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


# contract-test: tooling
def test_unchanged_turns_are_silent_and_resume_restores_full_context(
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
    assert cached.context(tmp_path, "session", THREAD, "UserPromptSubmit", config) == ""
    assert "Split complex workflows" in cached.context(tmp_path, "session", THREAD, "SessionStart", config)


# contract-test: tooling
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


# contract-test: tooling
def test_runtime_preflight_rejects_modified_hook_without_starting_inference(tmp_path):
    class RPC:
        def call(self, method, params):
            assert method == "hooks/list" and params == {"cwds": [str(tmp_path)]}
            return {"data": [{"hooks": [
                {"eventName": event, "enabled": True, "trustStatus": "modified" if event == "sessionStart" else "trusted",
                 "sourcePath": str(tmp_path / ".codex/hooks.json"), "command": "bash claude-hook-bridge.sh"}
                for event in cached.REQUIRED_CONTEXT_HOOKS]}]}
    result = cached.runtime_preflight(tmp_path, RPC())
    assert result["status"] == "needs_attention"
    assert result["hooks_needing_review"] == ["sessionStart"]
    assert "/hooks" in result["resolution"]


# contract-test: tooling
def test_runtime_preflight_requires_all_enabled_project_context_hooks(tmp_path):
    class RPC:
        def call(self, *_):
            return {"data": [{"hooks": [
                {"eventName": event, "enabled": event != "postToolUse", "trustStatus": "trusted",
                 "sourcePath": str(tmp_path / ".codex/hooks.json"), "command": "bash claude-hook-bridge.sh"}
                for event in cached.REQUIRED_CONTEXT_HOOKS]}]}
    assert cached.runtime_preflight(tmp_path, RPC())["missing_hooks"] == ["postToolUse"]


# contract-test: tooling
def test_runtime_preflight_accepts_reviewed_project_hooks(tmp_path):
    class RPC:
        def call(self, *_):
            return {"data": [{"hooks": [
                {"eventName": event, "enabled": True, "trustStatus": "trusted",
                 "sourcePath": str(tmp_path / ".codex/hooks.json"), "command": "bash claude-hook-bridge.sh"}
                for event in cached.REQUIRED_CONTEXT_HOOKS]}]}
    assert cached.runtime_preflight(tmp_path, RPC())["status"] == "ready"


# contract-test: tooling
def test_repository_cutover_covers_new_unregistered_chats(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENMATES_STATE_DIR', str(tmp_path / 'cli'))
    config = tmp_path / 'cli/codex-adapter.json'
    config.parent.mkdir()
    entry = {'enabled': True, 'all_threads': True, 'threads': [THREAD], 'snapshots': []}
    config.write_text(json.dumps({'repositories': {str(tmp_path.resolve()): entry}}))
    assert cached.configuration(tmp_path, WORKER) == entry
    entry['all_threads'] = False
    config.write_text(json.dumps({'repositories': {str(tmp_path.resolve()): entry}}))
    assert cached.configuration(tmp_path, WORKER) is None
