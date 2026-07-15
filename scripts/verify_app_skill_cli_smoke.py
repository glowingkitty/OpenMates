#!/usr/bin/env python3
"""Verify real-dev typed CLI task/workflow commands.

This smoke gate runs the compiled OpenMates CLI against the hosted dev API with
a real test account. It intentionally uses explicit typed commands instead of
generic `openmates apps <app> <skill>` execution, which is forbidden by the CLI
contract. The emitted JSON is sanitized and must not include account credentials
or private plaintext beyond generated test labels.
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


def run_cli_json(args: list[str], *, timeout: int = 120) -> Any:
    output = run(["node", "dist/cli.js", *args, "--json"], cwd=CLI_DIR, timeout=timeout).stdout
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"CLI did not return JSON for {' '.join(args)}:\n{output}") from exc
    return parsed


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_task_create(api_url: str) -> dict[str, Any]:
    suffix = int(time.time())
    result = run_cli_json([
        "--api-url",
        api_url,
        "tasks",
        "create",
        "--title",
        f"CLI typed smoke task {suffix}",
    ])
    require(isinstance(result, dict) and isinstance(result.get("task"), dict), f"task create returned malformed JSON: {result}")
    task = result["task"]
    return {
        "task_id": task.get("task_id"),
        "short_id": task.get("short_id"),
        "status": task.get("status"),
    }


def verify_task_list(api_url: str) -> dict[str, Any]:
    result = run_cli_json(["--api-url", api_url, "tasks", "list"])
    require(isinstance(result, dict) and isinstance(result.get("tasks"), list), f"task list returned malformed JSON: {result}")
    return {"task_count": len(result["tasks"])}


def verify_workflow_list(api_url: str) -> dict[str, Any]:
    result = run_cli_json(["--api-url", api_url, "workflows", "list"])
    workflows = result if isinstance(result, list) else result.get("workflows") if isinstance(result, dict) else None
    require(isinstance(workflows, list), f"workflow list returned malformed JSON: {result}")
    return {"workflow_count": len(workflows)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real-dev typed CLI task/workflow commands.")
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
            "task_list": verify_task_list(args.api_url),
            "workflow_list": verify_workflow_list(args.api_url),
        },
    }
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
