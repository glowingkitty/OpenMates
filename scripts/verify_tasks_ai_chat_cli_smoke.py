#!/usr/bin/env python3
"""Run real CLI AI chat task-flow smoke scenarios against a real API.

This script intentionally uses the compiled OpenMates CLI and real API/WebSocket
chat inference. It does not mock OpenMates API calls. The scenarios verify that
assistant task proposals can be accepted into encrypted Tasks V1 records, that
chat-scoped AI tasks are executed one at a time, and that block/unblock queue
handling is observable from task state.
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
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"CLI did not return JSON for {' '.join(args)}:\n{output}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def accepted_tasks(result: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = result.get("acceptedTaskProposals")
    require(isinstance(tasks, list), "chat result did not include acceptedTaskProposals")
    return [task for task in tasks if isinstance(task, dict)]


def list_chat_tasks(chat_id: str) -> list[dict[str, Any]]:
    data = run_cli_json(["tasks", "list", "--chat", chat_id])
    tasks = data.get("tasks")
    require(isinstance(tasks, list), "tasks list did not return a task array")
    return [task for task in tasks if isinstance(task, dict)]


def delete_task_quietly(short_id: str) -> None:
    run_cli(["tasks", "delete", short_id, "--confirm", "--json"], check=False, timeout=60)


def delete_chat_quietly(chat_id: str) -> None:
    run_cli(["chats", "delete", chat_id, "--yes"], check=False, timeout=60)


def wait_for_task_state(short_id: str, statuses: set[str], *, timeout_seconds: int, interval_seconds: int = 5) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = run_cli_json(["tasks", "status", short_id])["task"]
        if last.get("status") in statuses:
            return last
        time.sleep(interval_seconds)
    raise AssertionError(f"Task {short_id} did not reach {sorted(statuses)} within {timeout_seconds}s; last={last}")


def create_chat_with_accepted_tasks(prompt: str, *, timeout: int) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    result = run_cli_json([
        "chats",
        "new",
        prompt,
        "--accept-task-proposals",
        "--no-pii-detection",
    ], timeout=timeout)
    chat_id = result.get("chatId")
    require(isinstance(chat_id, str) and chat_id, "chat result did not include chatId")
    tasks = accepted_tasks(result)
    require(all("encrypted_" not in json.dumps(task) for task in tasks), "accepted task output leaked encrypted fields")
    return chat_id, tasks, result


def scenario_explicit_multi_task(args: argparse.Namespace) -> dict[str, Any]:
    suffix = str(int(time.time()))
    prompt = (
        f"Tasks V1 CLI smoke {suffix}: explicitly create exactly three separate tasks for this chat. "
        "Use these task lines exactly as the saved task titles:\n"
        f"- EXPLICIT-{suffix}-A summarize the launch checklist\n"
        f"- EXPLICIT-{suffix}-B draft a short launch announcement\n"
        f"- EXPLICIT-{suffix}-C identify one review risk\n"
        "Do not browse the web. Reply briefly after confirming the tasks."
    )
    chat_id, tasks, _result = create_chat_with_accepted_tasks(prompt, timeout=args.chat_timeout)
    require(len(tasks) >= 2, f"expected at least 2 accepted explicit task proposals, got {len(tasks)}")
    scoped = list_chat_tasks(chat_id)
    require(len(scoped) >= len(tasks), "chat-scoped task list did not include accepted explicit tasks")
    return {"chat_id": chat_id, "tasks": tasks}


def scenario_implicit_split(args: argparse.Namespace) -> dict[str, Any]:
    suffix = str(int(time.time()))
    prompt = (
        f"Tasks V1 CLI implicit smoke {suffix}: I need to prepare for a small product launch tomorrow. "
        "Please help me get it ready. What's on my mind:\n"
        "- finish the launch checklist\n"
        "- draft a short announcement\n"
        "- identify what needs final review\n"
        "Do not browse the web and do not ask me to create tasks; just help organize the work naturally."
    )
    chat_id, tasks, _result = create_chat_with_accepted_tasks(prompt, timeout=args.chat_timeout)
    require(len(tasks) >= 2, f"expected at least 2 accepted implicit task proposals, got {len(tasks)}")
    return {"chat_id": chat_id, "tasks": tasks}


def scenario_sequential_execution(args: argparse.Namespace, seed: dict[str, Any]) -> dict[str, Any]:
    tasks = [task for task in seed["tasks"] if isinstance(task.get("short_id"), str)]
    require(len(tasks) >= 2, "sequential scenario needs at least two accepted tasks")
    first = tasks[0]
    second = tasks[1]

    first_started = run_cli_json(["tasks", "start", first["short_id"]], timeout=120)["task"]
    require(first_started.get("status") == "in_progress", "first task did not start")

    second_attempt = run_cli(["tasks", "start", second["short_id"], "--json"], check=False, timeout=120)
    require(second_attempt.returncode != 0, "second task started while first task was active")
    second_attempt_output = (second_attempt.stderr + second_attempt.stdout).lower()
    require(
        "409" in second_attempt_output or "conflict" in second_attempt_output,
        f"second task conflict did not expose a conflict response: {second_attempt.stderr}{second_attempt.stdout}",
    )

    first_done = wait_for_task_state(first["short_id"], {"done", "blocked"}, timeout_seconds=args.ai_task_timeout)
    require(first_done.get("status") == "done", f"first task did not complete cleanly: {first_done}")

    second_started = run_cli_json(["tasks", "start", second["short_id"]], timeout=120)["task"]
    require(second_started.get("status") == "in_progress", "second task did not start after first completed")
    second_terminal = wait_for_task_state(second["short_id"], {"done", "blocked"}, timeout_seconds=args.ai_task_timeout)
    require(second_terminal.get("status") == "done", f"second task did not complete cleanly: {second_terminal}")

    return {"first": first_done, "second": second_terminal}


def scenario_blocker(args: argparse.Namespace) -> dict[str, Any]:
    suffix = str(int(time.time()))
    prompt = (
        f"Tasks V1 CLI blocker smoke {suffix}: propose one task titled BLOCKER-{suffix}. "
        "Use this task line as the saved task title:\n"
        f"- BLOCKER-{suffix} ask for the missing destination city before continuing\n"
        "Do not browse the web. The assistant should ask for the city and wait if it is missing."
    )
    chat_id, tasks, _result = create_chat_with_accepted_tasks(prompt, timeout=args.chat_timeout)
    require(tasks, "blocker scenario did not create an accepted task")
    task = tasks[0]
    short_id = task["short_id"]
    blocked = run_cli_json(["tasks", "block", short_id, "--reason", "needs_user_input"], timeout=120)["task"]
    require(blocked.get("status") == "blocked", f"expected blocker task to enter blocked state, got {blocked}")
    require(blocked.get("blocked_reason_code"), "blocked task did not include a reason code")

    run_cli_json([
        "chats",
        "send",
        "--chat",
        chat_id,
        "The missing destination city is Berlin. Continue the blocked task now.",
        "--no-pii-detection",
    ], timeout=args.chat_timeout)
    unblocked = run_cli_json(["tasks", "unblock", short_id], timeout=120)["task"]
    require(unblocked.get("status") == "todo", f"blocked task did not return to todo after unblock: {unblocked}")
    require(not unblocked.get("blocked_reason_code"), "unblocked task still had a blocked reason")

    started = run_cli_json(["tasks", "start", short_id], timeout=120)["task"]
    require(started.get("status") == "in_progress", "unblocked task did not start")
    terminal = wait_for_task_state(short_id, {"blocked", "done"}, timeout_seconds=args.ai_task_timeout)
    require(terminal.get("status") == "done", f"unblocked task did not complete cleanly: {terminal}")
    return {"chat_id": chat_id, "task": terminal, "blocked_reason": blocked.get("blocked_reason_code")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real CLI AI chat task flows.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org", help="Real API URL to test against")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI first")
    parser.add_argument("--scenario", choices=["all", "explicit", "implicit", "blocker"], default="all")
    parser.add_argument("--chat-timeout", type=int, default=360, help="Seconds per real AI chat CLI call")
    parser.add_argument("--ai-task-timeout", type=int, default=360, help="Seconds to wait for AI task terminal state")
    parser.add_argument("--unblock-timeout", type=int, default=180, help="Seconds to wait for blocked task resume")
    parser.add_argument("--keep-artifacts", action="store_true", help="Do not delete created tasks/chats")
    args = parser.parse_args()

    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR, timeout=180)
    run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", args.api_url], cwd=ROOT, timeout=120)

    created_chats: list[str] = []
    created_tasks: list[str] = []
    results: dict[str, Any] = {"api_url": args.api_url, "scenarios": {}}
    try:
        if args.scenario in {"all", "explicit"}:
            explicit = scenario_explicit_multi_task(args)
            results["scenarios"]["explicit"] = explicit
            created_chats.append(explicit["chat_id"])
            created_tasks.extend(task["short_id"] for task in explicit["tasks"] if isinstance(task.get("short_id"), str))
            if args.scenario == "all":
                results["scenarios"]["sequential"] = scenario_sequential_execution(args, explicit)

        if args.scenario in {"all", "implicit"}:
            implicit = scenario_implicit_split(args)
            results["scenarios"]["implicit"] = implicit
            created_chats.append(implicit["chat_id"])
            created_tasks.extend(task["short_id"] for task in implicit["tasks"] if isinstance(task.get("short_id"), str))

        if args.scenario in {"all", "blocker"}:
            blocker = scenario_blocker(args)
            results["scenarios"]["blocker"] = blocker
            created_chats.append(blocker["chat_id"])
            task = blocker.get("task")
            if isinstance(task, dict) and isinstance(task.get("short_id"), str):
                created_tasks.append(task["short_id"])
    finally:
        if not args.keep_artifacts:
            for short_id in reversed(created_tasks):
                delete_task_quietly(short_id)
            for chat_id in reversed(created_chats):
                delete_chat_quietly(chat_id)

    results["success"] = True
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
