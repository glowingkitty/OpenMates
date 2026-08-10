#!/usr/bin/env python3
"""Verify deterministic Personal and Team Project CLI CRUD against dev.

The script invokes the compiled production binary, requires an owner/admin Team
for Team mutation checks, and removes every created Project with exact confirmed
commands. Output contains only IDs and operation status, never encrypted fields.
Run only after the TASK-4 implementation is deployed to the dev API.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from verify_project_remote_access_api import CLI_DIR, login_session, run


def _cli(home: Path, api_url: str, arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["node", "dist/cli.js", *arguments, "--api-url", api_url, "--json"],
        cwd=CLI_DIR,
        env={**os.environ, "HOME": str(home)},
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Project CLI failed for {arguments[:2]}: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("Project CLI returned non-object JSON")
    return payload


def _exercise(home: Path, api_url: str, context: list[str], label: str) -> dict[str, Any]:
    created = _cli(home, api_url, ["projects", "create", f"CLI verification {label}", "--description", "bounded verifier", *context])
    project = created.get("project") or {}
    project_id = str(project.get("project_id") or "")
    if not project_id:
        raise RuntimeError("Project create did not return project_id")
    try:
        _cli(home, api_url, ["projects", "list", "--include-archived", *context])
        _cli(home, api_url, ["projects", "show", project_id, *context])
        _cli(home, api_url, ["projects", "open", project_id, *context])
        _cli(home, api_url, ["projects", "update", project_id, "--name", f"CLI verification updated {label}", *context])
        _cli(home, api_url, ["projects", "archive", project_id, *context])
        _cli(home, api_url, ["projects", "unarchive", project_id, *context])
        _cli(home, api_url, ["projects", "items", "list", project_id, *context])
        _cli(home, api_url, ["projects", "sources", "list", project_id, *context])
    finally:
        _cli(home, api_url, ["projects", "delete", project_id, "--confirm", project_id, *context])
    return {"context": label, "operations": ["list", "show", "open", "create", "update", "archive", "unarchive", "delete", "items", "sources"], "status": "passed"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify deterministic Project CLI CRUD.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--personal-and-team", action="store_true", required=True)
    args = parser.parse_args()
    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR)
    with tempfile.TemporaryDirectory(prefix="openmates-projects-cli-") as home_value:
        home = Path(home_value)
        login_session(args.api_url, args.slot, home, "projects-cli-verifier")
        teams = _cli(home, args.api_url, ["teams", "list"]).get("teams") or []
        writable = next((team for team in teams if team.get("role") in {"owner", "admin"}), None)
        if not writable or not writable.get("team_id"):
            raise RuntimeError("No owner/admin Team is available for Team Project CLI verification")
        results = [
            _exercise(home, args.api_url, ["--personal"], "personal"),
            _exercise(home, args.api_url, ["--team", str(writable["team_id"])], "team"),
        ]
    print(json.dumps({"success": True, "api_url": args.api_url, "results": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
