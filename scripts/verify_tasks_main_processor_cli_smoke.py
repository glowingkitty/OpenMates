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
DEFAULT_CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
CLI_DIR = DEFAULT_CLI_DIR
CREATED_CHAT_IDS: set[str] = set()
CREATED_TASK_IDS: set[str] = set()


def run(command: list[str], *, cwd: Path = ROOT, check: bool = True, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)
    if check and result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result


def run_cli(args: list[str], *, check: bool = True, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    return run(["node", "dist/cli.js", *args], cwd=CLI_DIR, check=check, timeout=timeout)


def parse_cli_json(output: str, args: list[str]) -> dict[str, Any]:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"CLI did not return JSON for {' '.join(args)}:\n{output}") from exc
    if not isinstance(parsed, dict):
        raise AssertionError(f"CLI returned non-object JSON for {' '.join(args)}: {parsed!r}")
    return parsed


def run_cli_json(args: list[str], *, timeout: int = 240) -> dict[str, Any]:
    output = run_cli([*args, "--json"], timeout=timeout).stdout
    return parse_cli_json(output, args)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def task_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    track_chat_result(result)
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


def track_task(task: dict[str, Any]) -> None:
    task_id = str(task.get("task_id") or "")
    if task_id:
        CREATED_TASK_IDS.add(task_id)


def track_chat_result(result: dict[str, Any]) -> None:
    chat_id = str(result.get("chatId") or result.get("chat_id") or "")
    if chat_id:
        CREATED_CHAT_IDS.add(chat_id)
    events = result.get("taskEvents")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and event.get("event_type") == "created":
                track_task(event)


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


def refresh_cli_chat_sync(chat_id: str) -> dict[str, Any]:
    force_cli_sync_refresh()
    return run_cli_json(["chats", "show", chat_id], timeout=90)


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


def wait_for_task_status_in(chat_id: str, task_id: str, statuses: set[str], *, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_task: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        listed = run_cli_json(["tasks", "list", "--chat", chat_id], timeout=60)
        by_id = {str(task.get("task_id") or ""): task for task in tasks_from_result(listed)}
        task = by_id.get(task_id)
        if task:
            last_task = task
            if str(task.get("status") or "") in statuses:
                return task
        time.sleep(2)
    raise AssertionError(f"task {task_id} did not reach one of {sorted(statuses)}: got {last_task}")


def create_setup_chat(args: argparse.Namespace, prompt: str) -> str:
    result = run_cli_json([
        "chats",
        "new",
        prompt,
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    chat_id = result.get("chatId")
    require(isinstance(chat_id, str) and chat_id, f"setup chat did not return chatId: {result}")
    CREATED_CHAT_IDS.add(chat_id)
    return chat_id


def create_task_for_chat(chat_id: str, title: str, *, assign: str = "user", status: str = "todo") -> dict[str, Any]:
    created = run_cli_json([
        "tasks",
        "create",
        "--title",
        title,
        "--chat",
        chat_id,
        "--assign",
        assign,
        "--status",
        status,
    ], timeout=60)
    task = task_from_result(created)
    require(str(task.get("task_id") or "") and str(task.get("short_id") or ""), f"created task missing identifiers: {task}")
    track_task(task)
    return task


def assert_no_plans_for_chat(chat_id: str) -> None:
    result = run_cli_json(["plans", "list", "--chat", chat_id], timeout=60)
    plans = result.get("plans")
    require(isinstance(plans, list), f"plans list result did not include plans: {result}")
    require(plans == [], f"task continuation smoke must not create plans, got {plans}")


def list_chat_tasks(chat_id: str, *, refresh_sync: bool = False) -> list[dict[str, Any]]:
    if refresh_sync:
        refresh_cli_chat_sync(chat_id)
    return tasks_from_result(run_cli_json(["tasks", "list", "--chat", chat_id], timeout=60))


def wait_for_tasks_with_titles(chat_id: str, titles: list[str], *, timeout: int) -> list[dict[str, Any]]:
    expected = {title.lower(): title for title in titles}
    deadline = time.monotonic() + timeout
    last_tasks: list[dict[str, Any]] = []
    last_chat: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_chat = refresh_cli_chat_sync(chat_id)
        last_tasks = list_chat_tasks(chat_id)
        by_title = {str(task.get("title") or "").lower(): task for task in last_tasks}
        if expected.keys() <= by_title.keys():
            selected = [by_title[title.lower()] for title in titles]
            for task in selected:
                track_task(task)
            return selected
        time.sleep(2)
    raise AssertionError(
        f"expected natural-language-created task titles {titles}, got tasks={last_tasks}, chat={last_chat}"
    )


def completed_natural_tasks(tasks: list[dict[str, Any]], titles: list[str]) -> set[str]:
    title_set = {title.lower() for title in titles}
    return {
        str(task.get("title") or "")
        for task in tasks
        if str(task.get("title") or "").lower() in title_set and task.get("status") == "done"
    }


def wait_for_natural_task_progress(
    chat_id: str,
    titles: list[str],
    previous_completed: set[str],
    *,
    timeout: int,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_tasks: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last_tasks = wait_for_tasks_with_titles(chat_id, titles, timeout=10)
        completed = completed_natural_tasks(last_tasks, titles)
        if len(completed) > len(previous_completed) or len(completed) == len(titles):
            return last_tasks
        time.sleep(2)
    raise AssertionError(
        f"natural-language follow-up did not complete another task; "
        f"previous={sorted(previous_completed)}, got={last_tasks}"
    )


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
    track_chat_result(result)
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
    track_task(task)
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


def scenario_auto_continuation(args: argparse.Namespace) -> dict[str, Any]:
    suffix = str(int(time.time()))
    chat_id = create_setup_chat(
        args,
        f"Tasks auto-continuation smoke {suffix}: reply setup complete only. Do not create tasks or plans.",
    )
    first = create_task_for_chat(chat_id, f"MPT-{suffix}-AUTO first AI task", assign="ai")
    second = create_task_for_chat(chat_id, f"MPT-{suffix}-AUTO second AI task", assign="ai")
    first_id = str(first["task_id"])
    second_id = str(second["task_id"])
    first_short = str(first["short_id"])
    wait_for_task_status(chat_id, first_id, "in_progress", timeout=args.task_ready_timeout)
    wait_for_task_status(chat_id, second_id, "todo", timeout=args.task_ready_timeout)

    force_cli_sync_refresh()
    completion = run_cli_json([
        "chats",
        "send",
        "--chat",
        chat_id,
        (
            f"Use the task_complete tool for existing visible task {first_short}, currently version 1. "
            "Do not create tasks or plans. Reply briefly after the task tool succeeds."
        ),
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    events = task_events(completion)
    require(any(event.get("event_type") == "completed" and event.get("task_id") == first_id for event in events), f"expected completed event for {first_id}, got {events}")
    first_done = wait_for_task_status(chat_id, first_id, "done", timeout=args.task_ready_timeout)
    second_started = wait_for_task_status_in(chat_id, second_id, {"in_progress", "done"}, timeout=args.task_ready_timeout)
    assert_no_plans_for_chat(chat_id)
    return {"chat_id": chat_id, "task_events": events, "first": first_done, "second": second_started}


def scenario_blocking_continuation(args: argparse.Namespace) -> dict[str, Any]:
    suffix = str(int(time.time()))
    chat_id = create_setup_chat(
        args,
        f"Tasks blocking-continuation smoke {suffix}: reply setup complete only. Do not create tasks or plans.",
    )
    first = create_task_for_chat(chat_id, f"MPT-{suffix}-BLOCK first AI task", assign="ai")
    time.sleep(1)
    blocker = create_task_for_chat(chat_id, f"MPT-{suffix}-BLOCK human gate", assign="user", status="blocked")
    time.sleep(1)
    later = create_task_for_chat(chat_id, f"MPT-{suffix}-BLOCK later AI task", assign="ai")
    first_id = str(first["task_id"])
    blocker_id = str(blocker["task_id"])
    later_id = str(later["task_id"])

    wait_for_task_status(chat_id, first_id, "in_progress", timeout=args.task_ready_timeout)
    wait_for_task_status(chat_id, blocker_id, "blocked", timeout=args.task_ready_timeout)
    wait_for_task_status(chat_id, later_id, "todo", timeout=args.task_ready_timeout)
    force_cli_sync_refresh()
    complete_first = run_cli_json([
        "chats",
        "send",
        "--chat",
        chat_id,
        (
            f"Use the task_complete tool for existing visible task {first['short_id']}, currently version 1. "
            "Do not create tasks or plans. Reply briefly after the task tool succeeds."
        ),
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    first_events = task_events(complete_first)
    require(any(event.get("event_type") == "completed" and event.get("task_id") == first_id for event in first_events), f"expected completed event for {first_id}, got {first_events}")
    wait_for_task_status(chat_id, first_id, "done", timeout=args.task_ready_timeout)
    later_still_todo = wait_for_task_status(chat_id, later_id, "todo", timeout=args.task_ready_timeout)

    force_cli_sync_refresh()
    resolve_blocker = run_cli_json([
        "chats",
        "send",
        "--chat",
        chat_id,
        (
            f"The blocker for existing visible task {blocker['short_id']}, currently version 1, is resolved. "
            "Use the appropriate task tool to unblock it or mark it complete. Do not create tasks or plans. "
            "Reply briefly after the task tool succeeds."
        ),
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    blocker_events = task_events(resolve_blocker)
    require(
        any(event.get("event_type") in {"unblocked", "completed"} and event.get("task_id") == blocker_id for event in blocker_events),
        f"expected unblock or complete event for {blocker_id}, got {blocker_events}",
    )
    later_started = wait_for_task_status_in(chat_id, later_id, {"in_progress", "done"}, timeout=args.task_ready_timeout)
    assert_no_plans_for_chat(chat_id)
    return {
        "chat_id": chat_id,
        "first_task_events": first_events,
        "blocker_task_events": blocker_events,
        "later_before_unblock": later_still_todo,
        "later_after_unblock": later_started,
    }


def scenario_natural_task_workflow(args: argparse.Namespace) -> dict[str, Any]:
    suffix = str(int(time.time()))
    titles = [
        f"MPT-{suffix}-NAT draft one sentence launch note",
        f"MPT-{suffix}-NAT identify one launch risk",
        f"MPT-{suffix}-NAT write final go recommendation",
    ]
    prompt = (
        "I need help organizing a tiny launch prep checklist. "
        "Please create exactly three AI-owned tasks in this chat, one task for each numbered title below. "
        "Copy each title exactly, do not create duplicate or untitled tasks, and do not start working on the tasks yet. "
        f"1. {titles[0]} 2. {titles[1]} 3. {titles[2]}. "
        "Do not create a plan."
    )
    result = run_cli_json([
        "chats",
        "new",
        prompt,
        "--no-pii-detection",
        "--response-timeout-seconds",
        str(args.chat_timeout),
    ], timeout=args.chat_timeout + 30)
    track_chat_result(result)
    chat_id = result.get("chatId")
    require(isinstance(chat_id, str) and chat_id, f"natural workflow did not return chatId: {result}")
    events = task_events(result)
    require(pending_jobs(result) == [], "CLI should finish natural task update jobs before final JSON output")
    assert_no_plans_for_chat(chat_id)

    tasks = wait_for_tasks_with_titles(chat_id, titles, timeout=args.task_ready_timeout)
    require(
        all(str(task.get("assignee_type") or "") == "openmates" for task in tasks),
        f"expected natural workflow tasks to be AI-owned, got {tasks}",
    )
    completed = completed_natural_tasks(tasks, titles)
    followup_results: list[dict[str, Any]] = []
    for attempt, title in enumerate(titles[: args.natural_followup_turns], start=1):
        if len(completed) == len(titles):
            break
        force_cli_sync_refresh()
        followup_args = [
            "chats",
            "send",
            "--chat",
            chat_id,
            (
                f"Please work on the existing task titled \"{title}\" in this chat. "
                "Use only your current knowledge, do not browse the web, write the result briefly, "
                "and mark that task complete when finished. Do not create new tasks and do not create a plan."
            ),
            "--no-pii-detection",
            "--response-timeout-seconds",
            str(args.chat_timeout),
        ]
        followup_process = run_cli([*followup_args, "--json"], check=False, timeout=args.chat_timeout + 30)
        recovered_preflight_conflict = False
        if followup_process.returncode == 0:
            followup = parse_cli_json(followup_process.stdout, followup_args)
            followup_events = task_events(followup)
            events.extend(followup_events)
            require(pending_jobs(followup) == [], "CLI should finish natural follow-up task update jobs before final JSON output")
            tasks = wait_for_natural_task_progress(
                chat_id,
                titles,
                completed,
                timeout=args.task_ready_timeout,
            )
        else:
            combined_output = f"{followup_process.stdout}\n{followup_process.stderr}"
            if "Encrypted chat preflight was rejected" not in combined_output:
                sys.stderr.write(followup_process.stdout)
                sys.stderr.write(followup_process.stderr)
                raise RuntimeError(f"Command failed ({followup_process.returncode}): node dist/cli.js {' '.join(followup_args)} --json")
            recovered_preflight_conflict = True
            tasks = wait_for_natural_task_progress(
                chat_id,
                titles,
                completed,
                timeout=args.task_ready_timeout,
            )
            followup_events = []
        assert_no_plans_for_chat(chat_id)
        followup_results.append({
            "attempt": attempt,
            "title": title,
            "task_events": followup_events,
            "recovered_preflight_conflict": recovered_preflight_conflict,
        })
        completed = completed_natural_tasks(tasks, titles)

    require(len(completed) == len(titles), f"expected all natural workflow tasks completed, got tasks={tasks}")
    require(any(event.get("event_type") == "completed" for event in events), f"expected completed task events, got {events}")
    assert_no_plans_for_chat(chat_id)
    return {
        "chat_id": chat_id,
        "titles": titles,
        "task_events": events,
        "followups": followup_results,
        "final_tasks": tasks,
    }


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
    track_chat_result(source_chat)
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
    track_task(task)
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


def delete_task(task_id: str) -> str | None:
    result = run_cli(["tasks", "delete", task_id, "--confirm", "--json"], check=False, timeout=60)
    if result.returncode == 0:
        return None
    return f"task {task_id}: {(result.stderr or result.stdout).strip()}"


def delete_chat(chat_id: str) -> str | None:
    result = run_cli(["chats", "delete", chat_id, "--yes"], check=False, timeout=60)
    if result.returncode == 0:
        return None
    return f"chat {chat_id}: {(result.stderr or result.stdout).strip()}"


def cleanup_created_resources() -> None:
    failures: list[str] = []
    for resource_type, resource_ids, delete_resource in (
        ("task", CREATED_TASK_IDS, delete_task),
        ("chat", CREATED_CHAT_IDS, delete_chat),
    ):
        for resource_id in sorted(resource_ids):
            try:
                failure = delete_resource(resource_id)
            except Exception as exc:  # noqa: BLE001 - cleanup must continue across every tracked resource.
                failure = f"{resource_type} {resource_id}: {exc}"
            if failure:
                failures.append(failure)
    if failures:
        raise RuntimeError("Task smoke cleanup failed:\n" + "\n".join(failures))


def cleanup_after_smoke(primary_error: BaseException | None) -> None:
    try:
        cleanup_created_resources()
    except Exception as cleanup_error:
        if primary_error is None:
            raise
        sys.stderr.write(f"WARNING: Task smoke cleanup also failed: {cleanup_error}\n")


def main() -> int:
    global CLI_DIR

    parser = argparse.ArgumentParser(description="Verify real CLI main-processor task-tool flows.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org", help="Real API URL to test against")
    parser.add_argument("--cli-dir", default=str(DEFAULT_CLI_DIR), help="Path to a built frontend/packages/openmates-cli directory")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI first")
    parser.add_argument(
        "--scenario",
        choices=[
            "all",
            "create",
            "update",
            "block-unblock",
            "mention-move",
            "auto-continuation",
            "blocking-continuation",
            "natural-task-workflow",
        ],
        default="all",
    )
    parser.add_argument("--chat-timeout", type=int, default=360, help="Seconds per real AI chat CLI call")
    parser.add_argument("--task-ready-timeout", type=int, default=90, help="Seconds to wait for created tasks to become visible before update")
    parser.add_argument("--natural-followup-turns", type=int, default=5, help="Maximum natural follow-up turns to finish natural workflow tasks")
    parser.add_argument("--keep-artifacts", action="store_true", help="Do not delete created Tasks or chats")
    args = parser.parse_args()
    CLI_DIR = Path(args.cli_dir).resolve()

    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR, timeout=180)
    run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", args.api_url], cwd=ROOT, timeout=120)

    results: dict[str, Any] = {"api_url": args.api_url, "scenarios": {}}
    CREATED_CHAT_IDS.clear()
    CREATED_TASK_IDS.clear()
    primary_error: BaseException | None = None
    try:
        seed: dict[str, Any] | None = None
        if args.scenario in {"all", "create", "update", "block-unblock", "mention-move"}:
            seed = scenario_create(args)
            results["scenarios"]["create"] = seed
        if seed and args.scenario in {"all", "update"}:
            results["scenarios"]["update"] = scenario_update(args, seed)
        if seed and args.scenario in {"all", "block-unblock"}:
            results["scenarios"]["block_unblock"] = scenario_block_unblock(args, seed)
        if seed and args.scenario in {"all", "mention-move"}:
            results["scenarios"]["mention_move"] = scenario_mention_move(args, seed)
        if args.scenario in {"all", "auto-continuation"}:
            auto_result = scenario_auto_continuation(args)
            results["scenarios"]["auto_continuation"] = auto_result
        if args.scenario in {"all", "blocking-continuation"}:
            blocking_result = scenario_blocking_continuation(args)
            results["scenarios"]["blocking_continuation"] = blocking_result
        if args.scenario in {"all", "natural-task-workflow"}:
            natural_result = scenario_natural_task_workflow(args)
            results["scenarios"]["natural_task_workflow"] = natural_result
        print(json.dumps(results, indent=2))
        return 0
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if not args.keep_artifacts:
            cleanup_after_smoke(primary_error)


if __name__ == "__main__":
    raise SystemExit(main())
