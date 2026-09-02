#!/usr/bin/env python3
"""Deterministic contracts for the OpenCode-to-OpenMates Task bridge.

The bridge may read decrypted Task text only from trusted CLI JSON for the
current request. Durable repository-session state must retain identifiers,
versions, hashes, generations, and response-boundary ids only.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_task_bridge", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def task(
    short_id: str,
    *,
    status: str = "todo",
    position: int = 1,
    version: int = 1,
    assignee_type: str = "ai",
    queue_state: str = "none",
    ai_execution_state: str | None = None,
) -> dict:
    return {
        "task_id": f"uuid-{short_id}",
        "short_id": short_id,
        "title": f"Private title for {short_id}",
        "description": f"Private description for {short_id}",
        "latest_instruction": f"Private instruction for {short_id}",
        "status": status,
        "position": position,
        "version": version,
        "assignee_type": assignee_type,
        "queue_state": queue_state,
        "ai_execution_state": ai_execution_state,
        "blocked_reason_code": "external_dependency" if status == "blocked" else None,
        "blocked_reason": "Private blocker" if status == "blocked" else None,
        "external_chat": {"provider": "opencode", "id": "ses_parent", "title": "Private chat"},
    }


def state() -> dict:
    return {
        "sessions": {
            "4bf3": {
                "opencode_session_id": "ses_parent",
                "modified_files": [],
            }
        }
    }


def install_mutator(monkeypatch, sessions, data):
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))


def test_task_cli_auth_failure_preserves_actionable_reason(monkeypatch) -> None:
    sessions = load_sessions_module()

    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["openmates", "tasks", "list"],
            returncode=1,
            stdout="",
            stderr=json.dumps({
                "error": {
                    "code": "command_failed",
                    "message": "Session validation failed (HTTP 200): Passkey verification required (location_change). Please run `openmates login`.",
                }
            }),
        )

    monkeypatch.setattr(sessions.subprocess, "run", run)
    try:
        sessions._run_openmates_task_cli(["tasks", "list", "--json"])
    except RuntimeError as error:
        message = str(error)
        assert "Passkey verification required (location_change)" in message
        assert "openmates login" in message
        assert "do not retry" in message.lower()
    else:
        raise AssertionError("Task CLI authentication failures must fail with actionable context")


def test_snapshot_classification_is_deterministic_and_fail_closed() -> None:
    sessions = load_sessions_module()

    active = sessions._classify_openmates_task_snapshot([
        task("TASK-2", status="todo", position=2),
        task("TASK-1", status="in_progress", position=1, version=4),
    ])
    assert active["decision"] == "resume_active"
    assert active["active"]["short_id"] == "TASK-1"
    assert [item["short_id"] for item in active["remaining"]] == ["TASK-2"]

    next_task = sessions._classify_openmates_task_snapshot([
        task("TASK-2", status="todo", position=2),
        task("TASK-1", status="todo", position=1),
    ])
    assert next_task["decision"] == "activate_next"
    assert next_task["active"]["short_id"] == "TASK-1"

    blocked = sessions._classify_openmates_task_snapshot([
        task("TASK-1", status="blocked", queue_state="waiting_for_user"),
        task("TASK-2", status="todo", position=2),
    ])
    assert blocked["decision"] == "wait_blocked"
    assert blocked["active"]["short_id"] == "TASK-1"

    user_owned = sessions._classify_openmates_task_snapshot([
        task("TASK-1", status="todo", assignee_type="user"),
    ])
    assert user_owned["decision"] == "no_work"

    try:
        sessions._classify_openmates_task_snapshot([
            task("TASK-1", status="in_progress"),
            task("TASK-2", status="in_progress"),
        ])
    except RuntimeError as error:
        assert "multiple active" in str(error).lower()
    else:
        raise AssertionError("multiple active Tasks must fail closed")


def test_workflow_projections_and_wrong_external_context_are_rejected() -> None:
    sessions = load_sessions_module()
    payload = {
        "tasks": [
            {**task("WF-123"), "task_id": "workflow-run:123", "source": "workflow_run"},
            {
                **task("TASK-WRONG"),
                "external_chat": {"provider": "opencode", "id": "ses_other", "title": "private"},
            },
            {
                **task("TASK-RIGHT"),
                "external_chat": {"provider": "opencode", "id": "ses_parent", "title": "private"},
            },
        ]
    }

    filtered = sessions._validated_openmates_task_records(payload, "ses_parent")

    assert [item["short_id"] for item in filtered] == ["TASK-RIGHT"]

    try:
        sessions._validated_openmates_task_records(
            {"tasks": [{key: value for key, value in task("TASK-UNSCOPED").items() if key != "external_chat"}]},
            "ses_parent",
        )
    except RuntimeError as error:
        assert "external context" in str(error).lower()
    else:
        raise AssertionError("unscoped legacy CLI output must fail closed")


def test_stage_and_reconcile_store_no_decrypted_task_text(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = state()
    install_mutator(monkeypatch, sessions, data)
    calls: list[list[str]] = []

    def cli(args: list[str]) -> dict:
        calls.append(args)
        if args[:2] == ["tasks", "list"]:
            return {"tasks": [task("TASK-1", status="in_progress", version=7)]}
        raise AssertionError(args)

    first = sessions._stage_openmates_task_reconciliation("ses_parent", "msg_done")
    duplicate = sessions._stage_openmates_task_reconciliation("ses_parent", "msg_done")
    result = sessions._reconcile_openmates_tasks("ses_parent", cli_runner=cli)

    assert first["staged"] is True
    assert duplicate["staged"] is False
    assert result["decision"] == "resume_active"
    assert result["continuation"]["operation_type"] == "task_ready"
    assert calls == [["tasks", "list", "--external-chat", "opencode:ses_parent", "--json"]]

    durable = json.dumps(data, sort_keys=True)
    assert "Private title" not in durable
    assert "Private description" not in durable
    assert "Private instruction" not in durable
    assert "Private blocker" not in durable
    metadata = data["sessions"]["4bf3"]["task_bridge"]
    assert metadata["task_id"] == "uuid-TASK-1"
    assert metadata["task_version"] == 7
    assert metadata["generation"] == 1
    assert metadata["last_reconciled_message_id"] == "msg_done"


def test_activate_next_mutates_once_and_uses_versioned_continuation_key(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = state()
    install_mutator(monkeypatch, sessions, data)
    calls: list[list[str]] = []

    def cli(args: list[str]) -> dict:
        calls.append(args)
        if args[:2] == ["tasks", "list"]:
            return {"tasks": [task("TASK-1", status="todo", version=3)]}
        if args[:2] == ["tasks", "edit"]:
            return {"task": task("TASK-1", status="in_progress", version=4)}
        raise AssertionError(args)

    sessions._stage_openmates_task_reconciliation("ses_parent", "msg_one")
    first = sessions._reconcile_openmates_tasks("ses_parent", cli_runner=cli)
    second = sessions._reconcile_openmates_tasks("ses_parent", cli_runner=cli)

    assert first["decision"] == "activate_next"
    assert calls[1] == ["tasks", "edit", "uuid-TASK-1", "--status", "in_progress", "--json"]
    assert first["continuation"]["operation_key"].endswith(":uuid-TASK-1:4:1")
    assert second["decision"] == "already_reconciled"
    assert len(calls) == 2


def test_context_keeps_full_active_details_and_minimal_remaining_titles() -> None:
    sessions = load_sessions_module()
    snapshot = sessions._openmates_task_context_from_payload(
        {
            "tasks": [
                task("TASK-2", status="todo", position=2),
                task("TASK-1", status="in_progress", position=1),
            ]
        },
        "ses_parent",
    )

    assert snapshot["active"]["description"] == "Private description for TASK-1"
    assert snapshot["active"]["latest_instruction"] == "Private instruction for TASK-1"
    assert snapshot["remaining"] == [
        {"short_id": "TASK-2", "title": "Private title for TASK-2", "status": "todo"}
    ]


def test_typed_tool_scopes_creates_and_mutations_to_the_bound_chat(monkeypatch) -> None:
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_load_sessions", state)
    calls: list[list[str]] = []

    def cli(args: list[str]) -> dict:
        calls.append(args)
        return {"task": task("TASK-9", status="todo")}

    created = sessions._openmates_task_tool(
        "ses_parent",
        {"action": "create", "title": "Private new title", "description": "Private body", "status": "in_progress"},
        cli_runner=cli,
    )
    started = sessions._openmates_task_tool(
        "ses_parent",
        {"action": "start", "task_id": "TASK-9"},
        cli_runner=cli,
    )
    blocked = sessions._openmates_task_tool(
        "ses_parent",
        {
            "action": "block",
            "task_id": "TASK-9",
            "reason_code": "external_dependency",
            "reason_text": "Private wait detail",
        },
        cli_runner=cli,
    )

    assert created["task"]["short_id"] == "TASK-9"
    assert started["task"]["short_id"] == "TASK-9"
    assert blocked["task"]["short_id"] == "TASK-9"
    assert calls == [
        [
            "tasks", "create", "--title", "Private new title", "--description", "Private body",
            "--assign", "user", "--external-chat", "opencode:ses_parent", "--json",
        ],
        [
            "tasks", "edit", "uuid-TASK-9", "--assign", "ai", "--status", "in_progress",
            "--external-chat", "opencode:ses_parent", "--json",
        ],
        [
            "tasks", "edit", "TASK-9", "--status", "in_progress",
            "--external-chat", "opencode:ses_parent", "--json",
        ],
        [
            "tasks", "block", "TASK-9", "--reason-code", "external_dependency",
            "--reason-text", "Private wait detail", "--external-chat", "opencode:ses_parent", "--json",
        ],
    ]


def test_typed_tool_rejects_unknown_actions_and_unbound_sessions(monkeypatch) -> None:
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_load_sessions", state)

    for reference, payload, message in (
        ("ses_parent", {"action": "delete", "task_id": "TASK-1"}, "unsupported"),
        ("not-a-session", {"action": "context"}, "session"),
        ("ses_parent", {"action": "block", "task_id": "TASK-1", "reason_code": "invented"}, "reason"),
    ):
        try:
            sessions._openmates_task_tool(reference, payload, cli_runner=lambda _args: {})
        except RuntimeError as error:
            assert message in str(error).lower()
        else:
            raise AssertionError(f"{payload} must fail closed")


def test_new_top_level_chat_can_read_and_create_before_worktree_binding(monkeypatch) -> None:
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {}})
    calls: list[list[str]] = []

    def cli(args: list[str]) -> dict:
        calls.append(args)
        if args[:2] == ["tasks", "list"]:
            return {"tasks": []}
        if args[:2] == ["tasks", "create"]:
            return {"task": task("TASK-NEW", assignee_type="user")}
        if args[:2] == ["tasks", "edit"]:
            return {"task": task("TASK-NEW", assignee_type="ai", version=2)}
        raise AssertionError(args)

    context = sessions._openmates_task_context("ses_newchat", cli_runner=cli)
    created = sessions._openmates_task_tool(
        "ses_newchat",
        {"action": "create", "title": "Implicit multi-step work"},
        cli_runner=cli,
    )

    assert context == {"decision": "no_work", "active": None, "remaining": []}
    assert created["task"]["assignee_type"] == "ai"
    assert all("opencode:ses_newchat" in command for command in calls)


def test_staged_reconciliation_survives_process_restart(tmp_path, monkeypatch) -> None:
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps(state()), encoding="utf-8")
    first_process = load_sessions_module()
    monkeypatch.setattr(first_process, "SESSIONS_FILE", sessions_file)
    assert first_process._stage_openmates_task_reconciliation("ses_parent", "msg_restart")["staged"]

    second_process = load_sessions_module()
    monkeypatch.setattr(second_process, "SESSIONS_FILE", sessions_file)
    calls: list[list[str]] = []

    def cli(args: list[str]) -> dict:
        calls.append(args)
        return {"tasks": [task("TASK-1", status="in_progress", version=8)]}

    reconciled = second_process._reconcile_openmates_tasks("ses_parent", cli_runner=cli)
    duplicate = second_process._reconcile_openmates_tasks("ses_parent", cli_runner=cli)

    assert reconciled["decision"] == "resume_active"
    assert duplicate["decision"] == "already_reconciled"
    assert len(calls) == 1
    durable = sessions_file.read_text(encoding="utf-8")
    assert "Private title" not in durable
    assert "Private description" not in durable
