#!/usr/bin/env python3
"""CI-only disk metadata probe through the real encrypted Task command outbox.

The authenticated foreground CLI delivers these intents. This helper never calls
an API, creates capacity pressure, starts inference, or controls a live adapter.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import codex_task_adapter as adapter
from scripts.codex_cached_context import _save, state_root


def commands():
    return {
        str(path): json.loads(path.read_text())
        for path in (state_root() / "task-command-delivery").glob("*/*.json")
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("block", "restore", "confirm", "human-blocker"))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get("CI") == "true", "Only the isolated CI harness may run this probe"
    assert os.environ.get("OPENMATES_API_URL") == "http://localhost:8000"
    assert os.environ.get("OPENMATES_STATE_DIR"), "Use the paired runner's private CLI state"
    snapshot = json.loads(args.snapshot.read_text())
    assert snapshot["connection"] == "connected"
    refreshed = datetime.fromisoformat(snapshot["synced_at"].replace("Z", "+00:00"))
    assert (datetime.now(timezone.utc) - refreshed).total_seconds() < 120
    matches = [task for task in snapshot["tasks"] if task["task_id"] == args.task]
    assert len(matches) == 1
    task = {**matches[0], "snapshot_path": str(args.snapshot)}
    owner = task.get("external_chat") or {}
    assert owner.get("provider") == "codex" and owner.get("id")
    uuid.UUID(owner["id"])
    before = commands()
    if args.phase == "block":
        assert not args.fixture.exists()
        assert task["status"] == "in_progress"
        assert not task.get("blocked_reason") and not task.get("blocked_reason_code")
        fixture = {"state": adapter.empty_state(), "original_version": task["version"],
                   "original_status": task["status"], "owner": owner["id"],
                   "row": {"id": str(uuid.uuid4()), "state": "waiting", "thread": owner["id"],
                           "task_id": task["task_id"], "operation": "isolated-task-disk-proof",
                           "grant_id": "", "expires_at": 0, "amount": 1024}}
    else:
        fixture = json.loads(args.fixture.read_text())
        assert fixture["owner"] == owner["id"]
    state, row = fixture["state"], fixture["row"]
    def save():
        _save(args.fixture, fixture)
    if args.phase == "human-blocker":
        assert task["status"] == "blocked" and task.get("blocked_reason_code") == "needs_user_input"
        assert task.get("blocked_reason") == "Human approval remains required during disk recovery."
        isolated = adapter.empty_state()
        assert not adapter.sync_disk_task(isolated, {"id": str(uuid.uuid4()), "state": "waiting"}, task, lambda: None)
        assert not isolated.get("disk_task_waits")
        # A stale ready continuation from the completed disk cycle must also
        # preserve the newer human blocker, not merely reject a new disk wait.
        assert not adapter.sync_disk_task(state, row, task, save)
        assert state["disk_task_waits"][row["id"]]["state"] == "needs_review"
        save()
        assert commands() == before, "A human blocker must not create any disk status/activity intent"
    else:
        if args.phase == "restore":
            assert task["status"] == "blocked" and task["version"] == fixture["original_version"] + 1
            assert not task.get("blocked_reason") and not task.get("blocked_reason_code")
            # Only capacity metadata is synthetic; the Task cache and outbox are real.
            row.update(state="granted", grant_id=uuid.uuid4().hex, expires_at=time.time() + 300)
        ready = adapter.sync_disk_task(state, row, task, save)
        if args.phase == "confirm":
            assert ready
            assert task["status"] == fixture["original_status"]
            assert task["version"] == fixture["original_version"] + 2
        else:
            assert not ready
        save()
    after = commands()
    wait = state.get("disk_task_waits", {}).get(row["id"], {})
    receipt_ids = [wait[name] for name in ("block_delivery", "activity_delivery", "restore_delivery") if name in wait]
    relevant = [record for record in after.values() if record["id"] in receipt_ids]
    expected_count = 2 if args.phase == "block" else 3
    if args.phase != "human-blocker":
        assert len(relevant) == expected_count
    if args.phase == "restore":
        assert wait.get("block_state") == "acknowledged" and wait.get("activity_state") == "acknowledged"
    if args.phase == "confirm":
        assert all(record["state"] == "acknowledged" for record in relevant)
    print(json.dumps({"phase": args.phase, "original_version": fixture["original_version"],
                      "original_status": fixture["original_status"], "receipts": [
                          {"id": record["id"], "state": record["state"], "kind": record["operation"]["kind"]}
                          for record in relevant]}))


if __name__ == "__main__":
    main()
