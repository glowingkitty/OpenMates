#!/usr/bin/env python3
"""Run real OpenMates CLI plan commands against a real API.

This smoke test exercises the compiled CLI, not mocked handlers. It logs into
the configured dev/test account, creates uniquely titled encrypted plans, reads
them back as decrypted plaintext, updates management fields, and archives the
created records during cleanup. It is intended for Plans V1 CLI-first
verification before web workspace changes rely on plan parity.
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


def find_plan_by_title(plans: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    for plan in plans:
        if plan.get("title") == title:
            return plan
    return None


def archive_plan(plan_id_or_short_id: str) -> None:
    subprocess.run(
        ["node", "dist/cli.js", "plans", "archive", plan_id_or_short_id, "--json"],
        cwd=CLI_DIR,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real OpenMates plan CLI commands.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Real API URL to test against")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the CLI before running commands")
    args = parser.parse_args()

    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR)

    run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", args.api_url])

    suffix = str(int(time.time()))
    title = f"CLI real smoke plan {suffix}"
    edited_title = f"CLI real smoke plan edited {suffix}"
    ask_title = f"CLI ask smoke plan {suffix}"
    plan_id = ""
    short_id = ""
    ask_plan_id = ""
    ask_short_id = ""

    try:
        initial = run_cli_json(["plans", "list"])
        require(isinstance(initial.get("plans"), list), "plans list did not return a plan array")

        created = run_cli_json([
            "plans",
            "create",
            "--title",
            title,
            "--summary",
            "Real local API smoke",
            "--goal",
            "Verify live CLI plan encryption",
            "--risks",
            "Regression coverage gap",
        ])["plan"]
        plan_id = created["plan_id"]
        short_id = created["short_id"]
        require(created["title"] == title, "created plan title was not decrypted")
        require(created["summary"] == "Real local API smoke", "created plan summary was not decrypted")
        require("encrypted_" not in json.dumps(created), "created plan output leaked encrypted fields")

        shown_text = run_cli(["plans", "show", short_id])
        require(title in shown_text, "plans show did not render decrypted title")
        require("Verify live CLI plan encryption" in shown_text, "plans show did not render decrypted goal")
        require("encrypted_" not in shown_text, "plans show leaked encrypted fields")

        status = run_cli_json(["plans", "status", short_id])["plan"]
        require(status["title"] == title, "plans status did not resolve/decrypt plan")

        edited = run_cli_json([
            "plans",
            "edit",
            short_id,
            "--title",
            edited_title,
            "--summary",
            "Edited real local API smoke",
        ])["plan"]
        require(edited["title"] == edited_title, "plans edit did not update/decrypt title")
        require(edited["summary"] == "Edited real local API smoke", "plans edit did not update/decrypt summary")

        goal_updated = run_cli_json(["plans", "goal", "set", short_id, "--text", "Updated live CLI goal"])["plan"]
        require(goal_updated["goal"] == "Updated live CLI goal", "plans goal set did not update/decrypt goal")

        learning = run_cli_json([
            "plans",
            "learnings",
            "add",
            short_id,
            "--title",
            "Finalize smoke learning",
            "--status",
            "accepted",
            "--task-draft",
            "Keep plan completion gates covered by live CLI smoke.",
        ])["learning"]
        require(learning["title"] == "Finalize smoke learning", "plans learning add did not decrypt title")
        require(learning["status"] == "accepted", "plans learning add did not persist accepted status")
        require("encrypted_" not in json.dumps(learning), "plans learning add leaked encrypted fields")

        completed = run_cli_json(["plans", "complete", short_id])["plan"]
        require(completed["status"] == "completed", "plans complete did not set completed status")
        require(completed["completed_at"] is not None, "plans complete did not set completed_at")

        ask_result = run_cli_json(["plans", "ask", ask_title])
        require("encrypted_" not in json.dumps(ask_result), "plans ask leaked encrypted fields")
        after_ask = run_cli_json(["plans", "list"])["plans"]
        ask_plan = find_plan_by_title(after_ask, ask_title)
        require(ask_plan is not None, "plans ask did not create a readable plan")
        ask_plan_id = str(ask_plan["plan_id"])
        ask_short_id = str(ask_plan["short_id"])

        archived_ask = run_cli_json(["plans", "archive", ask_short_id])["plan"]
        require(archived_ask["status"] == "archived", "plans archive did not archive ask-created plan")
        ask_plan_id = ""
        ask_short_id = ""

        archived = run_cli_json(["plans", "archive", short_id])["plan"]
        require(archived["status"] == "archived", "plans archive did not archive created plan")
        require("encrypted_" not in json.dumps(archived), "plans archive leaked encrypted fields")
        plan_id = ""
        short_id = ""
    finally:
        if ask_short_id:
            archive_plan(ask_short_id)
        elif ask_plan_id:
            archive_plan(ask_plan_id)
        if short_id:
            archive_plan(short_id)
        elif plan_id:
            archive_plan(plan_id)

    print(json.dumps({"success": True, "api_url": args.api_url, "commands": "real-cli-local-api"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
