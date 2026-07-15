#!/usr/bin/env python3
"""Verify real-dev CLI app-skill embeds through generic app commands.

This smoke gate runs the compiled OpenMates CLI against the hosted dev API with
a real test account. It validates the backend/CLI contract before SDK parity:
task create succeeds, task search returns the expected connected-client waiting
state, and workflow search succeeds server-side. The emitted JSON is sanitized
and must not include account credentials or private plaintext beyond generated
test labels.
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


def run(command: list[str], *, cwd: Path = ROOT, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)
    if check and result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result


def run_cli_json(args: list[str], *, timeout: int = 120) -> dict[str, Any]:
    output = run(["node", "dist/cli.js", *args, "--json"], cwd=CLI_DIR, timeout=timeout).stdout
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


def skill_data(result: dict[str, Any], *, skill_id: str) -> dict[str, Any]:
    require(result.get("success") is True, f"top-level {skill_id} call failed: {result}")
    data = result.get("data")
    require(isinstance(data, dict), f"{skill_id} response did not include object data: {result}")
    require(data.get("skill_id") == skill_id, f"expected skill_id {skill_id}, got {data.get('skill_id')!r}")
    return data


def summarize_result(data: dict[str, Any]) -> dict[str, Any]:
    results = data.get("results")
    if not isinstance(results, list):
        results = []
    first = results[0] if results and isinstance(results[0], dict) else {}
    return {
        "success": data.get("success"),
        "app_id": data.get("app_id"),
        "skill_id": data.get("skill_id"),
        "status": data.get("status"),
        "result_count": data.get("result_count"),
        "first_result_type": first.get("type"),
        "first_result_id": first.get("task_id") or first.get("workflow_id"),
        "first_result_status": first.get("status"),
    }


def verify_task_create(api_url: str) -> dict[str, Any]:
    suffix = int(time.time())
    data = skill_data(
        run_cli_json([
            "--api-url",
            api_url,
            "apps",
            "tasks",
            "create",
            "--input",
            json.dumps({"title": f"CLI app-skill smoke task {suffix}", "assignee": "user"}),
        ]),
        skill_id="create",
    )
    require(data.get("success") is True, f"task create app skill failed: {data.get('error') or data}")
    require((data.get("result_count") or 0) >= 1, f"task create returned no child task results: {data}")
    results = data.get("results")
    require(isinstance(results, list) and isinstance(results[0], dict), f"task create results malformed: {data}")
    require(results[0].get("type") == "task", f"task create first result was not a task: {results[0]}")
    return summarize_result(data)


def verify_task_search(api_url: str) -> dict[str, Any]:
    data = skill_data(
        run_cli_json([
            "--api-url",
            api_url,
            "apps",
            "tasks",
            "search",
            "--input",
            json.dumps({"query": "CLI app-skill smoke task"}),
        ]),
        skill_id="search",
    )
    require(data.get("success") is True, f"task search app skill failed: {data.get('error') or data}")
    require(data.get("status") == "waiting_for_client", f"task search should wait for connected client, got {data}")
    pending = data.get("pending_client_search")
    require(isinstance(pending, dict) and pending.get("request_id"), f"task search missing pending request: {data}")
    summary = summarize_result(data)
    summary["pending_request_id"] = pending.get("request_id")
    summary["notification_queued"] = pending.get("notification_queued")
    return summary


def verify_workflow_search(api_url: str) -> dict[str, Any]:
    data = skill_data(
        run_cli_json([
            "--api-url",
            api_url,
            "apps",
            "workflows",
            "search",
            "--input",
            json.dumps({"query": "weather"}),
        ]),
        skill_id="search",
    )
    require(data.get("success") is True, f"workflow search app skill failed: {data.get('error') or data}")
    require(data.get("status") != "waiting_for_client", f"workflow search should be server-side, got {data}")
    return summarize_result(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real-dev generic CLI app-skill task/workflow commands.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org", help="Real API URL to test against")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI first")
    args = parser.parse_args()

    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR, timeout=180)
    run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", args.api_url], cwd=ROOT, timeout=120)

    results = {
        "api_url": args.api_url,
        "scenarios": {
            "task_create": verify_task_create(args.api_url),
            "task_search": verify_task_search(args.api_url),
            "workflow_search": verify_workflow_search(args.api_url),
        },
    }
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
