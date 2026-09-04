#!/usr/bin/env python3
"""Run test-account CLI automation without touching the personal CLI session.

The wrapper reserves one normal Playwright account lane in the shared test
control plane, creates a disposable HOME, and runs the existing credential-safe
Node helper. Credentials remain in environment/.env handling owned by that
helper and are never printed or persisted outside the temporary home.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

try:
    from scripts import sessions as session_control
except ModuleNotFoundError:
    import sessions as session_control


ROOT = Path(__file__).resolve().parents[1]
NORMAL_ACCOUNT_SLOTS = tuple(range(1, 14))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Owning sessions.py session ID")
    parser.add_argument("--slot", type=int, choices=NORMAL_ACCOUNT_SLOTS)
    parser.add_argument("helper_args", nargs=argparse.REMAINDER)
    return parser.parse_args()


def _acquire_account(owner: str, requested_slot: int | None) -> tuple[str, int, set[str]]:
    candidates = (requested_slot,) if requested_slot else NORMAL_ACCOUNT_SLOTS
    for slot in candidates:
        lease_id = f"test-account-cli-{slot}-{uuid.uuid4().hex[:10]}"
        resources = {f"playwright-account:{slot}"}
        try:
            session_control.acquire_test_resource_lease(
                lease_id,
                owner,
                resources,
                timeout=0,
                poll=1,
                mode="exclusive",
            )
        except RuntimeError:
            continue
        return lease_id, slot, resources
    raise RuntimeError("No normal test-account lane is currently available")


def main() -> int:
    args = _parse_args()
    helper_args = list(args.helper_args)
    if helper_args[:1] == ["--"]:
        helper_args = helper_args[1:]
    if not helper_args:
        raise RuntimeError("Missing openmates_cli_test_account.mjs arguments")

    owner = f"opencode-session-{args.session}"
    lease_id, slot, resources = _acquire_account(owner, args.slot)
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(session_control.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
            session_control.renew_test_resource_lease(lease_id, owner, resources, mode="exclusive")

    heartbeat = threading.Thread(target=renew, name="test-account-cli-lease", daemon=True)
    heartbeat.start()
    try:
        with tempfile.TemporaryDirectory(prefix=f"openmates-test-account-{slot}-") as temp_home:
            env = {
                **os.environ,
                "HOME": temp_home,
                "USERPROFILE": temp_home,
                "OPENMATES_TEST_ACCOUNT_SOURCE_SLOT": str(slot),
            }
            result = subprocess.run(
                ["node", "scripts/openmates_cli_test_account.mjs", *helper_args, "--slot", str(slot)],
                cwd=ROOT,
                env=env,
                check=False,
            )
            return result.returncode
    finally:
        stop.set()
        heartbeat.join(timeout=1)
        session_control.release_test_resource_lease(lease_id)


if __name__ == "__main__":
    raise SystemExit(main())
