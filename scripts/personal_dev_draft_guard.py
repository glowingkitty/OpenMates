#!/usr/bin/env python3
"""Fail personal-dev real-account runs that leave drafts behind.

Real-inference and browser runs on the shared dev stack use the personal dev
test account. A run that leaves a draft (an unsent composer, an app-inserted
mention, an unsent embed) pollutes that account for every later run and for
the person who uses it. Take a baseline right after login, then check again
after the run's own cleanup: any draft on a chat that had none before is a
failure. Only chat ids are reported; draft plaintext never leaves the CLI.

Library use (Python harnesses):
    guard = DraftGuard.start(cli)          # after login
    ...run and clean up owned chats...
    leftovers = guard.leftovers()          # [] when clean

Command use (Playwright or manual runs, with the run's CLI state active):
    personal_dev_draft_guard.py snapshot --output baseline.json --cli openmates
    personal_dev_draft_guard.py check --baseline baseline.json --cli openmates
`check` exits 1 and lists the leftover chat ids when the run left drafts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

API_URL = "https://api.dev.openmates.org"
ROOT = Path(__file__).resolve().parents[1]


class DraftGuardError(RuntimeError):
    """The draft inventory could not be read, so the run cannot be called clean."""


def parse_draft_chat_ids(payload: object) -> set[str]:
    """Extract chat ids from `openmates drafts list --json` output."""
    drafts = payload.get("drafts") if isinstance(payload, dict) else None
    if not isinstance(drafts, list):
        raise DraftGuardError("draft_list_shape_invalid")
    ids: set[str] = set()
    for draft in drafts:
        chat_id = draft.get("chatId") if isinstance(draft, dict) else None
        if not isinstance(chat_id, str) or not chat_id:
            raise DraftGuardError("draft_list_entry_without_chat_id")
        ids.add(chat_id)
    return ids


def list_draft_chat_ids(
    cli: str, *, api_url: str = API_URL, env: dict[str, str] | None = None, timeout: int = 120,
) -> set[str]:
    """Read the account's current drafts from the server through the CLI.

    `env` selects the run's isolated CLI state (OPENMATES_STATE_DIR); the
    process environment is used when it is omitted.
    """
    try:
        result = subprocess.run(
            [cli, "drafts", "list", "--refresh", "--api-url", api_url, "--json"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DraftGuardError("draft_list_timeout") from exc
    if result.returncode:
        raise DraftGuardError("draft_list_failed")
    try:
        return parse_draft_chat_ids(json.loads(result.stdout))
    except json.JSONDecodeError as exc:
        raise DraftGuardError("draft_list_json_invalid") from exc


def leftover_drafts(baseline: Iterable[str], current: Iterable[str]) -> list[str]:
    """Drafts present now on chats that had no draft at the baseline."""
    return sorted(set(current) - set(baseline))


@dataclass(frozen=True)
class DraftGuard:
    """A baseline of the account's draft chat ids, taken right after login."""

    baseline: frozenset[str]
    read: Callable[[], set[str]]

    @classmethod
    def start(cls, cli: str, *, api_url: str = API_URL, env: dict[str, str] | None = None) -> "DraftGuard":
        def read() -> set[str]:
            return list_draft_chat_ids(cli, api_url=api_url, env=env)
        return cls(frozenset(read()), read)

    def leftovers(self) -> list[str]:
        return leftover_drafts(self.baseline, self.read())


def record_leftovers(receipt: dict, guard: DraftGuard | None) -> None:
    """Add the guard result to a run receipt; leftovers or an unreadable inventory fail the run."""
    if guard is None:
        return
    try:
        leftovers = guard.leftovers()
    except DraftGuardError as exc:
        receipt.setdefault("cleanup", {})["drafts"] = "check_failed"
        receipt["leftover_drafts_error"] = str(exc)
        receipt["status"] = "failed"
        return
    receipt.setdefault("cleanup", {})["drafts"] = "clean" if not leftovers else "leftover"
    if leftovers:
        receipt["leftover_draft_chat_ids"] = leftovers
        receipt["status"] = "failed"
        receipt.setdefault("error_code", "leftover_drafts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("snapshot", "check"):
        action = sub.add_parser(name)
        action.add_argument("--cli", default="openmates")
        action.add_argument("--api-url", default=API_URL)
    sub.choices["snapshot"].add_argument("--output", type=Path, required=True)
    sub.choices["check"].add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        current = list_draft_chat_ids(args.cli, api_url=args.api_url)
        if args.action == "snapshot":
            args.output.write_text(json.dumps({"draft_chat_ids": sorted(current)}) + "\n")
            print(f"Draft baseline: {len(current)} draft(s).")
            return 0
        baseline = json.loads(args.baseline.read_text()).get("draft_chat_ids")
        if not isinstance(baseline, list):
            raise DraftGuardError("baseline_invalid")
    except (DraftGuardError, OSError, json.JSONDecodeError) as exc:
        print(f"Draft guard could not read drafts: {exc}", file=sys.stderr)
        return 2
    leftovers = leftover_drafts(baseline, current)
    if leftovers:
        print(f"FAIL: the run left {len(leftovers)} draft(s) on chat(s): {', '.join(leftovers)}", file=sys.stderr)
        print("Clear them with `openmates drafts clear <chat-id>` and fix the run's cleanup.", file=sys.stderr)
        return 1
    print("No leftover drafts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
