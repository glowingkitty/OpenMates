"""Write a durable Codex Task command without invoking the OpenMates CLI.

The selected private snapshot binds the account and Project. The actual running
chat ID binds the caller; ownership and version are preserved for later delivery.
The foreground remote-access process encrypts and sends this local intent.
Queued is never reported as a confirmed claim, edit, activity or completion.
No credentials, network requests, shell commands or model calls are used here.
"""

from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid


def enqueue(
    snapshot_path: Path, operation: dict, key: str, thread: str, root: Path
) -> dict:
    uuid.UUID(thread)
    if not key or len(key) > 200:
        raise ValueError(
            "Use a stable, short operation ID, such as header-investigation-finished"
        )
    snapshot = json.loads(snapshot_path.read_text())
    scope = snapshot.get("account_scope")
    if (
        not isinstance(scope, list)
        or len(scope) != 3
        or not all(isinstance(part, str) and part for part in scope)
    ):
        raise ValueError(
            "This cache lacks an authenticated account scope; refresh remote-access first"
        )
    if snapshot.get("connection") == "revoked":
        raise ValueError("Project access was revoked; no command was queued")
    allowed = {
        "kind",
        "task_id",
        "title",
        "description",
        "status",
        "message",
        "link_to_chat",
    }
    if not isinstance(operation, dict) or set(operation) - allowed:
        raise ValueError("Unsupported Task command field")
    kind = operation.get("kind")
    if kind not in {"create", "edit", "activity", "complete"}:
        raise ValueError("Supported commands: create, edit, activity, complete")
    task = None
    if kind == "create":
        if (
            not isinstance(operation.get("title"), str)
            or not operation["title"].strip()
        ):
            raise ValueError("Task creation requires a title")
        if "link_to_chat" in operation and not isinstance(
            operation["link_to_chat"], bool
        ):
            raise ValueError("link_to_chat must be a boolean")
    else:
        task = next(
            (
                item
                for item in snapshot["tasks"]
                if item["task_id"] == operation.get("task_id")
            ),
            None,
        )
        if not task:
            raise ValueError("Task is not in this snapshot; refresh its Project first")
        owner = task.get("external_chat") or {}
        if owner.get("provider") != "codex" or owner.get("id") != thread:
            raise ValueError(
                f"Task is linked to {json.dumps(owner.get('title') or 'another chat')}; Codex chat ID: {owner.get('id') or 'unavailable'}. Only its owner can enqueue work."
            )
    for field in ("title", "description", "message"):
        if field in operation and (
            not isinstance(operation[field], str) or len(operation[field]) > 100_000
        ):
            raise ValueError(f"{field} must be bounded text")
    if kind == "activity" and not isinstance(operation.get("message"), str):
        raise ValueError("Task activity requires a message")
    if kind in {"create", "complete"} and scope[2] != "personal":
        raise ValueError(
            "This command is not supported in Team scope by the current Task API"
        )
    if "status" in operation and operation["status"] not in {
        "backlog",
        "todo",
        "in_progress",
        "blocked",
        "done",
    }:
        raise ValueError("Unsupported Task status")
    identity = hashlib.sha256(
        json.dumps([thread, key], separators=(",", ":")).encode()
    ).hexdigest()
    account = hashlib.sha256(
        json.dumps(scope, separators=(",", ":")).encode()
    ).hexdigest()
    directory = root / "task-command-delivery" / account
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / ".enqueue.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / f"{identity}.json"
        if path.exists():
            saved = json.loads(path.read_text())
            if saved["operation"] != operation:
                raise ValueError(
                    "This operation ID already refers to different work; use a new ID"
                )
        else:
            saved = {
                "schema_version": 1,
                "id": identity,
                "scope": scope,
                "thread": thread,
                "project_id": snapshot["project_id"],
                "operation": operation,
                "task_id": task["task_id"] if task else str(uuid.uuid4()),
                "task": task,
                "created_at": time.time(),
                "state": "pending",
            }
            fd, temporary = tempfile.mkstemp(prefix=".intent-", dir=directory)
            try:
                with os.fdopen(fd, "w") as output:
                    json.dump(saved, output)
                    output.flush()
                    os.fsync(output.fileno())
                Path(temporary).replace(path)
            finally:
                Path(temporary).unlink(missing_ok=True)
    return {
        "delivery": {
            "id": identity,
            "state": saved["state"],
            "task_id": saved["task_id"],
        }
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--id")
    parser.add_argument("--status", action="store_true")
    parser.add_argument(
        "--operation", help="JSON object using the existing Task fields"
    )
    args = parser.parse_args()
    thread = os.environ.get("CODEX_THREAD_ID")
    if not thread:
        parser.error(
            "Run this inside the owning Codex chat; CODEX_THREAD_ID is required"
        )
    root = Path(os.environ.get("OPENMATES_STATE_DIR") or Path.home() / ".openmates")
    if args.status:
        snapshot = json.loads(args.snapshot.read_text())
        scope = snapshot["account_scope"]
        account = hashlib.sha256(
            json.dumps(scope, separators=(",", ":")).encode()
        ).hexdigest()
        entries = []
        for path in sorted((root / "task-command-delivery" / account).glob("*.json")):
            record = json.loads(path.read_text())
            if record.get("thread") == thread:
                entries.append(
                    {
                        key: record.get(key)
                        for key in ("id", "task_id", "state", "error")
                    }
                )
        print(json.dumps({"deliveries": entries}))
        return
    if not args.id or not args.operation:
        parser.error(
            "Enqueue requires --id and --operation; use --status to inspect existing delivery"
        )
    print(
        json.dumps(
            enqueue(args.snapshot, json.loads(args.operation), args.id, thread, root)
        )
    )


if __name__ == "__main__":
    main()
