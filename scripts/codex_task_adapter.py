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
    from scripts import codex_chat_presence as presence
    from scripts.codex_rpc import CodexRPC, CodexRPCRejected
except ModuleNotFoundError:
    from codex_cached_context import _save, state_root
    import codex_chat_presence as presence
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
            tasks[key] = {**task, "scope": snapshot["account_scope"], "snapshot_path": name}
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
    return presence.repository_checkout(root, location)


def execution_threads(root, config, disk_requests=()):
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
        for session_id, record in sessions.items():
            thread = record.get("codex_task_id")
            worktree = record.get("worktree") or {}
            location = worktree.get("path")
            provisioning_wait = (
                record.get("repo_root") == str(root.resolve())
                and worktree.get("status") in {None, "pending", "provisioning", "waiting"}
                and any(
                    row.get("thread") == thread
                    and row.get("repository") == str(root.resolve())
                    and row.get("operation") == f"workspace:{session_id}"
                    and row.get("state") in {"waiting", "granted"}
                    for row in disk_requests
                )
            )
            if (
                thread
                and record.get("codex_host") == host
                and worktree.get("status") not in {"merged", "removed"}
                and ((location and repository_checkout(root, location)) or provisioning_wait)
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


def disk_owner_task(row, tasks, allowed):
    """Only a unique, locally registered Task owner can receive a grant."""
    if not row.get("thread"):
        return None  # Anonymous maintenance callers never authorize a model wake.
    candidates = [
        task for task in tasks.values()
        if (task.get("external_chat") or {}).get("provider") == "codex"
        and (task.get("external_chat") or {}).get("id") in allowed
        and (not row.get("thread") or (task.get("external_chat") or {}).get("id") == row["thread"])
        and (not row.get("task_id") or task.get("task_id") == row["task_id"])
        and task.get("status") != "done"
    ]
    return candidates[0] if len(candidates) == 1 else None


def disk_task_eligible(task):
    return task and task.get("status") in {"todo", "in_progress", "active"} and not any(
        task.get(flag) for flag in ("paused", "deleted", "archived")
    )


def disk_blocked_task(task):
    """A disk-specific environment blocker permits a notice, never its removal."""
    import re
    return bool(task and task.get("status") == "blocked"
                and task.get("blocked_reason_code") == "environment_unavailable"
                and re.search(r"\b(disk|filesystem|file system|storage|free space|no space)\b",
                              task.get("blocked_reason") or "", re.IGNORECASE))


def refresh_disk_wait_receipts(state):
    """Read delivery truth independently of resource state and Task versions."""
    for request_id, record in state.get("disk_task_waits", {}).items():
        for phase in ("block", "activity", "restore"):
            delivery_id = record.get(phase + "_delivery")
            if not delivery_id:
                continue
            paths = list((state_root() / "task-command-delivery").glob(f"*/{delivery_id}.json"))
            if len(paths) != 1:
                continue
            receipt = json.loads(paths[0].read_text())
            if (receipt.get("id") == delivery_id and receipt.get("thread") == record["owner"]
                    and receipt.get("task_id") == record["task_id"]):
                record[phase + "_state"] = receipt.get("state", "pending")


def prior_disk_status_owner(state, task, owner):
    """A replacement request may reuse only an exact, acknowledged status fence."""
    candidates = []
    for request_id, wait in state.get("disk_task_waits", {}).items():
        if (wait.get("owner") != owner or wait.get("task_id") != task["task_id"]
                or wait.get("state") == "needs_review" or task.get("blocked_reason")
                or task.get("blocked_reason_code")):
            continue
        if (task.get("status") == "blocked" and wait.get("block_state") == "acknowledged"
                and task.get("version") == wait["original_version"] + 1):
            candidates.append(request_id)
    return candidates[0] if len(candidates) == 1 else None


def sync_disk_task(state, row, task, save):
    """Version-fenced status edits; any competing Task edit requires review."""
    try:
        from scripts.codex_task_queue import enqueue
    except ModuleNotFoundError:
        from codex_task_queue import enqueue
    waits = state.setdefault("disk_task_waits", {})
    record = waits.get(row["id"])
    owner = (task.get("external_chat") or {}).get("id")
    clean = not task.get("blocked_reason") and not task.get("blocked_reason_code")
    if record is None:
        if row["state"] != "waiting":
            return True  # No Task mutation was needed for an immediately admitted job.
        if task.get("status") not in {"todo", "in_progress"} or not clean or not task.get("snapshot_path"):
            return False
        record = waits[row["id"]] = {
            "task_id": task["task_id"], "owner": owner, "original_status": task["status"],
            "original_version": task["version"], "state": "blocking",
        }
        save()  # Preserve original ownership/version before publishing any mutation.
    refresh_disk_wait_receipts({"disk_task_waits": {row["id"]: record}})
    version = record["original_version"]
    if task["task_id"] != record["task_id"] or owner != record["owner"] or not clean:
        record["state"] = "needs_review"
        return False
    if record["state"] == "needs_review":
        return False
    current = (task.get("status"), task.get("version"))
    original = (record["original_status"], version)
    blocked = ("blocked", version + 1)
    restored = (record["original_status"], version + 2)
    if current == restored and record["state"] == "restoring":
        # The queue's receipt is authoritative; a coincidentally matching human
        # status change cannot be mistaken for our acknowledged restoration.
        restore_id = record.get("restore_delivery") or identity([owner, f"disk-{identity(row['id'])[:32]}-restore"])
        receipts = list((state_root() / "task-command-delivery").glob(f"*/{restore_id}.json")) if restore_id else []
        if len(receipts) != 1 or json.loads(receipts[0].read_text()).get("state") != "acknowledged":
            return False
        record["state"] = "restored"
        return True
    if record["state"] == "restored":
        return current == restored
    if current not in {original, blocked}:
        record["state"] = "needs_review"
        return False

    def publish(phase, operation):
        # Freeze the exact authenticated snapshot used for this intent: enqueue
        # must never pick up a newer version between validation and its read.
        key = f"disk-{identity(row['id'])[:32]}-{phase}"
        frozen = state_root() / "disk-task-snapshots" / f"{key}.json"
        if not frozen.exists():
            expected_version = version + 1 if phase == "restore" else version
            if task.get("version") != expected_version:
                return False
            source = json.loads(Path(task["snapshot_path"]).read_text())
            selected = [t for t in source.get("tasks", []) if t.get("task_id") == task["task_id"]]
            if len(selected) != 1 or selected[0].get("version") != task["version"] or selected[0].get("external_chat") != task.get("external_chat"):
                return False
            _save(frozen, source)
        result = enqueue(frozen, operation, key, owner, state_root())
        record[phase + "_delivery"] = result["delivery"]["id"]
        record[phase + "_state"] = result["delivery"]["state"]
        return result["delivery"]["state"] == "acknowledged"

    if current == original and record["state"] == "blocking":
        publish("block", {"kind": "edit", "task_id": task["task_id"], "status": "blocked"})
        publish("activity", {"kind": "activity", "task_id": task["task_id"], "message": "Waiting for host disk capacity; existing work will resume after a reserved grant."})
    elif current == blocked and row["state"] == "granted":
        block_ok = publish("block", {"kind": "edit", "task_id": task["task_id"], "status": "blocked"})
        activity_ok = publish("activity", {"kind": "activity", "task_id": task["task_id"], "message": "Waiting for host disk capacity; existing work will resume after a reserved grant."})
        if not block_ok or not activity_ok:
            return False
        record["state"] = "restoring"
        save()
        publish("restore", {"kind": "edit", "task_id": task["task_id"], "status": record["original_status"]})
    return False


def observe_disk(root, state, tasks, allowed, coordinator, save=lambda: None, requests=None):
    """One ledger snapshot per loop; one Task-status fence per resource group."""
    rows = coordinator.requests(str(root)) if requests is None else requests
    refresh_disk_wait_receipts(state)
    state["disk_requests"] = rows
    current = {(row["id"], row.get("grant_id")) for row in rows if row["state"] == "granted"}
    for item in state["deliveries"].values():
        if item["kind"] == "disk_ready" and (item["data"]["id"], item["data"].get("grant_id")) not in current:
            if item["state"] == "pending":
                item["state"] = "superseded"
    for runtime in state["threads"].values():
        runtime["resource_waiting"] = False
    groups = {}
    for row in rows:
        if row["state"] not in {"waiting", "granted"}:
            continue
        if row.get("thread") and row.get("task_id"):
            exact = [task for task in tasks.values() if task.get("task_id") == row["task_id"]]
            if len(exact) == 1:
                linked = exact[0].get("external_chat") or {}
                if exact[0].get("status") == "done" or linked.get("provider") != "codex" or linked.get("id") != row["thread"]:
                    coordinator.cancel(row["id"], "The bound Task completed or changed its conversation owner")
                    row["state"] = "cancelled"
                    for item in state["deliveries"].values():
                        if item["kind"] == "disk_ready" and item["data"]["id"] == row["id"] and item["state"] == "pending":
                            item["state"] = "superseded"
                    continue
        task = disk_owner_task(row, tasks, allowed)
        owner = (task.get("external_chat") or {}).get("id") if task else row.get("thread")
        if owner:
            state["threads"].setdefault(owner, {})["resource_waiting"] = True
        if not task:
            continue
        if not row.get("task_id") and hasattr(coordinator, "bind_task"):
            if not coordinator.bind_task(row["id"], owner, task["task_id"]):
                continue  # A concurrent owner/state change cannot authorize routing.
            row["task_id"] = task["task_id"]
        row["resolved_task_id"] = task["task_id"]
        key = identity([owner, task["task_id"], task.get("scope")])
        groups.setdefault(key, {"owner": owner, "task": task, "rows": []})["rows"].append(row)
    for key, group in groups.items():
        owner, task, members = group["owner"], group["task"], group["rows"]
        runtime = state["threads"][owner]
        if any(runtime.get(flag) for flag in ("paused", "deleted", "archived")):
            for row in members:
                if row["state"] == "granted":
                    coordinator.defer(row["id"])
                for item in state["deliveries"].values():
                    if item["kind"] == "disk_ready" and item["data"]["id"] == row["id"] and item["state"] == "pending":
                        item["state"] = "superseded"
            continue
        active_ids = {row["id"] for row in members}
        saved = state.setdefault("disk_task_groups", {}).get(key)
        if not saved or not active_ids.intersection(saved["members"]):
            status_owner = prior_disk_status_owner(state, task, owner)
            saved = state["disk_task_groups"][key] = {"id": status_owner or members[0]["id"], "members": []}
        saved["members"] = sorted(active_ids)
        group_id = saved["id"]
        for row in members:
            row["task_wait_id"] = group_id
        grants = [row for row in members if row["state"] == "granted" and coordinator.valid_grant(row["id"], row.get("grant_id"))]
        representative = {**members[0], "id": group_id, "state": "granted" if grants else "waiting"}
        if disk_blocked_task(task):
            for row in grants[:1]:
                queue(state, owner, "disk_ready", [row["id"], row["grant_id"], "notify_only"], {
                    **row, "task_id": task["task_id"], "task_status_policy": "notify_only",
                    "notice": "Disk capacity is reserved. Your Task status and blocker were preserved. Continue only existing authorized disk-dependent work; reconcile your own disk blocker when appropriate. The next gated operation must claim this grant.",
                })
            continue
        if not grants and group_id not in state.get("disk_task_waits", {}):
            active_owned = [t for t in tasks.values() if (t.get("external_chat") or {}).get("id") == owner and t.get("status") in {"todo", "in_progress", "blocked"}]
            if len(active_owned) != 1:
                continue
        synchronized = sync_disk_task(state, representative, task, save)
        if not grants or not synchronized:
            continue
        if not disk_task_eligible(task):
            for row in members:
                coordinator.defer(row["id"])
            continue
        # Deliver the oldest live grant only. Later requests can proceed after
        # this operation claims/completes; requiring all grants can deadlock.
        for row in grants[:1]:
            queue(state, owner, "disk_ready", [row["id"], row["grant_id"]], {**row, "task_id": task["task_id"], "task_wait_id": group_id})


def disk_delivery_valid(item, state, tasks, allowed, coordinator):
    task = disk_owner_task(item["data"], tasks, allowed)
    runtime = state["threads"].get(item["owner"], {})
    wait = state.get("disk_task_waits", {}).get(item["data"].get("task_wait_id", item["data"]["id"]))
    restored = not wait or (wait.get("state") == "restored" and task and task.get("version") == wait["original_version"] + 2 and task.get("status") == wait["original_status"])
    notify_only = item["data"].get("task_status_policy") == "notify_only" and disk_blocked_task(task)
    status_eligible = notify_only or (restored and disk_task_eligible(task)
                                     and not task.get("blocked_reason") and not task.get("blocked_reason_code"))
    return bool(
        status_eligible and coordinator and coordinator.available()
        and not any(task.get(flag) for flag in ("paused", "deleted", "archived"))
        and not any(runtime.get(flag) for flag in ("paused", "deleted", "archived"))
        and coordinator.valid_grant(item["data"]["id"], item["data"].get("grant_id"))
    )


def disk_start_unresolved(state, item):
    return any(
        previous["id"] != item["id"] and previous["owner"] == item["owner"]
        and previous["kind"] == "disk_ready"
        and previous["data"]["id"] == item["data"]["id"]
        and previous["created_at"] < item["created_at"]
        and previous["state"] in {"uncertain", "needs_review"}
        for previous in state["deliveries"].values()
    )


def acknowledge_context(state, receipt, owner, coordinator, tasks, allowed):
    for delivered_id in receipt.get("adapter_events", []):
        item = state["deliveries"].get(delivered_id)
        if not item or item["state"] != "pending" or item["owner"] != owner:
            continue
        if item["kind"] == "disk_ready":
            if disk_start_unresolved(state, item) or not disk_delivery_valid(item, state, tasks, allowed, coordinator):
                continue
            coordinator.acknowledge(item["data"]["id"], item["data"]["grant_id"])
        item["state"] = "provided_in_context"


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
    runtime["archived"] = bool(result["thread"].get("archived"))
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


def deliver(state, rpc, allowed, auto_wake, save, tasks, coordinator=None, revalidate=None,
            execution_not_before=0):
    attempted = set()
    for item in state["deliveries"].values():
        owner = item["owner"]
        if owner not in allowed or owner in attempted or item["kind"] == "chat_deleted":
            continue
        if item["kind"] == "disk_ready" and disk_start_unresolved(state, item):
            continue  # An expired reservation never resolves uncertain start acceptance.
        if item["state"] not in {"pending", "uncertain"} or time.time() < item.get(
            "retry_at", 0
        ):
            continue
        # An explicit rollout boundary retains historical notifications for
        # context without launching old work when a long-disconnected adapter
        # reconnects. Uncertain starts still require their original reconciliation.
        if item["state"] == "pending" and item["created_at"] < execution_not_before:
            continue
        attempted.add(owner)
        if item["state"] == "uncertain":
            reconcile_uncertain(rpc, item)
            if item["kind"] == "disk_ready" and item["state"] == "accepted" and coordinator:
                coordinator.acknowledge(item["data"]["id"], item["data"]["grant_id"])
            save()
            continue
        runtime = state["threads"].get(owner, {})
        if not auto_wake or runtime.get("paused") or runtime.get("deleted") or runtime.get("archived"):
            continue
        if runtime.get("resource_waiting") and item["kind"] != "disk_ready":
            continue
        if item["kind"] == "disk_ready" and not disk_delivery_valid(item, state, tasks, allowed, coordinator):
            item["state"] = "superseded"
            save()
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
        if thread.get("archived"):
            state["threads"][owner]["archived"] = True
            if item["kind"] == "disk_ready":
                coordinator.defer(item["data"]["id"])
            continue
        if status != "idle":
            continue
        if item["kind"] == "disk_ready":
            if revalidate:
                allowed, tasks = revalidate()
            if not disk_delivery_valid(item, state, tasks, allowed, coordinator):
                item["state"] = "superseded"
                save()
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
        if item["kind"] == "disk_ready":
            coordinator.acknowledge(item["data"]["id"], item["data"]["grant_id"])
        save()


def registry(root, session):
    path = root / "logs/codex-orchestration" / session / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def stop_adapter(state, save, rpc=None):
    """Persist a truthful stopped state without altering pending deliveries."""
    state["presence"] = presence.unavailable(state.get("presence"), "Adapter stopped")
    state["connection"] = {"state": "stopped"}
    save()
    if rpc:
        rpc.close()


def refresh_presence(rpc, root, config, state):
    """Keep advisory inventory faults outside the Task delivery state machine."""
    try:
        state["presence"] = presence.collect_once(rpc, root, config, state.get("presence"))
    except Exception:
        state["presence"] = presence.unavailable(
            state.get("presence"), "Presence refresh unavailable"
        )
    if state["presence"].get("reason", "").startswith(
        "Codex inventory deadline exceeded"
    ):
        # A timed-out read can leave a partial WebSocket frame. Reconnect before
        # any Task event call uses this stream.
        rpc.close()
        return CodexRPC(), True
    return rpc, False


def disk_ledger(root):
    try:
        from scripts.disk_coordinator import Coordinator, configured
    except ModuleNotFoundError:
        from disk_coordinator import Coordinator, configured
    return configured(root) or Coordinator()


def refresh_disk_authorization(root, state):
    """Reload opt-in, local routing, Task scope and human controls at start."""
    config = json.loads((state_root() / "codex-adapter.json").read_text()).get(
        "repositories", {}
    ).get(str(root))
    if not config or not config.get("enabled") or config.get("auto_wake") is not True:
        return set(), {}
    allowed = execution_threads(root, config, state.get("disk_requests", []))
    controls = state_root() / "codex-adapter-controls" / identity(str(root))
    for owner in allowed:
        control_path = controls / f"{owner}.json"
        if control_path.exists():
            control = json.loads(control_path.read_text())
            runtime = state["threads"].setdefault(owner, {})
            if control["updated_at"] > runtime.get("control_at", 0):
                runtime.update(paused=control["paused"], control_at=control["updated_at"])
    return allowed, load_tasks(config)


def run(root, config):
    path = adapter_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(path.read_text()) if path.exists() else empty_state()

        def save():
            _save(path, state)

        coordinator = disk_ledger(root)
        rpc = None
        retry_at = 0
        failures = 0
        first_failure = None
        tasks = {}
        subscribed = set()
        next_presence_read = 0
        while True:
            # EOF binds child lifetime to remote-access, including parent crashes.
            readable = select.select(
                [sys.stdin, *([rpc.socket] if rpc else [])], [], [], 5
            )[0]
            if sys.stdin in readable and not sys.stdin.readline():
                stop_adapter(state, save, rpc)
                return
            try:
                current_config = json.loads(
                    (state_root() / "codex-adapter.json").read_text()
                )["repositories"].get(str(root))
                if not current_config or not current_config.get("enabled"):
                    stop_adapter(state, save, rpc)
                    return
                config = current_config
                disk_rows = coordinator.requests(str(root)) if coordinator.available() else []
                allowed = execution_threads(root, config, disk_rows)
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
                tasks = load_tasks(config)
                observe_tasks(state, tasks, allowed)
                if coordinator.available():
                    observe_disk(root, state, tasks, allowed, coordinator, save, requests=disk_rows)
                else:
                    state["disk_service"] = "unavailable"
                for owner in allowed:
                    receipt_path = state_root() / "codex-context-receipts" / f"{owner}.json"
                    if receipt_path.exists():
                        acknowledge_context(state, json.loads(receipt_path.read_text()), owner, coordinator, tasks, allowed)
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
                    next_presence_read = 0
                presence_enabled = config.get("presence_enabled") is not False
                if not presence_enabled:
                    next_presence_read = 0
                if presence_enabled and time.time() >= next_presence_read:
                    rpc, reset = refresh_presence(rpc, root, config, state)
                    if reset:
                        subscribed = set()
                    next_presence_read = time.time() + 30
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
                    if presence_enabled:
                        presence.observe_notification(state.get("presence", {}), notification)
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
                    state, rpc, allowed, config.get("auto_wake") is True, save, tasks,
                    coordinator, lambda: refresh_disk_authorization(root, state),
                    execution_not_before=float(config.get("execution_not_before", 0)),
                )
                state["connection"] = {"state": "connected"}
                failures = 0
                first_failure = None
                save()
            except (OSError, RuntimeError, ValueError, KeyError):
                if rpc:
                    rpc.close()
                    rpc = None
                state["presence"] = presence.unavailable(state.get("presence"))
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
                    "presence": state.get("presence"),
                    "disk_requests": state.get("disk_requests", []),
                    "disk_task_waits": state.get("disk_task_waits", {}),
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
        state = json.loads(path.read_text()) if path.exists() else empty_state()
        if args.thread not in execution_threads(root, config, state.get("disk_requests", [])):
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
