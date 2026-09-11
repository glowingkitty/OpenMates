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
    from codex_task_context import _INVOCATION_READS
    _INVOCATION_READS.clear()
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


def test_start_activates_one_and_preserves_active_operations():
    state = {"sessions": {"ecad": {"task_bridge": {}}}}
    sessions = SimpleNamespace(_load_sessions=lambda: state)
    tasks = [
        {
            "task_id": str(i),
            "external_chat": {"id": "thread"},
            "assignee_identity": "codex",
            "status": "todo",
        }
        for i in range(2)
    ]
    calls = []

    def reader(root, args):
        calls.append(args)
        if args[0] == "list":
            return {"tasks": tasks, "complete": True}
        tasks[0]["status"] = "in_progress"
        return {"task": tasks[0]}

    hook(None, "ecad", "thread", "SessionStart", {}, sessions, reader)
    hook(None, "ecad", "thread", "UserPromptSubmit", {}, sessions, reader)
    assert len([c for c in calls if c[0] == "edit"]) == 1
    assert tasks[1]["status"] == "todo"


def test_pending_recovery_retains_identity_and_does_not_replace_uncertain_intent():
    from codex_task_lifecycle import save_intent, finish_intent

    state = {"sessions": {"ecad": {"task_bridge": {}}}}
    sessions = SimpleNamespace(_mutate_sessions=lambda mutate: mutate(state))
    intent = {"delivery_id": "a" * 64}
    save_intent(sessions, "ecad", intent)
    with pytest.raises(RuntimeError, match="existing pending"):
        save_intent(sessions, "ecad", {"delivery_id": "b" * 64})
    finish_intent(sessions, "ecad", intent, {"activity_id": "ack"})
    assert (
        state["sessions"]["ecad"]["task_bridge"]["codex_outcome"]["delivery_id"]
        == "a" * 64
    )


def test_hook_allows_cli_development_inside_bound_workspace(tmp_path):
    from scripts.codex_hook_context import route
    for command in ["node frontend/packages/openmates-cli/dist/cli.js --help",
                    "node --loader tests/loader.mjs src/cli.ts --help",
                    "openmates tasks list", "node --test tests/taskDiscovery.test.ts"]:
        result = route("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}}, tmp_path, "ecad")
        assert str(tmp_path) in result["hookSpecificOutput"]["updatedInput"]["command"]
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_shared_429_stops_other_chats_and_honors_retry_after(monkeypatch, tmp_path):
    import codex_task_context as context
    calls = []
    clock = [1000]
    monkeypatch.setattr(context.time, "time", lambda: clock[0])
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stderr="HTTP429 Retry-After: 300")
    monkeypatch.setattr(context.subprocess, "run", run)
    for i in range(16):
        with pytest.raises(context.TaskDeliveryDeferred):
            context.cli(tmp_path, ["list", "--external-chat", f"codex:{i}"])
    assert len(calls) == 1
    clock[0] = 1299
    with pytest.raises(context.TaskDeliveryDeferred):
        context.cli(tmp_path, ["show", "owned-task"])
    assert len(calls) == 1
    clock[0] = 1301
    with pytest.raises(context.TaskDeliveryDeferred):
        context.cli(tmp_path, ["show", "owned-task"])
    assert len(calls) == 2


def test_global_slot_defers_parallel_chat_without_network(monkeypatch, tmp_path):
    import fcntl
    import codex_task_context as context
    directory = tmp_path / "logs/codex-task-context"
    directory.mkdir(parents=True)
    monkeypatch.setattr(context.subprocess, "run", lambda *a, **k: pytest.fail("network during another chat request"))
    with (directory / "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(context.TaskDeliveryDeferred, match="another chat"):
            context.cli(tmp_path, ["list"])


def test_same_hook_discovery_reused_but_mutation_invalidates(monkeypatch, tmp_path):
    import codex_task_context as context
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='{"complete":true,"tasks":[]}')
    monkeypatch.setattr(context.subprocess, "run", run)
    context.cli(tmp_path, ["list"])
    context.cli(tmp_path, ["list"])
    assert len(calls) == 1
    context.cli(tmp_path, ["edit", "t", "--status", "in_progress"])
    context.cli(tmp_path, ["list"])
    assert len(calls) == 3


def test_pending_outcome_survives_shared_cooldown():
    import codex_task_context as context
    pending = {"task_id": "t", "delivery_id": "stable"}
    state = {"sessions": {"ecad": {"task_bridge": {"codex_pending_outcome": pending}}}}
    sessions = SimpleNamespace(_load_sessions=lambda: state)
    def reader(*args):
        raise context.TaskDeliveryDeferred("cooldown")
    with pytest.raises(context.TaskDeliveryDeferred):
        hook(None, "ecad", "thread", "Stop", {}, sessions, reader)
    assert state["sessions"]["ecad"]["task_bridge"]["codex_pending_outcome"] == pending
