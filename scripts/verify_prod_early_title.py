#!/usr/bin/env python3
"""Post-deploy check: production runs chat recovery epoch 1 and early chat titles.

Run after a production server update and after one signed-in chat message was
sent on production (guest chats never use recovery). Needs an open prod SSH
session (`scripts/prod-ssh.sh open`); every remote command is read-only.

Checks:
- cutover_state: the authoritative recovery state is epoch 1 with sends open;
- cutover_logged: the API startup task logged the activation (or found it active);
- recovery_enqueue: the API enqueued recovery-backed inference since the update;
- early_title: the AI worker produced an early chat title since the update.

Usage:
  python3 scripts/verify_prod_early_title.py --since 2026-11-20T10:00:00Z
Exit code 0 when every check passes, 2 otherwise; JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD_SSH = ROOT / "scripts" / "prod-ssh.sh"

STATE_PROGRAM = """
import asyncio, json
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController

async def main():
    cache = CacheService()
    state = await ChatRecoveryCutoverController(cache, DirectusService(cache_service=cache)).get_state(authoritative=True)
    print(json.dumps({key: state.get(key) for key in ("protocol_epoch", "sends_paused", "legacy_in_flight")}))

asyncio.run(main())
"""

CUTOVER_MARKERS = (
    "[RecoveryCutover] activated protocol epoch 1",
    "[RecoveryCutover] protocol epoch 1 already active",
)
ENQUEUE_MARKER = "enqueue_inference"
EARLY_TITLE_MARKER = "Early chat metadata ready"


def remote_commands(since: str) -> dict[str, str]:
    """Read-only commands run on the production host."""
    quoted_since = shlex.quote(since)
    return {
        "state": f"docker exec api python -c {shlex.quote(STATE_PROGRAM)}",
        "api_logs": f"docker logs api --since {quoted_since} 2>&1",
        "worker_logs": f"docker logs app-ai-worker --since {quoted_since} 2>&1",
    }


def evaluate(state_output: str, api_logs: str, worker_logs: str) -> dict[str, object]:
    """Turn the raw remote outputs into named pass/fail checks."""
    try:
        state = json.loads(state_output.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        state = {}
    checks = [
        {
            "check": "cutover_state",
            "passed": state.get("protocol_epoch") == 1 and state.get("sends_paused") is False,
            "detail": state or "state unreadable",
        },
        {
            "check": "cutover_logged",
            "passed": any(marker in api_logs for marker in CUTOVER_MARKERS),
            "detail": "API startup cutover task log line",
        },
        {
            "check": "recovery_enqueue",
            "passed": api_logs.count(ENQUEUE_MARKER) > 0,
            "detail": f"{api_logs.count(ENQUEUE_MARKER)} recovery enqueue log line(s)",
        },
        {
            "check": "early_title",
            "passed": worker_logs.count(EARLY_TITLE_MARKER) > 0,
            "detail": f"{worker_logs.count(EARLY_TITLE_MARKER)} early chat title log line(s)",
        },
    ]
    return {"checks": checks, "passed": all(check["passed"] for check in checks)}


def run_remote(command: str) -> str:
    completed = subprocess.run(
        [str(PROD_SSH), command], capture_output=True, text=True, timeout=180, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"prod-ssh command failed ({completed.returncode}): {completed.stderr.strip()[:300]}")
    return completed.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", required=True, help="Update start time (RFC 3339), e.g. 2026-11-20T10:00:00Z")
    args = parser.parse_args(argv)
    commands = remote_commands(args.since)
    result = evaluate(
        run_remote(commands["state"]), run_remote(commands["api_logs"]), run_remote(commands["worker_logs"]),
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
