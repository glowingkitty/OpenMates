"""Regression tests for live Task smoke resource cleanup.

These tests keep shared dev test accounts reusable after successful, failed, or
interrupted smoke scenarios. They validate immediate resource registration,
Task-before-chat cleanup ordering, visible cleanup failures, and failure-safe
cleanup in both SDK implementations.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = ROOT / "scripts" / "verify_tasks_main_processor_cli_smoke.py"
SDK_SMOKE_PATH = ROOT / "scripts" / "verify_sdk_tasks_live_smoke.mjs"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("verify_tasks_main_processor_cli_smoke", SMOKE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
def test_created_chat_and_task_are_registered_immediately() -> None:
    smoke = _load_smoke_module()

    smoke.track_chat_result(
        {
            "chatId": "chat-created",
            "taskEvents": [
                {"event_type": "created", "task_id": "task-created"},
                {"event_type": "updated", "task_id": "task-existing"},
            ],
        }
    )

    assert smoke.CREATED_CHAT_IDS == {"chat-created"}
    assert smoke.CREATED_TASK_IDS == {"task-created"}


# contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
def test_cleanup_deletes_tasks_before_chats(monkeypatch: pytest.MonkeyPatch) -> None:
    smoke = _load_smoke_module()
    calls: list[tuple[str, str]] = []
    smoke.CREATED_TASK_IDS.update({"task-b", "task-a"})
    smoke.CREATED_CHAT_IDS.update({"chat-b", "chat-a"})
    monkeypatch.setattr(smoke, "delete_task", lambda task_id: calls.append(("task", task_id)))
    monkeypatch.setattr(smoke, "delete_chat", lambda chat_id: calls.append(("chat", chat_id)))

    smoke.cleanup_created_resources()

    assert calls == [
        ("task", "task-a"),
        ("task", "task-b"),
        ("chat", "chat-a"),
        ("chat", "chat-b"),
    ]


# contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
def test_cleanup_failure_is_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    smoke = _load_smoke_module()
    smoke.CREATED_TASK_IDS.add("task-failed")
    monkeypatch.setattr(smoke, "delete_task", lambda _task_id: "task task-failed: HTTP 500")

    with pytest.raises(RuntimeError, match="task-failed: HTTP 500"):
        smoke.cleanup_created_resources()


# contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
def test_cleanup_continues_after_delete_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    smoke = _load_smoke_module()
    calls: list[tuple[str, str]] = []
    smoke.CREATED_TASK_IDS.update({"task-failed", "task-ok"})
    smoke.CREATED_CHAT_IDS.add("chat-ok")

    def delete_task(task_id: str) -> None:
        calls.append(("task", task_id))
        if task_id == "task-failed":
            raise TimeoutError("delete timed out")

    monkeypatch.setattr(smoke, "delete_task", delete_task)
    monkeypatch.setattr(smoke, "delete_chat", lambda chat_id: calls.append(("chat", chat_id)))

    with pytest.raises(RuntimeError, match="task task-failed: delete timed out"):
        smoke.cleanup_created_resources()

    assert calls == [("task", "task-failed"), ("task", "task-ok"), ("chat", "chat-ok")]


# contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
def test_cleanup_does_not_replace_primary_smoke_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    smoke = _load_smoke_module()
    primary_error = AssertionError("scenario failed")
    monkeypatch.setattr(
        smoke,
        "cleanup_created_resources",
        lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )

    smoke.cleanup_after_smoke(primary_error)

    assert "Task smoke cleanup also failed: cleanup failed" in capsys.readouterr().err


# contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
def test_sdk_smoke_has_npm_and_pip_finally_cleanup() -> None:
    source = SDK_SMOKE_PATH.read_text(encoding="utf-8")

    assert "if (!primaryError) throw cleanupError;" in source
    assert "if primary_error is None:\n                raise" in source
    assert "npm SDK Task cleanup also failed" in source
    assert "pip SDK Task cleanup also failed" in source
    assert source.count("finally") >= 3
