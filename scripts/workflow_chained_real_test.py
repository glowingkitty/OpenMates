#!/usr/bin/env python3
"""Real dev-server chained Workflow verification.

This script proves a Workflow is more than a single skill execution: a trigger
starts a graph, one app-skill output is templated into a second app skill, and
the resulting value is templated into chat-delivery and notification actions.
It shells out to the built CLI against the real dev API and uses no mocked
OpenMates API calls.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from workflow_real_test_helpers import resolve_cli_path, run_cli, run_cli_json


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "waiting"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chained real Workflow proofs through the OpenMates CLI")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--cli-path")
    parser.add_argument("--home")
    parser.add_argument("--schedule-delay-seconds", type=int, default=75)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()

    cli_path = resolve_cli_path(args.cli_path)
    with tempfile.TemporaryDirectory(prefix="openmates-workflow-chain-") as tmp:
        tmp_path = Path(tmp)
        manual = _run_manual_chain(cli_path, args.api_url, tmp_path, args.home, args.timeout_seconds)
        scheduled = _run_scheduled_chain(
            cli_path,
            args.api_url,
            tmp_path,
            args.home,
            args.schedule_delay_seconds,
            args.timeout_seconds,
        )

    print(json.dumps({"manual": manual, "scheduled": scheduled}, indent=2, sort_keys=True))
    return 0


def _run_manual_chain(cli_path: Path, api_url: str, tmp_path: Path, home: str | None, timeout_seconds: int) -> dict[str, Any]:
    workflow_file = tmp_path / "manual-chain.yml"
    workflow_file.write_text(_workflow_yaml("manual", "manual: {}"), encoding="utf-8")
    workflow_id = _create_and_enable(cli_path, api_url, workflow_file, home)
    try:
        run = run_cli_json(
            cli_path,
            api_url,
            ["workflows", "run", workflow_id, "--idempotency-key", f"manual-chain-{int(time.time())}", "--yes"],
            home=home,
            timeout_seconds=120,
        )
        return _validated_summary(_poll_run(cli_path, api_url, workflow_id, str(run["id"]), home, timeout_seconds))
    finally:
        _delete_workflow(cli_path, api_url, workflow_id, home)


def _run_scheduled_chain(
    cli_path: Path,
    api_url: str,
    tmp_path: Path,
    home: str | None,
    schedule_delay_seconds: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    run_at = datetime.now(UTC) + timedelta(seconds=schedule_delay_seconds)
    workflow_file = tmp_path / "scheduled-chain.yml"
    workflow_file.write_text(
        _workflow_yaml(
            "scheduled",
            "schedule:\n    type: once\n    at: " + json.dumps(run_at.isoformat()),
        ),
        encoding="utf-8",
    )
    workflow_id = _create_and_enable(cli_path, api_url, workflow_file, home)
    try:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            runs = run_cli_json(cli_path, api_url, ["workflows", "runs", workflow_id], home=home, timeout_seconds=60)
            scheduled_run = next((item for item in runs if item.get("trigger_type") == "schedule"), None)
            if scheduled_run:
                return _validated_summary(_poll_run(cli_path, api_url, workflow_id, str(scheduled_run["id"]), home, timeout_seconds))
            time.sleep(3)
        raise RuntimeError("Timed out waiting for scheduled chained workflow run")
    finally:
        _delete_workflow(cli_path, api_url, workflow_id, home)


def _workflow_yaml(label: str, trigger_yaml: str) -> str:
    return f"""
title: Real chained workflow verification ({label})
start_when:
  {trigger_yaml}
run_content_retention: last_5
steps:
  - id: first_math
    use_app_skill: math.calculate
    input:
      expression: 2 + 2
  - id: second_math
    use_app_skill: math.calculate
    input:
      expression: "{{{{ steps.first_math.raw.result_numeric }}}} + 3"
  - id: chat_delivery
    send_chat_message:
      title: "Workflow chained result"
      message: "The chained math result is {{{{ steps.second_math.raw.result_numeric }}}}."
  - id: push_delivery
    send_notification:
      title: "Workflow result"
      body: "The chained math result is {{{{ steps.second_math.raw.result_numeric }}}}."
""".lstrip()


def _create_and_enable(cli_path: Path, api_url: str, workflow_file: Path, home: str | None) -> str:
    created = run_cli_json(cli_path, api_url, ["workflows", "create", "--file", str(workflow_file)], home=home, timeout_seconds=120)
    workflow_id = created.get("workflow", {}).get("id")
    if not isinstance(workflow_id, str) or not workflow_id:
        raise RuntimeError(f"Workflow create did not return an id: {created}")
    run_cli_json(cli_path, api_url, ["workflows", "enable", workflow_id], home=home, timeout_seconds=60)
    return workflow_id


def _poll_run(cli_path: Path, api_url: str, workflow_id: str, run_id: str, home: str | None, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = run_cli_json(cli_path, api_url, ["workflows", "run-show", workflow_id, run_id], home=home, timeout_seconds=60)
        if last.get("status") in TERMINAL_STATUSES:
            return last
        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for chained workflow run: {last}")


def _validated_summary(run: dict[str, Any]) -> dict[str, Any]:
    by_id = {node.get("node_id"): node for node in run.get("node_runs", []) if isinstance(node, dict)}
    required = ["trigger", "first_math", "second_math", "chat_delivery", "push_delivery"]
    missing = [node_id for node_id in required if node_id not in by_id]
    if missing:
        raise RuntimeError(f"Chained workflow run missing nodes {missing}: {run}")
    if run.get("status") != "completed":
        raise RuntimeError(f"Expected completed chained workflow, got {run.get('status')}: {run}")
    first = by_id["first_math"].get("output_summary", {}).get("raw", {})
    second = by_id["second_math"].get("output_summary", {}).get("raw", {})
    chat = by_id["chat_delivery"].get("output_summary", {})
    notification = by_id["push_delivery"].get("output_summary", {})
    if first.get("result_numeric") != 4:
        raise RuntimeError(f"Expected first math result 4, got {first}")
    if second.get("expression_raw") != "4.0 + 3" or second.get("result_numeric") != 7:
        raise RuntimeError(f"Expected second math to consume first output and produce 7, got {second}")
    if chat.get("type") != "send_chat_message" or chat.get("status") != "delivery_pending" or not chat.get("delivery_id"):
        raise RuntimeError(f"Expected pending chat delivery output, got {chat}")
    if notification.get("type") != "send_notification":
        raise RuntimeError(f"Expected notification action output, got {notification}")
    if by_id["push_delivery"].get("status") not in {"completed", "skipped"}:
        raise RuntimeError(f"Expected notification completed or skipped, got {by_id['push_delivery']}")
    return {
        "run_id": run.get("id"),
        "workflow_id": run.get("workflow_id"),
        "status": run.get("status"),
        "first_math": {"input": "2 + 2", "result_numeric": first.get("result_numeric")},
        "second_math": {"input": second.get("expression_raw"), "result_numeric": second.get("result_numeric")},
        "chat_delivery": {
            "status": chat.get("status"),
            "delivery_id": chat.get("delivery_id"),
            "chat_id": chat.get("chat_id"),
            "message_id": chat.get("message_id"),
        },
        "notification": {
            "status": by_id["push_delivery"].get("status"),
            "skipped_reason": by_id["push_delivery"].get("skipped_reason"),
            "output": notification,
        },
    }


def _delete_workflow(cli_path: Path, api_url: str, workflow_id: str, home: str | None) -> None:
    run_cli(cli_path, api_url, ["workflows", "disable", workflow_id], home=home, timeout_seconds=60)
    run_cli(cli_path, api_url, ["workflows", "delete", workflow_id, "--yes"], home=home, timeout_seconds=60)


if __name__ == "__main__":
    raise SystemExit(main())
