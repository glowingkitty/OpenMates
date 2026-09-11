"""Foreground Codex event delivery beside the OpenMates remote-access connection.

Reads account-scoped Task snapshots and the existing CI coordinator's local DB.
One persistent app-server connection observes metadata; routine activity never
starts a model. Durable delivery IDs fence uncertain starts across restarts.
Explicit repository/thread opt-in is required; nothing installs a background OS
service. Integration state is private and separate from the Task data model.
"""

from __future__ import annotations
import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import select
import socket
import sqlite3
import sys
import time
import uuid

try:
    from scripts.codex_cached_context import _save, state_root
    from scripts.codex_rpc import CodexRPC, CodexRPCRejected
except ModuleNotFoundError:
    from codex_cached_context import _save, state_root
    from codex_rpc import CodexRPC, CodexRPCRejected


def identity(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def adapter_path(root):
    return (
        state_root() / "codex-adapters" / identity(str(root.resolve())) / "state.json"
    )


def empty_state():
    return {
        "schema_version": 1,
        "tasks": {},
        "threads": {},
        "deliveries": {},
        "ci_seen": {},
    }


def queue(state, owner, kind, key, data):
    event = identity([owner, kind, key])
    state["deliveries"].setdefault(
        event,
        {
            "id": event,
            "owner": owner,
            "kind": kind,
            "data": data,
            "state": "pending",
            "message_id": str(uuid.uuid4()),
            "created_at": time.time(),
        },
    )


def load_tasks(config):
    tasks = {}
    for name in config.get("snapshots", []):
        snapshot = json.loads(Path(name).read_text())
        # Disconnected files remain context, but cannot authorize automatic work.
        if snapshot.get("connection") != "connected":
            continue
        refreshed = datetime.fromisoformat(snapshot["synced_at"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - refreshed).total_seconds() > 120:
            continue
        for task in snapshot["tasks"]:
            key = identity([snapshot["account_scope"], task["task_id"]])
            tasks[key] = {**task, "scope": snapshot["account_scope"]}
    return tasks


def dependency_ready(previous, current):
    owner = current.get("external_chat") or {}
    return (
        previous.get("status") == "blocked"
        and previous.get("blocked_reason_code") == "external_dependency"
        and not previous.get("blocked_reason")
        and not (current.get("encrypted") or {}).get("plan_id")
        and current.get("status") == "todo"
        and current.get("version", 0) > previous.get("version", 0)
        and owner.get("provider") == "codex"
        and owner.get("id") == (previous.get("external_chat") or {}).get("id")
        and current.get("dependencies")
        and all(
            edge.get("target_kind") == "task" and edge.get("target_status") == "done"
            for edge in current["dependencies"]
        )
    )


def repository_checkout(root, location):
    """Recognize app-native linked worktrees through their local Git metadata."""
    checkout = Path(location).resolve()
    if checkout.is_relative_to(root):
        return True
    try:
        pointer = (checkout / ".git").read_text().strip()
        if not pointer.startswith("gitdir: "):
            return False
        gitdir = (checkout / pointer[len("gitdir: "):]).resolve()
        common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
        return common == (root / ".git").resolve()
    except (OSError, ValueError):
        return False


def execution_threads(root, config):
    """Explicit pilots or actual local repository bindings, never cache visibility."""
    host = socket.gethostname()
    allowed = {
        thread
        for thread, owner_host in config.get("execution_hosts", {}).items()
        if owner_host == host and thread in config.get("threads", [])
    }
    path = root / ".claude/sessions.json"
    if config.get("all_threads") and path.exists():
        sessions = json.loads(path.read_text()).get("sessions", {})
        for record in sessions.values():
            thread = record.get("codex_task_id")
            worktree = record.get("worktree") or {}
            location = worktree.get("path")
            if (
                thread
                and record.get("codex_host") == host
                and worktree.get("status") not in {"merged", "removed"}
                and location
                and repository_checkout(root, location)
            ):
                uuid.UUID(thread)
                allowed.add(thread)
    return allowed


def observe_tasks(state, tasks, allowed):
    for key, task in tasks.items():
        previous = state["tasks"].get(key)
        owner = (task.get("external_chat") or {}).get("id")
        if previous and owner in allowed and dependency_ready(previous, task):
            queue(
                state,
                owner,
                "dependency_ready",
                [key, task["version"]],
                {
                    "task_id": task["task_id"],
                    "version": task["version"],
                    "title": task["title"],
                },
            )
        # Store only the metadata needed for routing/replay, never full transcripts.
        state["tasks"][key] = {
            field: task.get(field)
            for field in (
                "task_id",
                "version",
                "status",
                "blocked_reason_code",
                "blocked_reason",
                "external_chat",
                "scope",
            )
        }


def observe_ci(root, config, state, allowed):
    """Consume the current CI owner cache; no GitHub requests or second scheduler."""
    database = root / "logs/ci-coordinator/queue.sqlite3"
    sessions_path = root / ".claude/sessions.json"
    if not database.exists() or not sessions_path.exists():
        return
    sessions = json.loads(sessions_path.read_text()).get("sessions", {})
    owners = {
        sid: record.get("codex_task_id")
        for sid, record in sessions.items()
        if record.get("codex_host") == socket.gethostname()
        and record.get("codex_task_id") in allowed
    }
    if not owners:
        return
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id,owner,source,state,run_id,url,proof_profile,created FROM jobs WHERE owner IN ("
            + ",".join("?" for _ in owners)
            + ") AND state IN ('success','failure','cancelled')",
            list(owners),
        ).fetchall()
    for row in rows:
        job = dict(row)
        if job["id"] in state["ci_seen"] or job["created"] < config.get(
            "activated_at", time.time()
        ):
            continue
        receipt_path = root / "test-results/ci-runs" / job["id"] / "receipt.json"
        evidence = {
            "request_id": job["id"],
            "state": job["state"],
            "source_commit": job["source"],
            "run_id": job["run_id"],
            "url": job["url"],
            "proof_profile": job["proof_profile"],
            "result_command": f"python3 scripts/ci_coordinator.py result {job['id']}",
        }
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            report = receipt.get("report") or {}
            if (
                receipt.get("source_commit") != job["source"]
                or str(receipt.get("run_id")) != str(job["run_id"])
                or report.get("proof_profile", "") != job["proof_profile"]
                or not receipt.get("harness_commit")
                or (
                    report
                    and (
                        report.get("source_commit") != job["source"]
                        or str(report.get("run_id")) != str(job["run_id"])
                        or report.get("harness_commit") != receipt["harness_commit"]
                    )
                )
                or (job["state"] == "success" and not report)
            ):
                evidence["receipt_state"] = (
                    "identity_mismatch; do not use as passing proof"
                )
            else:
                evidence.update(
                    receipt=str(receipt_path),
                    harness_commit=receipt["harness_commit"],
                    receipt_state="available",
                )
        else:
            evidence["receipt_state"] = (
                "retrieve through existing coordinator before treating this as proof"
            )
        queue(state, owners[job["owner"]], "ci_result", job["id"], evidence)
        state["ci_seen"][job["id"]] = job["state"]


def observe_notification(state, message, allowed, parents, tasks):
    params = message.get("params", {})
    owner = params.get("threadId")
    if owner not in allowed:
        return
    runtime = state["threads"].setdefault(owner, {})
    method = message.get("method")
    if method == "thread/status/changed":
        runtime["status"] = params.get("status", {}).get("type", "unknown")
        if runtime["status"] == "active":
            runtime.pop("completed_turn", None)
    elif method == "thread/deleted":
        # Presence in the explicit local registration and a real notification
        # are required. A 404, archive or vanished list entry cannot enter here.
        runtime.update(deleted=True, paused=True)
        for task in state["tasks"].values():
            if (task.get("external_chat") or {}).get("id") != owner:
                continue
            queue(
                state,
                owner,
                "chat_deleted",
                [owner, task["scope"]],
                {"scope": task["scope"]},
            )
    elif method == "turn/completed":
        turn = params.get("turn", {})
        runtime["status"] = "idle" if turn.get("status") == "completed" else "attention"
        runtime["last_turn"] = turn.get("id")
        if turn.get("status") == "interrupted":
            runtime["paused"] = True
        if turn.get("status") == "completed":
            runtime["completed_turn"] = turn.get("id")
        else:
            runtime.pop("completed_turn", None)
        observe_worker_completion(state, parents, tasks, allowed)


def observe_worker_completion(state, parents, tasks, allowed):
    # Task commit delivery and turn completion can arrive in either order.
    for owner, parent in parents.items():
        turn = state["threads"].get(owner, {}).get("completed_turn")
        owned = [
            task
            for task in tasks.values()
            if (task.get("external_chat") or {}).get("id") == owner
        ]
        if (
            turn
            and state["threads"].get(owner, {}).get("status") == "idle"
            and parent in allowed
            and owner in allowed
            and owned
            and all(task["status"] == "done" for task in owned)
        ):
            queue(
                state,
                parent,
                "worker_done",
                [owner, turn, sorted(t["task_id"] for t in owned)],
                {
                    "worker_id": owner,
                    "tasks": [
                        {"task_id": t["task_id"], "title": t["title"]} for t in owned
                    ],
                },
            )


def subscribe_thread(rpc, state, owner):
    # thread/read deliberately does not subscribe. Resume attaches this client
    # without inference or configuration overrides and batches one turn summary.
    result = rpc.call(
        "thread/resume",
        {
            "threadId": owner,
            "excludeTurns": True,
            "initialTurnsPage": {
                "limit": 1,
                "sortDirection": "desc",
                "itemsView": "notLoaded",
            },
        },
    )
    runtime = state["threads"].setdefault(owner, {})
    runtime["status"] = result["thread"].get("status", {}).get("type", "unknown")
    turns = (result.get("initialTurnsPage") or {}).get("data", [])
    if turns:
        turn = turns[0]
        runtime["last_turn"] = turn["id"]
        if turn.get("status") == "interrupted" and (
            turn.get("completedAt") or time.time()
        ) > runtime.get("control_at", 0):
            runtime["paused"] = True
        if turn.get("status") == "completed":
            runtime["completed_turn"] = turn["id"]
    return result["thread"]


def reconcile_uncertain(rpc, item):
    """One bounded page per pass; absence never permits another turn/start."""
    params = {"threadId": item["owner"], "limit": 25, "sortDirection": "desc"}
    if item.get("reconcile_cursor"):
        params["cursor"] = item["reconcile_cursor"]
    page = rpc.call("thread/items/list", params)
    for record in page.get("data", []):
        payload = record.get("item", record)
        found = payload.get("clientId") == item["message_id"]
        if (
            payload.get("type") == "functionCallOutput"
            and payload.get("namespace") == "openmates"
            and payload.get("name") == "task_event"
        ):
            output = payload.get("output")
            try:
                found = (
                    found
                    or isinstance(output, str)
                    and json.loads(output).get("delivery_id") == item["message_id"]
                )
            except ValueError:
                pass
        if found:
            item["state"] = "accepted"
            return
    item["reconcile_cursor"] = page.get("nextCursor")
    item["retry_at"] = time.time() + 60
    if not item["reconcile_cursor"]:
        item["state"] = "needs_review"
        item["error"] = (
            "Start acceptance could not be proved; the original intent is retained and will not be sent twice."
        )


def deliver(state, rpc, allowed, auto_wake, save, tasks):
    attempted = set()
    for item in state["deliveries"].values():
        owner = item["owner"]
        if owner not in allowed or owner in attempted or item["kind"] == "chat_deleted":
            continue
        if item["state"] not in {"pending", "uncertain"} or time.time() < item.get(
            "retry_at", 0
        ):
            continue
        attempted.add(owner)
        if item["state"] == "uncertain":
            reconcile_uncertain(rpc, item)
            save()
            continue
        runtime = state["threads"].get(owner, {})
        if not auto_wake or runtime.get("paused") or runtime.get("deleted"):
            continue
        if item["kind"] == "dependency_ready":
            task = next(
                (
                    t
                    for t in tasks.values()
                    if t["task_id"] == item["data"]["task_id"]
                    and (t.get("external_chat") or {}).get("id") == owner
                ),
                None,
            )
            if not task:
                continue  # Revoked/disconnected/unselected scope cannot authorize a wake.
            if (
                task["status"] != "todo"
                or task["version"] < item["data"]["version"]
                or not task.get("dependencies")
                or not all(
                    edge.get("target_kind") == "task"
                    and edge.get("target_status") == "done"
                    for edge in task["dependencies"]
                )
            ):
                item["state"] = "superseded"
                save()
                continue
        thread = rpc.call("thread/read", {"threadId": owner, "includeTurns": False})[
            "thread"
        ]
        status = thread.get("status", {}).get("type")
        state["threads"].setdefault(owner, {})["status"] = status
        if status == "active":
            # The running worker receives this event at its next context boundary.
            continue
        if status == "notLoaded":
            thread = subscribe_thread(rpc, state, owner)
            status = thread.get("status", {}).get("type")
            if state["threads"][owner].get("paused"):
                save()
                continue
        if status != "idle" or thread.get("archived"):
            continue
        item["state"] = "uncertain"
        save()  # A crash after this point can never cause a blind duplicate start.
        try:
            result = rpc.call(
                "turn/start",
                {
                    "threadId": owner,
                    "clientUserMessageId": item["message_id"],
                    "turnTrigger": "openmates_tasks",
                    "input": [],
                    "toolOutput": {
                        "name": "task_event",
                        "namespace": "openmates",
                        "output": json.dumps(
                            {
                                "delivery_id": item["message_id"],
                                "event": item["kind"],
                                "data": item["data"],
                                "notice": "Automated Task event, not a human instruction or approval. Continue only the existing authorized work. CI results require source/harness/profile proof; passing CI does not complete a Task.",
                            }
                        ),
                    },
                },
            )
        except CodexRPCRejected:
            item.update(
                state="needs_review",
                error="Codex rejected the continuation; review the retained event before retrying.",
            )
            save()
            raise
        item.update(state="accepted", turn_id=result["turn"]["id"])
        save()


def registry(root, session):
    path = root / "logs/codex-orchestration" / session / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def run(root, config):
    path = adapter_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(path.read_text()) if path.exists() else empty_state()

        def save():
            _save(path, state)

        rpc = None
        retry_at = 0
        failures = 0
        first_failure = None
        tasks = {}
        subscribed = set()
        while True:
            # EOF binds child lifetime to remote-access, including parent crashes.
            readable = select.select(
                [sys.stdin, *([rpc.socket] if rpc else [])], [], [], 5
            )[0]
            if sys.stdin in readable and not sys.stdin.readline():
                if rpc:
                    rpc.close()
                return
            try:
                current_config = json.loads(
                    (state_root() / "codex-adapter.json").read_text()
                )["repositories"].get(str(root))
                if not current_config or not current_config.get("enabled"):
                    return
                config = current_config
                allowed = execution_threads(root, config)
                parents = {}
                for session in config.get("sessions", []):
                    registered = registry(root, session)
                    for owner, worker in registered.get("workers", {}).items():
                        parents[owner] = registered.get("coordinator")
                        if worker.get("stopped"):
                            state["threads"].setdefault(owner, {})["paused"] = True
                controls = state_root() / "codex-adapter-controls" / identity(str(root))
                for owner in allowed:
                    control_path = controls / f"{owner}.json"
                    if control_path.exists():
                        control = json.loads(control_path.read_text())
                        runtime = state["threads"].setdefault(owner, {})
                        if control["updated_at"] > runtime.get("control_at", 0):
                            runtime.update(
                                paused=control["paused"],
                                control_at=control["updated_at"],
                            )
                    receipt_path = (
                        state_root() / "codex-context-receipts" / f"{owner}.json"
                    )
                    if receipt_path.exists():
                        receipt = json.loads(receipt_path.read_text())
                        for delivered_id in receipt.get("adapter_events", []):
                            item = state["deliveries"].get(delivered_id)
                            if (
                                item
                                and item["state"] == "pending"
                                and item["owner"] == owner
                            ):
                                item["state"] = "provided_in_context"
                tasks = load_tasks(config)
                observe_tasks(state, tasks, allowed)
                observe_worker_completion(state, parents, tasks, allowed)
                # Local CI reads are bounded to one pass every five seconds.
                if time.time() >= state.get("next_ci_read", 0):
                    observe_ci(root, config, state, allowed)
                    state["next_ci_read"] = time.time() + 5
                save()
                if time.time() < retry_at:
                    continue
                if rpc is None:
                    rpc = CodexRPC()
                    subscribed = set()
                for owner in sorted(allowed - subscribed):
                    # Subscribe once per connection, without inference or full-history output.
                    if state["threads"].get(owner, {}).get("deleted"):
                        subscribed.add(owner)
                        continue
                    try:
                        meta = subscribe_thread(rpc, state, owner)
                    except CodexRPCRejected:
                        state["threads"].setdefault(owner, {})["status"] = "unavailable"
                        subscribed.add(owner)
                        continue
                    state["threads"].setdefault(owner, {})["status"] = meta.get(
                        "status", {}
                    ).get("type", "unknown")
                    subscribed.add(owner)
                for notification in rpc.poll_notifications(0):
                    observe_notification(state, notification, allowed, parents, tasks)
                for item in state["deliveries"].values():
                    if item["kind"] != "chat_deleted":
                        continue
                    scope = item["data"]["scope"]
                    directory = (
                        state_root()
                        / "codex-chat-deletions"
                        / hashlib.sha256(
                            json.dumps(scope, separators=(",", ":")).encode()
                        ).hexdigest()
                    )
                    delivery_path = directory / f"{item['id']}.json"
                    if not delivery_path.exists():
                        _save(
                            delivery_path,
                            {
                                "schema_version": 1,
                                "event_id": item["id"],
                                "scope": scope,
                                "thread": item["owner"],
                                "evidence": "thread/deleted",
                                "state": "pending",
                            },
                        )
                    item["state"] = json.loads(delivery_path.read_text())["state"]
                save()
                deliver(
                    state, rpc, allowed, config.get("auto_wake") is True, save, tasks
                )
                state["connection"] = {"state": "connected"}
                failures = 0
                first_failure = None
                save()
            except (OSError, RuntimeError, ValueError, KeyError):
                if rpc:
                    rpc.close()
                    rpc = None
                failures += 1
                first_failure = first_failure or time.time()
                retry_at = time.time() + min(120, 5 * 2 ** min(failures - 1, 5))
                state["connection"] = {
                    "state": "retrying",
                    "failures": failures,
                    "retry_at": retry_at,
                }
                if failures >= 5 and time.time() - first_failure >= 300:
                    state["connection"]["notice"] = (
                        "Codex event delivery remains unavailable; pending events are retained."
                    )
                save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["serve", "status", "pause", "resume"])
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--thread")
    args = parser.parse_args()
    root = args.repository.resolve()
    config = (
        json.loads((state_root() / "codex-adapter.json").read_text())
        .get("repositories", {})
        .get(str(root))
    )
    if not config or not config.get("enabled"):
        parser.error("Repository is not explicitly configured for the Task adapter")
    path = adapter_path(root)
    if args.action == "serve":
        run(root, config)
    elif args.action == "status":
        state = json.loads(path.read_text()) if path.exists() else empty_state()
        print(
            json.dumps(
                {
                    "threads": state["threads"],
                    "connection": state.get("connection"),
                    "deliveries": [
                        {k: v for k, v in item.items() if k != "data"}
                        for item in state["deliveries"].values()
                        if item["state"]
                        not in {"accepted", "superseded", "provided_in_context"}
                    ],
                }
            )
        )
    else:
        if args.thread not in execution_threads(root, config):
            parser.error("Select a locally registered chat")
        # Control intent is separate so the foreground owner's state write cannot
        # race a user pause. The loop applies these controls before delivery.
        controls = state_root() / "codex-adapter-controls" / identity(str(root))
        controls.mkdir(parents=True, exist_ok=True, mode=0o700)
        _save(
            controls / f"{args.thread}.json",
            {"paused": args.action == "pause", "updated_at": time.time()},
        )
        print(json.dumps({"thread": args.thread, "paused": args.action == "pause"}))


if __name__ == "__main__":
    main()
