#!/usr/bin/env python3
"""Production CLI smoke checks for OpenMates.

Purpose: run tiny, explicit CLI checks against the live production API without
the browser-heavy Playwright stack. The paid chat scenario is intentionally one
short prompt so it verifies the LLM pipeline while keeping cost bounded. The web
app-skill scenario calls the typed `openmates apps web search` command directly
so production app-skill routing is covered without involving chat UI state.
Security: reads the API key from env/arguments and never prints it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
DEFAULT_API_URL = "https://api.openmates.org"
CHAT_PROMPT = "Reply with exactly: PONG"
WEB_SEARCH_QUERY = "OpenMates official website"


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)


def parse_cli_json(output: str, command_label: str) -> Any:
    stripped = output.strip()
    if not stripped:
        raise AssertionError(f"{command_label} returned empty output")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start >= 0:
            return json.loads(stripped[start:])
        raise AssertionError(f"{command_label} did not return JSON: {stripped[:300]}")


def run_cli_json(args: list[str], *, api_url: str, api_key: str, timeout: int = 180) -> Any:
    command = [
        "node",
        "dist/cli.js",
        "--api-url",
        api_url,
        "--api-key",
        api_key,
        *args,
        "--json",
    ]
    result = run(command, cwd=CLI_DIR, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown CLI failure").strip()
        raise RuntimeError(f"CLI command failed ({result.returncode}): {' '.join(args)}\n{detail[:700]}")
    return parse_cli_json(result.stdout, " ".join(args))


def verify_paid_chat(api_url: str, api_key: str) -> dict[str, Any]:
    started = time.time()
    result = run_cli_json(
        [
            "chats",
            "new",
            CHAT_PROMPT,
            "--response-timeout-seconds",
            "120",
        ],
        api_url=api_url,
        api_key=api_key,
        timeout=180,
    )
    assistant = str(result.get("assistant") or result.get("content") or result.get("response") or "")
    if "PONG" not in assistant.upper():
        raise AssertionError(f"Expected assistant response to contain PONG, got: {assistant[:300]}")
    return {
        "status": "passed",
        "duration_seconds": round(time.time() - started, 2),
        "assistant_preview": assistant[:80],
        "chat_id_hash": str(result.get("chatId") or result.get("chat_id") or "")[:8] or None,
        "model_name": result.get("modelName") or result.get("model_name"),
    }


def flatten_result_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("results")
        if isinstance(nested, list):
            items.extend(item for item in nested if isinstance(item, dict))
        else:
            items.append(entry)
    return items


def verify_web_search(api_url: str, api_key: str) -> dict[str, Any]:
    started = time.time()
    result = run_cli_json(
        ["apps", "web", "search", WEB_SEARCH_QUERY],
        api_url=api_url,
        api_key=api_key,
        timeout=180,
    )
    items = flatten_result_items(result)
    if not items:
        raise AssertionError(f"Expected web search results, got: {json.dumps(result)[:500]}")
    joined = json.dumps(items[:5]).lower()
    if "openmates" not in joined:
        raise AssertionError(f"Expected an OpenMates-related web search result, got: {joined[:500]}")
    return {
        "status": "passed",
        "duration_seconds": round(time.time() - started, 2),
        "result_count": len(items),
        "first_title": items[0].get("title") or items[0].get("name"),
        "provider": (result.get("data") if isinstance(result.get("data"), dict) else result).get("provider") if isinstance(result, dict) else None,
    }


def scenario_failure(error: BaseException) -> dict[str, Any]:
    return {
        "status": "failed",
        "error": str(error)[:900],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production OpenMates CLI smoke checks.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Production API URL")
    parser.add_argument("--api-key", default=os.environ.get("OPENMATES_API_KEY", ""), help="Production smoke API key")
    parser.add_argument("--scenario", choices=["paid-chat", "app-skill-web-search", "all"], default="all")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI before running")
    args = parser.parse_args()

    if not args.api_key:
        print(json.dumps({"status": "failed", "error": "OPENMATES_API_KEY is required"}, indent=2))
        return 1

    if not args.skip_build:
        build = run(["npm", "run", "build"], cwd=CLI_DIR, timeout=240)
        if build.returncode != 0:
            print(json.dumps({"status": "failed", "error": (build.stderr or build.stdout)[:900]}, indent=2))
            return 1

    scenarios: dict[str, dict[str, Any]] = {}
    checks: list[tuple[str, Any]] = []
    if args.scenario in {"paid-chat", "all"}:
        checks.append(("paid_chat", verify_paid_chat))
    if args.scenario in {"app-skill-web-search", "all"}:
        checks.append(("app_skill_web_search", verify_web_search))

    for name, fn in checks:
        try:
            scenarios[name] = fn(args.api_url, args.api_key)
        except Exception as exc:  # noqa: BLE001 - produce structured smoke output for notifications.
            scenarios[name] = scenario_failure(exc)

    failed = [name for name, result in scenarios.items() if result.get("status") != "passed"]
    payload = {
        "status": "failed" if failed else "passed",
        "api_url": args.api_url,
        "scenario": args.scenario,
        "scenarios": scenarios,
    }
    print(json.dumps(payload, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
