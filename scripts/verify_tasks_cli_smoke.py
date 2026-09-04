#!/usr/bin/env python3
"""Run real OpenMates CLI task commands against a real API.

This smoke test is intentionally not a mocked unit test. It logs the local CLI
into the configured dev/test account, runs the compiled CLI command surface, and
verifies that encrypted task content is displayed as decrypted plaintext. The
script is safe to rerun: it creates one uniquely titled task and deletes it at
the end. Intended for Tasks V1 CLI-first verification.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"


def run(command: list[str], *, cwd: Path = ROOT) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result.stdout


def run_cli(args: list[str]) -> str:
    return run(["node", "dist/cli.js", *args], cwd=CLI_DIR)


def run_cli_json(args: list[str]) -> dict[str, Any]:
    return json.loads(run_cli([*args, "--json"]))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real OpenMates task CLI commands.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Real API URL to test against")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI before running commands")
    parser.add_argument("--activity-only", action="store_true", help="Stop after the focused Task Activity lifecycle")
    args = parser.parse_args()

    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR)

    run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", args.api_url])

    suffix = str(int(time.time()))
    title = f"CLI real smoke task {suffix}"
    edited_title = f"CLI real smoke task edited {suffix}"
    task_id = ""
    short_id = ""
    activity_entry_id = ""

    try:
        if not args.activity_only:
            initial = run_cli_json(["tasks", "list"])
            require(isinstance(initial.get("tasks"), list), "tasks list did not return a task array")

        created = run_cli_json([
            "tasks",
            "create",
            "--title",
            title,
            "--description",
            "Real local API smoke",
            "--assign",
            "user",
        ])["task"]
        task_id = created["task_id"]
        short_id = created["short_id"]
        require(created["title"] == title, "created task title was not decrypted")
        require("encrypted_" not in json.dumps(created), "created task output leaked encrypted fields")

        comment = f"CLI Activity smoke {suffix}\nSecond line"
        added_activity = run_cli_json([
            "tasks",
            "activity",
            "add",
            short_id,
            "--message",
            comment,
            "--status",
            "todo",
        ])["entry"]
        activity_entry_id = added_activity["entry_id"]
        require(added_activity["message"] == comment, "Task Activity add did not decrypt the comment")
        require("encrypted_" not in json.dumps(added_activity), "Task Activity add leaked encrypted fields")

        activity_text = run_cli(["tasks", "activity", "list", short_id, "--status", "todo"])
        require(comment in activity_text, "Task Activity list did not render decrypted multiline text")
        require("via OpenMates CLI" in activity_text, "Task Activity list omitted CLI attribution")
        require("encrypted_" not in activity_text, "Task Activity list leaked encrypted fields")

        deleted_activity = run_cli_json([
            "tasks",
            "activity",
            "delete",
            short_id,
            activity_entry_id,
            "--status",
            "todo",
        ])["entry"]
        require(deleted_activity["kind"] == "tombstone", "Task Activity delete did not return a tombstone")
        require("message" not in deleted_activity, "Task Activity tombstone retained comment content")
        require("encrypted_" not in json.dumps(deleted_activity), "Task Activity tombstone leaked encrypted fields")

        if args.activity_only:
            deleted = run_cli_json(["tasks", "delete", short_id, "--confirm"])
            require(deleted.get("deleted") is True, "tasks delete did not report deletion")
            task_id = ""
            print(json.dumps({"success": True, "api_url": args.api_url, "commands": "real-cli-activity"}, indent=2))
            return 0

        shown_text = run_cli(["tasks", "show", short_id, "--status", "todo"])
        require(title in shown_text, "tasks show did not render decrypted title")
        require("encrypted_" not in shown_text, "tasks show leaked encrypted fields")

        status = run_cli_json(["tasks", "status", short_id, "--status", "todo"])["task"]
        require(status["title"] == title, "tasks status did not resolve/decrypt task")

        board_positioned = run_cli_json(["tasks", "reorder", short_id, "--position", "0", "--status", "todo"])["tasks"][0]
        require(board_positioned["position"] == 0, "tasks reorder did not move task into visible board range")

        board_text = run_cli(["tasks", "board", "--status", "todo"])
        require("OpenMates Tasks Board" in board_text, "tasks board did not render board header")
        board_tasks = run_cli_json(["tasks", "board", "--status", "todo"])["tasks"]
        require(any(task.get("task_id") == task_id for task in board_tasks), "tasks board data did not include the task")

        edited = run_cli_json(["tasks", "edit", short_id, "--title", edited_title])["task"]
        require(edited["title"] == edited_title, "tasks edit did not update/decrypt title")

        blocked = run_cli_json(["tasks", "block", short_id, "--reason", "needs_user_input", "--status", "todo"])["task"]
        require(blocked["status"] == "blocked", "tasks block did not set blocked status")
        require(blocked["blocked_reason_code"] == "needs_user_input", "tasks block did not persist reason")

        unblocked = run_cli_json(["tasks", "unblock", short_id, "--status", "blocked"])["task"]
        require(unblocked["status"] == "todo", "tasks unblock did not return to todo")

        reordered = run_cli_json(["tasks", "reorder", short_id, "--position", "51"])["tasks"][0]
        require(reordered["position"] == 51, "tasks reorder did not update position")
        require("encrypted_" not in json.dumps(reordered), "tasks reorder leaked encrypted fields")

        skipped = run_cli_json(["tasks", "skip", short_id, "--status", "todo"])["task"]
        require(skipped["status"] == "backlog", "tasks skip did not move task to backlog")
        require(skipped["queue_state"] == "skipped", "tasks skip did not mark queue state skipped")
        require(skipped["ai_execution_state"] == "skipped", "tasks skip did not mark AI execution skipped")

        done = run_cli_json(["tasks", "done", short_id, "--status", "backlog"])["task"]
        require(done["status"] == "done", "tasks done did not set done status")

        deleted = run_cli_json(["tasks", "delete", short_id, "--confirm"])
        require(deleted.get("deleted") is True, "tasks delete did not report deletion")
        task_id = ""

        final = run_cli_json(["tasks", "list"])
        require(all(task.get("short_id") != short_id for task in final["tasks"]), "deleted task still appears in list")
    finally:
        if task_id and short_id:
            subprocess.run(["node", "dist/cli.js", "tasks", "delete", short_id, "--confirm", "--json"], cwd=CLI_DIR, text=True, capture_output=True, check=False)

    print(json.dumps({"success": True, "api_url": args.api_url, "commands": "real-cli-local-api"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
