# contract-test-file: tooling
"""Exercise turn reconciliation through a recording global CLI transport.

No browser, account, provider or runtime is contacted by these unit tests.
Unknown delivery must retain pending intent; replay reuses its activity ID.
Task state comes only from acknowledged CLI records, never final-text inference.
The hook protects final outcomes without operating on commentary events.
"""

from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from codex_task_lifecycle import reconcile, hook  # noqa: E402
from codex_task_context import cli  # noqa: E402


def test_global_only_preserves_auth_context(monkeypatch, tmp_path):
    def run(command, **kwargs):
        assert command == ["openmates", "tasks", "list", "--json"]
        assert "env" not in kwargs
        assert kwargs["cwd"] == tmp_path
        return SimpleNamespace(returncode=0, stdout='{"tasks":[],"complete":true}')

    monkeypatch.setattr("codex_task_context.subprocess.run", run)
    assert cli(tmp_path, ["list"])["complete"]
    monkeypatch.setattr(
        "codex_task_context.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="Only opencode allowed"),
    )
    with pytest.raises(RuntimeError, match="Only opencode allowed"):
        cli(tmp_path, ["list"])


@pytest.mark.parametrize("status", ["in_progress", "blocked", "done"])
def test_reconciliation_replay_and_ack(status):
    task = {
        "task_id": "t",
        "status": "todo",
        "external_chat": {"id": "thread"},
        "assignee_identity": "codex",
    }
    calls = []
    intent = dict(
        task_id="t",
        thread="thread",
        status=status,
        reason="Approval pending",
        reason_code="waiting_for_approval",
        summary="Outcome",
        next_action="Review linked proposal",
        approval="https://example.com/review",
        delivery_id="a" * 64,
    )

    def reader(root, args):
        calls.append(args)
        if args[0] == "show":
            return {"task": dict(task)}
        if args[:2] == ["activity", "flush"]:
            return {"pending": 0}
        if args[:2] == ["activity", "add"]:
            return {"entry": {"task_id": "t", "entry_id": "entry", "message": args[-1]}}
        task["status"] = status
        task["blocked_reason"] = intent["reason"]
        return {"task": dict(task)}

    assert reconcile(None, intent, reader)["status"] == status
    assert reconcile(None, intent, reader)["status"] == status
    assert len([c for c in calls if c[0] in ["edit", "block", "done"]]) == 1
    assert all(
        c[c.index("--delivery-id") + 1] == "a" * 64
        for c in calls
        if "--delivery-id" in c
    )


def test_uncertain_activity_does_not_acknowledge():
    intent = dict(
        task_id="t",
        thread="thread",
        status="in_progress",
        summary="Working",
        next_action="Verify",
        delivery_id="b" * 64,
    )

    def reader(root, args):
        if args[0] == "show":
            return {
                "task": {
                    "task_id": "t",
                    "status": "in_progress",
                    "external_chat": {"id": "thread"},
                    "assignee_identity": "codex",
                }
            }
        return {"pending": 1}

    with pytest.raises(RuntimeError, match="acknowledgement missing"):
        reconcile(None, intent, reader)


def test_stop_requires_current_turn_and_persisted_outcome():
    outcome = dict(
        task_id="t",
        turn="turn",
        status="blocked",
        summary="Approval pending",
        next_action="Review proposal",
    )
    state = {"sessions": {"ecad": {"task_bridge": {"codex_outcome": outcome}}}}
    sessions = SimpleNamespace(_load_sessions=lambda: state)

    def reader(root, args):
        return {
            "complete": True,
            "tasks": [
                {
                    "task_id": "t",
                    "external_chat": {"id": "thread"},
                    "assignee_identity": "codex",
                    "status": "blocked",
                }
            ],
        }

    result = hook(
        None,
        "ecad",
        "thread",
        "Stop",
        {
            "turn_id": "old",
            "last_assistant_message": "Approval pending. Review proposal",
        },
        sessions,
        reader,
    )
    assert result["decision"] == "block"
    assert (
        hook(
            None,
            "ecad",
            "thread",
            "Stop",
            {
                "turn_id": "turn",
                "last_assistant_message": "Approval pending. Review proposal",
            },
            sessions,
            reader,
        )
        == {}
    )
