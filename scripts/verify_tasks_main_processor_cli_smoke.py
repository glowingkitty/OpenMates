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


def tasks_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = result.get("tasks")
    require(isinstance(tasks, list), "task command result did not include tasks")
    return [task for task in tasks if isinstance(task, dict)]


def task_from_result(result: dict[str, Any]) -> dict[str, Any]:
    task = result.get("task")
    require(isinstance(task, dict), "task command result did not include task")
    return task


def pending_jobs(result: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = result.get("pendingTaskUpdateJobs")
    require(isinstance(jobs, list), "chat result did not include pendingTaskUpdateJobs")
    return [job for job in jobs if isinstance(job, dict)]


def wait_for_visible_tasks(chat_id: str, task_ids: set[str], *, timeout: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_tasks: list[dict[str, Any]] = []
    messages_ready = False
    while time.monotonic() < deadline:
        listed = run_cli_json(["tasks", "list", "--chat", chat_id], timeout=60)
        tasks = listed.get("tasks")
        require(isinstance(tasks, list), "tasks list result did not include tasks")
        last_tasks = [task for task in tasks if isinstance(task, dict)]
        visible_ids = {str(task.get("task_id") or "") for task in last_tasks}
        if task_ids.issubset(visible_ids):
            shown = run_cli_json(["chats", "show", chat_id], timeout=60)
            messages = shown.get("messages")
            require(isinstance(messages, list), "chat show result did not include messages")
            message_text = "\n".join(str(message.get("content") or "") for message in messages if isinstance(message, dict))
            messages_ready = all(task_id in message_text for task_id in task_ids)
        if task_ids.issubset(visible_ids) and messages_ready:
            time.sleep(3)
            return last_tasks
        time.sleep(2)
    raise AssertionError(f"created tasks were not visible before update: expected {sorted(task_ids)}, got {last_tasks}")


def force_cli_sync_refresh() -> None:
    sync_cache = Path.home() / ".openmates" / "sync_cache.json"
    sync_cache.unlink(missing_ok=True)


def wait_for_updated_task_state(
    chat_id: str,
    *,
    update_task_id: str,
    complete_task_id: str,
    update_short_id: str,
    complete_short_id: str,
    timeout: int,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_tasks: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        listed = run_cli_json(["tasks", "list", "--chat", chat_id], timeout=60)
        tasks = listed.get("tasks")
        require(isinstance(tasks, list), "tasks list result did not include tasks")
        last_tasks = [task for task in tasks if isinstance(task, dict)]
        by_id = {str(task.get("task_id") or ""): task for task in last_tasks}
        update_task = by_id.get(update_task_id)
        complete_task = by_id.get(complete_task_id)
        if update_task and complete_task:
            title_ready = "final review" in str(update_task.get("title") or "").lower()
            update_version_ready = _task_version(update_task) == 2
            complete_ready = complete_task.get("status") == "done" and _task_version(complete_task) == 2
            messages_ready = _chat_has_task_system_messages(chat_id, update_short_id, complete_short_id)
            if title_ready and update_version_ready and complete_ready and messages_ready:
                return last_tasks
        time.sleep(2)
    raise AssertionError(f"updated tasks were not visible with expected final state: got {last_tasks}")


def _chat_has_task_system_messages(chat_id: str, update_short_id: str, complete_short_id: str) -> bool:
    shown = run_cli_json(["chats", "show", chat_id], timeout=60)
    messages = shown.get("messages")
    require(isinstance(messages, list), "chat show result did not include messages")
    message_text = "\n".join(str(message.get("content") or "") for message in messages if isinstance(message, dict)).lower()
    return (
        update_short_id.lower() in message_text
        and "updated" in message_text
        and complete_short_id.lower() in message_text
        and "completed" in message_text
    )


def _task_version(task: dict[str, Any]) -> int | None:
    try:
        return int(task.get("version"))
    except (TypeError, ValueError):
        return None


def wait_for_task_status(chat_id: str, task_id: str, status: str, *, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_task: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        listed = run_cli_json(["tasks", "list", "--chat", chat_id], timeout=60)
        by_id = {str(task.get("task_id") or ""): task for task in tasks_from_result(listed)}
        task = by_id.get(task_id)
        if task:
            last_task = task
            if task.get("status") == status:
                return task
        time.sleep(2)
    raise AssertionError(f"task {task_id} did not reach status {status}: got {last_task}")


def wait_for_task_chat(task_id: str, chat_id: str, *, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_task: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        listed = run_cli_json(["tasks", "list", "--chat", chat_id], timeout=60)
        by_id = {str(task.get("task_id") or ""): task for task in tasks_from_result(listed)}
        task = by_id.get(task_id)
        last_task = task
        if task and task.get("primary_chat_id") == chat_id:
            return task
        time.sleep(2)
    raise AssertionError(f"task {task_id} did not move to chat {chat_id}: got {last_task}")


def chat_has_text(chat_id: str, expected: str, *, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    needle = expected.lower()
    while time.monotonic() < deadline:
        shown = run_cli_json(["chats", "show", chat_id], timeout=60)
        messages = shown.get("messages")
        require(isinstance(messages, list), "chat show result did not include messages")
        message_text = "\n".join(str(message.get("content") or "") for message in messages if isinstance(message, dict)).lower()
        if needle in message_text:
            return True
        time.sleep(2)
    return False


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
    visible_tasks = wait_for_visible_tasks(chat_id, {update_task_id, complete_task_id}, timeout=args.task_ready_timeout)
    visible_by_id = {str(task.get("task_id") or ""): task for task in visible_tasks}
    update_short_id = visible_by_id.get(update_task_id, {}).get("short_id")
    complete_short_id = visible_by_id.get(complete_task_id, {}).get("short_id")
    require(isinstance(update_short_id, str) and update_short_id, "first created task did not include short_id")
    require(isinstance(complete_short_id, str) and complete_short_id, "second created task did not include short_id")
    force_cli_sync_refresh()
    result = run_cli_json(
        [
            "chats",
            "send",
            "--chat",
            chat_id,
            (
                f"Update existing visible task {update_short_id}, currently version 1, so its title mentions final review. "
                f"Mark existing visible task {complete_short_id}, currently version 1, as complete. "
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
    require({"updated", "completed"}.issubset(event_types), f"expected updated and completed task events, got {events}")
    require(pending_jobs(result) == [], "CLI should finish task update jobs before final JSON output")
    wait_for_updated_task_state(
        chat_id,
        update_task_id=update_task_id,
        complete_task_id=complete_task_id,
        update_short_id=update_short_id,
        complete_short_id=complete_short_id,
        timeout=args.task_ready_timeout,
    )
    return {"chat_id": chat_id, "task_events": events}


def scenario_block_unblock(args: argparse.Namespace, seed: dict[str, Any]) -> dict[str, Any]:
    chat_id = seed.get("chat_id")
    require(isinstance(chat_id, str) and chat_id, "create scenario did not return a chat id")
    suffix = str(int(time.time()))
    created = run_cli_json([
        "tasks",
        "create",
        "--title",
        f"MPT-{suffix}-C unblock smoke task",
        "--chat",
        chat_id,
        "--status",
        "blocked",
    ], timeout=60)
    task = task_from_result(created)
    task_id = str(task.get("task_id") or "")
    short_id = str(task.get("short_id") or "")
    require(task_id and short_id, f"created blocked task did not include IDs: {task}")
    wait_for_task_status(chat_id, task_id, "blocked", timeout=args.task_ready_timeout)
    force_cli_sync_refresh()
    result = run_cli_json([
        "chats",
        "send",
        "--chat",
        chat_id,
        (
            f"The blocker for existing visible task {short_id}, currently version 1, is resolved. "
            "Mark that task as no longer blocked and ready to do. Do not create new tasks. Reply briefly after the task change finishes."
        ),
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    events = task_events(result)
    require(any(event.get("event_type") == "unblocked" and event.get("task_id") == task_id for event in events), f"expected unblocked event for {task_id}, got {events}")
    require(pending_jobs(result) == [], "CLI should finish unblock task update jobs before final JSON output")
    wait_for_task_status(chat_id, task_id, "todo", timeout=args.task_ready_timeout)
    return {"chat_id": chat_id, "task_events": events}


def scenario_mention_move(args: argparse.Namespace, seed: dict[str, Any]) -> dict[str, Any]:
    target_chat_id = seed.get("chat_id")
    require(isinstance(target_chat_id, str) and target_chat_id, "create scenario did not return a target chat id")
    seed_events = seed.get("task_events")
    require(isinstance(seed_events, list) and seed_events, "create scenario did not return target task events")
    target_task_ids = {str(event.get("task_id") or "") for event in seed_events if isinstance(event, dict) and event.get("task_id")}
    require(bool(target_task_ids), "create scenario did not return target task ids")
    wait_for_visible_tasks(target_chat_id, target_task_ids, timeout=args.task_ready_timeout)
    suffix = str(int(time.time()))
    source_chat = run_cli_json([
        "chats",
        "new",
        f"Tasks main-processor mention/move setup {suffix}: reply with exactly setup complete. Do not create tasks.",
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    source_chat_id = source_chat.get("chatId")
    require(isinstance(source_chat_id, str) and source_chat_id, "source chat setup did not return chatId")
    created = run_cli_json([
        "tasks",
        "create",
        "--title",
        f"MPT-{suffix}-D referenced move smoke task",
        "--chat",
        source_chat_id,
    ], timeout=60)
    task = task_from_result(created)
    task_id = str(task.get("task_id") or "")
    short_id = str(task.get("short_id") or "")
    require(task_id and short_id, f"created referenced task did not include IDs: {task}")
    require(task.get("primary_chat_id") == source_chat_id, f"referenced task was not attached to source chat: {task}")
    wait_for_task_chat(task_id, source_chat_id, timeout=args.task_ready_timeout)

    unchanged = task_from_result(run_cli_json(["tasks", "show", short_id, "--chat", source_chat_id], timeout=60))
    require(unchanged.get("primary_chat_id") == source_chat_id, f"context-only mention changed primary chat: {unchanged}")

    force_cli_sync_refresh()
    move_result = run_cli_json([
        "chats",
        "send",
        "--chat",
        target_chat_id,
        (
            f"Use the task_move tool exactly once for existing referenced task @{short_id}, currently version 1. "
            f"Move it from its current chat into destination chat ID {target_chat_id}. "
            "Do not edit the task title and do not create new tasks. Reply only after the task_move tool succeeds."
        ),
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    events = task_events(move_result)
    require(any(event.get("event_type") == "moved" and event.get("task_id") == task_id for event in events), f"expected moved event for {task_id}, got {events}")
    require(pending_jobs(move_result) == [], "CLI should finish move task update jobs before final JSON output")
    wait_for_task_chat(task_id, target_chat_id, timeout=args.task_ready_timeout)
    return {"chat_id": target_chat_id, "source_chat_id": source_chat_id, "task_events": events}


def delete_chat_quietly(chat_id: str | None) -> None:
    if chat_id:
        run_cli(["chats", "delete", chat_id, "--yes"], check=False, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real CLI main-processor task-tool flows.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org", help="Real API URL to test against")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI first")
    parser.add_argument("--scenario", choices=["all", "create", "update", "block-unblock", "mention-move"], default="all")
    parser.add_argument("--chat-timeout", type=int, default=360, help="Seconds per real AI chat CLI call")
    parser.add_argument("--task-ready-timeout", type=int, default=90, help="Seconds to wait for created tasks to become visible before update")
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
        if args.scenario in {"all", "block-unblock"}:
            results["scenarios"]["block_unblock"] = scenario_block_unblock(args, seed)
        if args.scenario in {"all", "mention-move"}:
            results["scenarios"]["mention_move"] = scenario_mention_move(args, seed)
        print(json.dumps(results, indent=2))
        return 0
    finally:
        if not args.keep_artifacts:
            delete_chat_quietly(created_chat_id)


if __name__ == "__main__":
    raise SystemExit(main())
