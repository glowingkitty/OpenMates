"""Rate-limited read access to authoritative OpenMates Tasks via the global CLI.

The installed ``openmates`` CLI owns encryption, task storage and the activity
outbox; this module only invokes ``openmates tasks <args> --json`` behind one
host-wide request slot and a shared HTTP429/transport cooldown. It is used by
the daily meeting collector and is never an alternate task ledger.
"""

from __future__ import annotations
import json
from pathlib import Path
import subprocess
import time


class TaskDeliveryDeferred(RuntimeError):
    """Shared admission refused a request; durable outcomes must remain pending."""


RATE_LIMIT_COOLDOWN_SECONDS = 120
MAX_RATE_LIMIT_COOLDOWN_SECONDS = 1800
TRANSPORT_COOLDOWN_SECONDS = 30
_INVOCATION_READS = {}


def cli(root, args):
    # One host-wide metadata-only gate protects every chat without sharing account
    # data. The global executable retains its caller's exact authentication context.
    import fcntl
    import re

    directory = Path(root) / "logs/openmates-task-reader"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = directory / "request-backoff.json"
    key = (str(root), tuple(args))
    with (directory / "request.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TaskDeliveryDeferred("Task delivery deferred: another chat owns the global CLI request slot; no request sent") from exc
        try:
            state = json.loads(state_path.read_text())
        except FileNotFoundError:
            state = {}
        now = time.time()
        if now < state.get("retry_at", 0):
            raise TaskDeliveryDeferred(
                f"Task delivery deferred until UTC epoch {state['retry_at']:.0f}; shared API cooldown, no request sent"
            )
        # Reuse identical list reads within one process only. Never cache across
        # processes/accounts or reuse reads after a mutation.
        if args[0] == "list" and key in _INVOCATION_READS:
            return _INVOCATION_READS[key]
        if args[0] != "list":
            _INVOCATION_READS.clear()
        try:
            result = subprocess.run(
                ["openmates", "tasks", *args, "--json"], cwd=root,
                capture_output=True, text=True, timeout=20,
            )
        except subprocess.TimeoutExpired as exc:
            state_path.write_text(json.dumps({**state, "retry_at": time.time() + TRANSPORT_COOLDOWN_SECONDS}))
            raise TaskDeliveryDeferred("Global openmates timed out; outcome retained, reconcile the existing outbox after shared cooldown") from exc
        if result.returncode:
            error = result.stderr.strip()
            if re.search(r"(?<!\d)429(?!\d)", error):
                failures = min(state.get("rate_limit_failures", 0) + 1, 5)
                # Current global CLI errors omit HTTP headers. Honor Retry-After
                # seconds when exposed, otherwise use conservative exponential delay.
                retry = re.search(r"retry-after[\s:=]+(\d+)", error, re.I)
                delay = max(int(retry.group(1)) if retry else 0,
                            min(RATE_LIMIT_COOLDOWN_SECONDS * 2 ** (failures - 1), MAX_RATE_LIMIT_COOLDOWN_SECONDS))
                retry_at = time.time() + delay
                state_path.write_text(json.dumps({"retry_at": retry_at, "rate_limit_failures": failures}))
                raise TaskDeliveryDeferred(f"Task API HTTP429; delivery deferred until UTC epoch {retry_at:.0f}. Pending outcome retained; no automatic network retry")
            raise RuntimeError("Global openmates failed: " + error)
        response = json.loads(result.stdout)
        state_path.write_text(json.dumps({"retry_at": 0, "rate_limit_failures": 0}))
        if args[0] == "list":
            _INVOCATION_READS[key] = response
        return response
