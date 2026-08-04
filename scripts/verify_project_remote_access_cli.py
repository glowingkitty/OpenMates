#!/usr/bin/env python3
"""Verify one real source CLI and one real requester CLI against dev.

The verifier uses independently authenticated same-account homes, runs Personal
and Team source fixtures, and invokes production projects files list/search/read.
It records only opaque IDs/counts and never prints remote plaintext or credentials.
Run only after the TASK-4 implementation is deployed to the dev API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from verify_project_remote_access_api import CLI_DIR, ROOT, login_session, run


LIVE_SCRIPT = [
    "node",
    "--experimental-strip-types",
    "--loader",
    "./frontend/packages/openmates-cli/tests/loader.mjs",
    "scripts/project_remote_access_live.mjs",
]
BACKEND_DENIAL_COVERAGE = {
    "cross_account_denial": "backend/tests/test_project_remote_access_bridge.py::test_cross_user_project_and_expired_session_requests_fail_closed",
    "removed_member_denial": "backend/tests/test_project_remote_access_bridge.py::test_team_heartbeat_membership_failure_revokes_session_and_offlines_sources",
}
EXPECTED_LIST_PATH = "src"
EXPECTED_MATCH_PATH = "src/remote-demo.ts"
EXPECTED_READ_MARKER = "OpenMates live remote preview"
SOURCE_EVENT_TIMEOUT_SECONDS = 30
CHILD_STOP_TIMEOUT_SECONDS = 30
STABLE_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def unavailable_account_probes() -> list[dict[str, str]]:
    return [
        {
            "probe": probe,
            "status": "not_run",
            "reason": "requires a separately approved second test account; only one approved account is configured",
            "backend_denial_coverage": coverage,
        }
        for probe, coverage in BACKEND_DENIAL_COVERAGE.items()
    ]


def _run_cli(
    home: Path,
    api_url: str,
    arguments: list[str],
    *,
    expected_error: str | None = None,
) -> dict[str, Any]:
    result = subprocess.run(
        ["node", "dist/cli.js", *arguments, "--api-url", api_url, "--json"],
        cwd=CLI_DIR,
        env={**os.environ, "HOME": str(home)},
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    error_code = _stable_error_code(result.stderr)
    if expected_error:
        if result.returncode == 0:
            raise RuntimeError("Requester CLI unexpectedly accepted a denied operation")
        if error_code != expected_error:
            raise RuntimeError(f"Requester CLI returned denial code: {error_code}")
        return {"error": {"code": expected_error}}
    if result.returncode != 0:
        raise RuntimeError(f"Requester CLI failed with code: {error_code}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Requester CLI returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Requester CLI returned a non-object JSON result")
    return payload


def _stable_error_code(stderr: str) -> str:
    for line in reversed(stderr.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and STABLE_ERROR_CODE_PATTERN.fullmatch(code):
            return code
    return "unknown_error"


def _readline_before(stream: Any, deadline: float) -> str | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        stream.fileno()
    except (AttributeError, OSError):
        return next(stream, None)
    readable, _, _ = select.select([stream], [], [], remaining)
    return stream.readline() if readable else None


def _wait_for_event(process: subprocess.Popen[str], event: str) -> dict[str, Any]:
    assert process.stdout is not None
    deadline = time.monotonic() + SOURCE_EVENT_TIMEOUT_SECONDS
    while (line := _readline_before(process.stdout, deadline)) is not None:
        if line == "":
            break
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == event:
            return payload
    if process.poll() is None:
        raise RuntimeError(f"Timed out waiting for source CLI event '{event}'")
    raise RuntimeError(f"Source CLI exited before event '{event}'")


def _wait_fixture(process: subprocess.Popen[str]) -> dict[str, Any]:
    return _wait_for_event(process, "fixture_ready")


def _wait_event(process: subprocess.Popen[str], event: str) -> None:
    _wait_for_event(process, event)


def _result(payload: dict[str, Any], operation: str) -> dict[str, Any]:
    if payload.get("operation") != operation or not isinstance(payload.get("result"), dict):
        raise RuntimeError(f"Requester CLI {operation} result was invalid")
    return payload["result"]


def _verify_context(api_url: str, host_home: Path, requester_home: Path, team: bool) -> dict[str, Any]:
    mode = "serve-team" if team else "serve"
    env = {**os.environ, "HOME": str(host_home), "OPENMATES_REMOTE_HOST_SESSION": str(host_home / ".openmates/session.json")}
    process = subprocess.Popen(
        [*LIVE_SCRIPT, mode, api_url],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        fixture = _wait_fixture(process)
        project_id = str(fixture["project_id"])
        source_id = str(fixture["source_id"])
        context = ["--team", str(fixture["team_id"])] if team else ["--personal"]
        listed = _run_cli(requester_home, api_url, ["projects", "files", "list", project_id, "--source", source_id, *context])
        searched = _run_cli(requester_home, api_url, ["projects", "files", "search", project_id, "OpenMates", "--source", source_id, *context])
        read = _run_cli(requester_home, api_url, ["projects", "files", "read", project_id, "src/remote-demo.ts", "--source", source_id, *context])
        list_result = _result(listed, "list")
        entries = list_result.get("entries")
        if not isinstance(entries, list) or not any(
            isinstance(entry, dict) and entry.get("path") == EXPECTED_LIST_PATH for entry in entries
        ) or any(isinstance(entry, dict) and entry.get("path") == ".env" for entry in entries):
            raise RuntimeError("Requester CLI list result was invalid")
        search_result = _result(searched, "search")
        matches = search_result.get("matches")
        if not isinstance(matches, list) or not any(
            isinstance(match, dict)
            and str(match.get("path") or "").removeprefix("./") == EXPECTED_MATCH_PATH
            for match in matches
        ):
            raise RuntimeError("Requester CLI search result was invalid")
        read_result = _result(read, "read")
        if EXPECTED_READ_MARKER not in str(read_result.get("content") or ""):
            raise RuntimeError("Requester CLI read result was invalid")
        _run_cli(
            requester_home,
            api_url,
            ["projects", "files", "read", project_id, ".env", "--source", source_id, *context],
            expected_error="protected_path",
        )
        process.send_signal(signal.SIGUSR1)
        _wait_event(process, "bridge_stopped")
        _run_cli(
            requester_home,
            api_url,
            ["projects", "files", "list", project_id, "--source", source_id, *context],
            expected_error="source_offline",
        )
        return {
            "context": "team" if team else "personal",
            "checks": {
                "list_entry": 1,
                "search_match": 1,
                "read_content": 1,
                "protected_denial": 1,
                "offline_after_stop": 1,
            },
            "status": "passed",
        }
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=CHILD_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=CHILD_STOP_TIMEOUT_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify production two-CLI Project remote access.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--two-cli", action="store_true", required=True)
    parser.add_argument("--personal-and-team", action="store_true", required=True)
    args = parser.parse_args()
    if not args.skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR)
    with tempfile.TemporaryDirectory(prefix="openmates-cli-host-") as host_value, tempfile.TemporaryDirectory(prefix="openmates-cli-requester-") as requester_value:
        host_home = Path(host_value)
        requester_home = Path(requester_value)
        login_session(args.api_url, args.slot, host_home, "project-cli-host")
        login_session(args.api_url, args.slot, requester_home, "project-cli-requester")
        results = [_verify_context(args.api_url, host_home, requester_home, False)]
        # The foreground CLI secures the test helper's plaintext session on first use.
        # Refresh it before the isolated fixture loader starts the Team context.
        login_session(args.api_url, args.slot, host_home, "project-cli-host")
        results.append(_verify_context(args.api_url, host_home, requester_home, True))
    probes = unavailable_account_probes()
    print(json.dumps({"success": True, "api_url": args.api_url, "results": results, "probes": probes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
