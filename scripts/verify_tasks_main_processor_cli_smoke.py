#!/usr/bin/env python3
"""Verify real CLI main-processor task-tool flows against a real API.

This smoke gate intentionally runs the compiled OpenMates CLI against the dev
API/WebSocket path. It must stay local-first until it passes from this workspace;
only then should equivalent GitHub Actions coverage be added.
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


def run(command: list[str], *, cwd: Path = ROOT, check: bool = True, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)
    if check and result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result


def run_cli(args: list[str], *, check: bool = True, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    return run(["node", "dist/cli.js", *args], cwd=CLI_DIR, check=check, timeout=timeout)


def run_cli_json(args: list[str], *, timeout: int = 240) -> dict[str, Any]:
    output = run_cli([*args, "--json"], timeout=timeout).stdout
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"CLI did not return JSON for {' '.join(args)}:\n{output}") from exc
    if not isinstance(parsed, dict):
        raise AssertionError(f"CLI returned non-object JSON for {' '.join(args)}: {parsed!r}")
    return parsed


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def task_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    events = result.get("taskEvents")
    require(isinstance(events, list), "chat result did not include taskEvents")
    return [event for event in events if isinstance(event, dict)]


def pending_jobs(result: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = result.get("pendingTaskUpdateJobs")
    require(isinstance(jobs, list), "chat result did not include pendingTaskUpdateJobs")
    return [job for job in jobs if isinstance(job, dict)]


def scenario_create(args: argparse.Namespace) -> dict[str, Any]:
    suffix = str(int(time.time()))
    prompt = (
        f"Tasks main-processor smoke {suffix}: create exactly two tasks in this chat using task tools. "
        f"The task titles must be MPT-{suffix}-A write release checklist and MPT-{suffix}-B review launch risk. "
        "Do not browse the web. Reply briefly after the task tools finish."
    )
    result = run_cli_json([
        "chats",
        "new",
        prompt,
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    events = task_events(result)
    require(any(event.get("event_type") == "created" for event in events), f"expected created task event, got {events}")
    require(pending_jobs(result) == [], "CLI should persist pending task update jobs before final JSON output")
    require("acceptedTaskProposals" not in result or result.get("acceptedTaskProposals") == [], "main-processor smoke must not rely on legacy accepted task proposals")
    return {"chat_id": result.get("chatId"), "task_events": events}


def scenario_update(args: argparse.Namespace, seed: dict[str, Any]) -> dict[str, Any]:
    chat_id = seed.get("chat_id")
    require(isinstance(chat_id, str) and chat_id, "create scenario did not return a chat id")
    seed_events = seed.get("task_events")
    require(isinstance(seed_events, list) and len(seed_events) >= 2, "create scenario did not return two task events")
    update_task_id = seed_events[0].get("task_id") if isinstance(seed_events[0], dict) else None
    complete_task_id = seed_events[1].get("task_id") if isinstance(seed_events[1], dict) else None
    require(isinstance(update_task_id, str) and update_task_id, "first create event did not include task_id")
    require(isinstance(complete_task_id, str) and complete_task_id, "second create event did not include task_id")
    result = run_cli_json(
        [
            "chats",
            "send",
            "--chat",
            chat_id,
            (
                f"Update the existing task with id {update_task_id}, currently version 1, so its title mentions final review. "
                f"Mark the existing task with id {complete_task_id}, currently version 1, as complete. "
                "Do not create any new tasks. Reply briefly after those two task changes finish."
            ),
            "--no-pii-detection",
            "--response-timeout-seconds",
            str(args.chat_timeout),
        ],
        timeout=args.chat_timeout + 30,
    )
    events = task_events(result)
    event_types = {event.get("event_type") for event in events}
    require("updated" in event_types or "completed" in event_types, f"expected update or completed task event, got {events}")
    require(pending_jobs(result) == [], "CLI should finish task update jobs before final JSON output")
    return {"chat_id": chat_id, "task_events": events}


def delete_chat_quietly(chat_id: str | None) -> None:
    if chat_id:
        run_cli(["chats", "delete", chat_id, "--yes"], check=False, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real CLI main-processor task-tool flows.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org", help="Real API URL to test against")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI first")
    parser.add_argument("--scenario", choices=["all", "create", "update"], default="all")
    parser.add_argument("--chat-timeout", type=int, default=360, help="Seconds per real AI chat CLI call")
    parser.add_argument("--keep-artifacts", action="store_true", help="Do not delete created chats")
    args = parser.parse_args()

    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR, timeout=180)
    run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", args.api_url], cwd=ROOT, timeout=120)

    results: dict[str, Any] = {"api_url": args.api_url, "scenarios": {}}
    created_chat_id: str | None = None
    try:
        seed = scenario_create(args)
        results["scenarios"]["create"] = seed
        created_chat_id = seed.get("chat_id") if isinstance(seed.get("chat_id"), str) else None
        if args.scenario in {"all", "update"}:
            results["scenarios"]["update"] = scenario_update(args, seed)
        print(json.dumps(results, indent=2))
        return 0
    finally:
        if not args.keep_artifacts:
            delete_chat_quietly(created_chat_id)


if __name__ == "__main__":
    raise SystemExit(main())
