"""Reconcile Codex turn outcomes through the authoritative global Task CLI.

The existing session task_bridge holds pending turn intent, not Task state.
The CLI's encrypted activity outbox owns delivery retries and acknowledgements.
A Stop hook verifies persisted state and final text before allowing a turn to end.
No commentary hook, account override, inference, or cross-thread send is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

from codex_task_context import cli


def owned(root, thread, reader=cli):
    response = reader(root, ["list", "--external-chat", f"codex:{thread}"])
    if response.get("complete") is not True:
        raise RuntimeError(
            "Global openmates lacks complete task discovery; update the installed CLI"
        )
    tasks = response["tasks"]
    for task in tasks:
        if task.get("external_chat", {}).get("id") != thread:
            raise RuntimeError("Task scope mismatch")
    return [t for t in tasks if t.get("assignee_identity") == "codex"]


def reconcile(root, intent, reader=cli):
    """Acknowledge durable activity before the read-before-write state transition."""
    task_id = intent["task_id"]
    task = reader(root, ["show", task_id])["task"]
    if (
        task.get("external_chat", {}).get("id") != intent["thread"]
        or task.get("assignee_identity") != "codex"
    ):
        raise RuntimeError("Lifecycle intent does not own this Task")
    target = intent["status"]
    message = intent["summary"] + "\nNext action: " + intent["next_action"]
    if intent.get("approval"):
        message += "\nApproval: " + intent["approval"]
    ack = reader(
        root,
        [
            "activity",
            "add",
            task_id,
            "--as-assignee",
            "--delivery-id",
            intent["delivery_id"],
            "--message",
            message,
        ],
    )
    if (
        ack.get("entry", {}).get("task_id") != task_id
        or ack["entry"].get("message") != message
    ):
        raise RuntimeError(
            "Task activity acknowledgement missing; flush existing outbox before retry"
        )
    if task["status"] != target or (
        target == "blocked" and task.get("blocked_reason") != intent["reason"]
    ):
        if target == "blocked":
            command = [
                "block",
                task_id,
                "--reason-code",
                intent["reason_code"],
                "--reason-text",
                intent["reason"],
            ]
        elif target == "done":
            flushed = reader(root, ["activity", "flush", task_id, "--as-assignee"])
            if flushed.get("pending"):
                raise RuntimeError(
                    "Pending Task activity must be acknowledged before done"
                )
            command = ["done", task_id]
        else:
            command = ["edit", task_id, "--status", "in_progress"]
        task = reader(root, command)["task"]
        if task.get("status") != target:
            raise RuntimeError("Task transition acknowledgement mismatch")
    return {"status": target, "activity_id": ack["entry"]["entry_id"]}


def save_intent(sessions, sid, intent):
    def mutate(data):
        bridge = data["sessions"][sid].setdefault("task_bridge", {})
        pending = bridge.get("codex_pending_outcome")
        if pending and pending["delivery_id"] != intent["delivery_id"]:
            raise RuntimeError(
                "Reconcile the existing pending outcome before replacing it"
            )
        bridge["codex_pending_outcome"] = intent

    sessions._mutate_sessions(mutate)


def finish_intent(sessions, sid, intent, ack):
    def mutate(data):
        bridge = data["sessions"][sid].setdefault("task_bridge", {})
        if (
            bridge.get("codex_pending_outcome", {}).get("delivery_id")
            != intent["delivery_id"]
        ):
            raise RuntimeError(
                "Concurrent Task outcome changed; retained pending intent"
            )
        bridge["codex_outcome"] = {**intent, "ack": ack}
        bridge.pop("codex_pending_outcome", None)

    sessions._mutate_sessions(mutate)


def hook(root, sid, thread, event, payload, sessions, reader=cli):
    bridge = sessions._load_sessions()["sessions"][sid].get("task_bridge", {})
    pending = bridge.get("codex_pending_outcome")
    if pending:
        finish_intent(sessions, sid, pending, reconcile(root, pending, reader))
    tasks = owned(root, thread, reader)
    if not tasks:
        return {}  # Never invent/recreate a Task or bind another account's record.
    if event in {"SessionStart", "UserPromptSubmit"}:
        if any(t["status"] in {"in_progress", "blocked"} for t in tasks):
            return {}
        for task in tasks:
            if task["status"] in {"todo", "backlog"}:
                updated = reader(
                    root, ["edit", task["task_id"], "--status", "in_progress"]
                )
                if updated.get("task", {}).get("status") != "in_progress":
                    raise RuntimeError("Task start acknowledgement missing")
                break
        return {}
    if event != "Stop":
        return {}
    outcome = (
        sessions._load_sessions()["sessions"][sid]
        .get("task_bridge", {})
        .get("codex_outcome")
    )
    text = payload.get("last_assistant_message", "")
    if (
        not outcome
        or not text
        or outcome.get("turn") != payload.get("turn_id")
        or outcome["summary"] not in text
    ):
        return {
            "decision": "block",
            "reason": "Persist this turn's Task outcome with scripts/codex_task_lifecycle.py before ending. Final text must include its exact summary; preserve unresolved decisions and next action. Do not mark partial work done.",
        }
    matching = next((t for t in tasks if t["task_id"] == outcome["task_id"]), None)
    if not matching or matching["status"] != outcome["status"]:
        return {
            "decision": "block",
            "reason": "Final Task outcome differs from authoritative persisted status; reconcile before ending.",
        }
    if outcome["status"] == "blocked" and any(
        value and value not in text
        for value in (
            outcome["next_action"],
            outcome.get("reason"),
            outcome.get("approval"),
        )
    ):
        return {
            "decision": "block",
            "reason": "Include the unresolved blocker and exact next action in the final response.",
        }
    return {}


def main():
    import sessions

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--turn", required=True)
    parser.add_argument(
        "--status", choices=["in_progress", "blocked", "done"], required=True
    )
    parser.add_argument("--summary", required=True)
    parser.add_argument("--next-action", required=True)
    parser.add_argument("--reason-code", default="external_dependency")
    parser.add_argument("--reason", default="")
    parser.add_argument("--approval", default="")
    args = parser.parse_args()
    if not all(value.strip() for value in (args.turn, args.task, args.summary, args.next_action)):
        parser.error("Task, turn, summary and next action must be nonempty")
    record = sessions._load_sessions()["sessions"][args.session]
    thread = record.get("codex_thread_id") or record.get("codex_task_id")
    if not thread:
        raise RuntimeError("Existing session lacks a Codex binding")
    if args.status == "blocked" and not args.reason.strip():
        parser.error("blocked requires an exact --reason and --next-action")
    if (
        args.status == "blocked"
        and args.reason_code == "waiting_for_approval"
        and not args.approval
    ):
        parser.error("approval blocker requires the exact --approval link")
    intent = {
        "task_id": args.task,
        "thread": thread,
        "turn": args.turn,
        "status": args.status,
        "summary": args.summary,
        "next_action": args.next_action,
        "reason": args.reason,
        "reason_code": args.reason_code,
        "approval": args.approval,
    }
    intent["delivery_id"] = hashlib.sha256(
        json.dumps(intent, sort_keys=True).encode()
    ).hexdigest()
    save_intent(sessions, args.session, intent)
    ack = reconcile(sessions.CONTROL_PLANE_ROOT, intent)
    finish_intent(sessions, args.session, intent, ack)
    print(json.dumps(ack))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
