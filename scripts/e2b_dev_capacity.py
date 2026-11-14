#!/usr/bin/env python3
"""Shared E2B capacity for developing OpenMates: concurrency cap, queue and daily budget.

Every E2B sandbox that dev tooling starts on this host (heavy_slot remote runs,
CI overflow) holds one slot from here first. Product usage of E2B (users' code
runs, browse sessions, spec-driven test runs) never goes through this module and
is not limited by it; the cap exists so that product usage always has room.

- Team limit: E2B Pro allows 100 concurrent sandboxes (https://e2b.dev/pricing).
  The API key cannot read the plan, so the tier was inferred on 2026-11-13: 41
  product sandboxes ran at once (Hobby allows 10) and sandbox timeouts above one
  hour are accepted (Hobby's maximum). An add-on raises the limit to 600 or 1,100.
- Dev share: dev jobs may hold at most DEV_SHARE (70%) of the team limit; the
  remaining 30% stays free for product usage. A dev job that finds the share
  used up waits in line for a slot instead of running on the dev server.
- Daily budget: $100/day (owner decision 2026-11-14; reviewed with the remaining
  credits every 14 days). When today's estimated dev E2B spend reaches it, new dev
  runs are refused (callers fall back to the local queue and say so).
- Credits: `e2b_credits.py` shows the daily spend, the (estimated) credit balance
  and the runway, and sends a "Feedback needed" push when the runway drops below
  30 days; it is checked after every recorded run.

Override without a deploy: write `{"team_concurrency_limit": 600}` (any of
the keys in DEFAULTS) to `<state dir>/e2b-dev-capacity.json`, or set
OPENMATES_E2B_TEAM_LIMIT / OPENMATES_E2B_DEV_SHARE / OPENMATES_E2B_DAILY_BUDGET_USD.

Standard library only (imported by heavy_slot.py under the system python).

Usage:
  python3 scripts/e2b_dev_capacity.py status
  python3 scripts/e2b_credits.py          # spend, credit balance estimate, runway
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_load_guard  # noqa: E402 - sibling module; path set up above for direct-file loading

# E2B published usage prices (https://e2b.dev/pricing, checked 2026-11-13).
USD_PER_VCPU_SECOND = 0.000014
USD_PER_GIB_SECOND = 0.0000045

DEFAULTS = {
    "team_concurrency_limit": 100,  # E2B Pro plan
    "dev_share": 0.70,
    "daily_budget_usd": 100.0,
}
ENV_OVERRIDES = {
    "team_concurrency_limit": ("OPENMATES_E2B_TEAM_LIMIT", int),
    "dev_share": ("OPENMATES_E2B_DEV_SHARE", float),
    "daily_budget_usd": ("OPENMATES_E2B_DAILY_BUDGET_USD", float),
}
POLL_SECONDS = 5


def run_cost_usd(seconds: float, cpus: int, memory_mb: int) -> float:
    """Estimated E2B cost of one sandbox kept for `seconds` at the given size."""
    return seconds * (cpus * USD_PER_VCPU_SECOND + memory_mb / 1024 * USD_PER_GIB_SECOND)


@dataclass(frozen=True)
class Settings:
    team_concurrency_limit: int
    dev_share: float
    daily_budget_usd: float

    @property
    def dev_slots(self) -> int:
        return max(1, math.floor(self.team_concurrency_limit * self.dev_share))


def capacity_dir() -> Path:
    path = host_load_guard.state_dir() / "e2b-dev"
    path.mkdir(parents=True, exist_ok=True)
    return path


def override_file() -> Path:
    return host_load_guard.state_dir() / "e2b-dev-capacity.json"


def settings() -> Settings:
    values = dict(DEFAULTS)
    if override_file().exists():
        try:
            data = json.loads(override_file().read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"e2b_dev_capacity: unreadable {override_file()}: {exc}") from exc
        values.update({k: v for k, v in data.items() if k in DEFAULTS})
    for key, (name, cast) in ENV_OVERRIDES.items():
        if os.environ.get(name):
            values[key] = cast(os.environ[name])
    result = Settings(int(values["team_concurrency_limit"]), float(values["dev_share"]),
                      float(values["daily_budget_usd"]))
    if result.team_concurrency_limit < 1 or not 0 < result.dev_share <= 1 or result.daily_budget_usd < 0:
        raise SystemExit(f"e2b_dev_capacity: invalid settings {result}")
    return result


# --------------------------------------------------------------------------
# Daily spend ledger.
# --------------------------------------------------------------------------

def _ledger_path(day: str | None = None) -> Path:
    return capacity_dir() / f"spend-{day or time.strftime('%Y-%m-%d', time.gmtime())}.json"


def spent_today() -> dict:
    path = _ledger_path()
    if not path.exists():
        return {"usd": 0.0, "runs": 0, "seconds": 0.0}
    return json.loads(path.read_text())


def record_spend(seconds: float, cpus: int, memory_mb: int) -> float:
    """Add one finished sandbox to today's ledger; returns its estimated cost."""
    cost = run_cost_usd(seconds, cpus, memory_mb)
    path = _ledger_path()
    with (capacity_dir() / "ledger.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else {"usd": 0.0, "runs": 0, "seconds": 0.0}
        data = {"usd": round(data["usd"] + cost, 4), "runs": data["runs"] + 1,
                "seconds": round(data["seconds"] + seconds, 1)}
        path.write_text(json.dumps(data))
    check_runway()
    return cost

def check_runway() -> None:
    """Low-credit push after each run; a delivery problem is reported, never fails the run."""
    import e2b_credits  # cyclic sibling (it reads this ledger); imported at call time
    import agent_question

    try:
        e2b_credits.check()
    except agent_question.QuestionError as error:
        print(f"e2b_dev_capacity: low-runway warning not delivered: {error}", file=sys.stderr)


def budget_exhausted(config: Settings | None = None) -> str | None:
    config = config or settings()
    spent = spent_today()["usd"]
    if spent >= config.daily_budget_usd:
        return (f"today's dev E2B spend ${spent:.2f} reached the daily budget "
                f"${config.daily_budget_usd:.2f}")
    return None


# --------------------------------------------------------------------------
# Slots (one flock file per slot; held for the life of a sandbox).
# --------------------------------------------------------------------------

class Slot:
    """A held dev E2B slot. Release with `release()` or use as a context manager."""

    def __init__(self, fd: int, index: int):
        self.fd = fd
        self.index = index

    def release(self) -> None:
        if self.fd >= 0:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "Slot":
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def try_acquire(label: str, config: Settings | None = None) -> Slot | None:
    config = config or settings()
    directory = capacity_dir()
    for index in range(config.dev_slots):
        fd = os.open(directory / f"slot-{index}.lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({"label": label[:300], "pid": os.getpid(), "started": time.time()}).encode())
        return Slot(fd, index)
    return None


def acquire(label: str, timeout: float, announce=None) -> Slot | None:
    """Wait up to `timeout` seconds for a slot (the E2B queue). None on timeout."""
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        config = settings()
        slot = try_acquire(label, config)
        if slot is not None:
            return slot
        if time.monotonic() >= deadline:
            return None
        if announce and not announced:
            announce(f"all {config.dev_slots} dev E2B slots busy "
                     f"({config.dev_share:.0%} of {config.team_concurrency_limit}); waiting in the E2B queue")
            announced = True
        time.sleep(POLL_SECONDS)


def held_slots() -> list[dict]:
    result = []
    for path in sorted(capacity_dir().glob("slot-*.lock")):
        fd = os.open(path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                result.append(json.loads(path.read_text() or "{}"))
            except json.JSONDecodeError:
                result.append({"label": "?"})
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    return result


def status() -> dict:
    config = settings()
    held = held_slots()
    return {"team_concurrency_limit": config.team_concurrency_limit, "dev_share": config.dev_share,
            "dev_slots": config.dev_slots, "busy": len(held), "daily_budget_usd": config.daily_budget_usd,
            "spent_today": spent_today(), "running": held, "credits": _credits_summary()}

def _credits_summary() -> dict:
    import e2b_credits  # cyclic sibling; imported at call time

    data = e2b_credits.summary()
    return {"average_daily_dev_usd": data["average_daily_dev_usd"], "balance": data["balance"],
            "real_balance": data["real_balance"]}


if __name__ == "__main__":
    if sys.argv[1:] != ["status"]:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(status(), indent=2))
