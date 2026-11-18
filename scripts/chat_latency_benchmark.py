#!/usr/bin/env python3
"""Chat latency benchmark for the OpenMates DEV stack.

Sends a fixed question set (8 simple, 4 complex) as new chats through the
installed ``openmates`` CLI with automatic model routing, sequentially and 3 s
apart, and records per question: chat id, UTC send time, CLI duration, the
assistant model when the --json output exposes it, and exit status. Used for
before/after comparison of latency changes. Never targets production; the
account comes from ``dev_test_account`` and is always released in ``finally``.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = "/tmp/claude-1001/-home-superdev-projects-OpenMates/0fa759b6-56e3-430f-a36a-58e40fa369db/scratchpad/logs"
SIMPLE = [
    "What is the capital of Portugal?", "How many minutes are in a day?", "Give me a synonym for happy.",
    "What does HTTP stand for?", "Hi! How are you today?", "Convert 10 kilometers to miles.",
    "Who wrote Romeo and Juliet?", "What's a good name for a goldfish?",
]
COMPLEX = [
    "Compare the trade-offs of PostgreSQL and MongoDB for an event-sourcing system with 50k writes per second.",
    "Write a Python function that merges overlapping intervals and explain its time complexity.",
    "Explain how mRNA vaccines train the immune system, step by step, for a high-school student.",
    "Plan a 3-day Lisbon itinerary for a family with two kids, including rainy-day options.",
]
MODEL_KEYS = ("model", "modelName", "model_name", "assistantModel", "model_id")


def find_model(data: object) -> str | None:
    """Depth-first search of the CLI JSON for a model field."""
    if isinstance(data, dict):
        for key in MODEL_KEYS:
            if isinstance(data.get(key), str) and data[key]:
                return data[key]
        children = list(data.values())
    elif isinstance(data, list):
        children = data
    else:
        return None
    for child in children:
        found = find_model(child)
        if found:
            return found
    return None


def run_cli(cli: str, args: list[str], api_url: str, env: dict[str, str], timeout: int) -> tuple[int, object, str]:
    try:
        proc = subprocess.run([cli, *args, "--api-url", api_url, "--json"], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, None, "timeout"
    try:
        parsed = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        parsed = None
    return proc.returncode, parsed, proc.stderr.strip()[-300:]


def benchmark(args: argparse.Namespace, cli: str, api_url: str, env: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    questions = [("simple", q) for q in SIMPLE] + [("complex", q) for q in COMPLEX]
    for round_no in range(1, args.rounds + 1):
        for kind, question in questions:
            sent_at = datetime.now(UTC).isoformat(timespec="milliseconds")
            started = time.monotonic()
            status, data, err = run_cli(cli, ["chats", "new", question, "--personal"], api_url, env, args.timeout)
            duration = round(time.monotonic() - started, 3)
            chat_id = data.get("chatId") if isinstance(data, dict) else None
            rows.append({"round": round_no, "kind": kind, "question": question, "chat_id": chat_id,
                         "sent_at_utc": sent_at, "cli_duration_s": duration, "model": find_model(data),
                         "exit_status": status, "error": err if status else None})
            print(f"{kind:7} {duration:7.2f}s exit={status} model={rows[-1]['model']} chat={chat_id}", flush=True)
            time.sleep(3)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--output")
    parser.add_argument("--keep", action="store_true", help="keep the created chats")
    parser.add_argument("--session", default="59b6")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    output = Path(args.output or f"{SCRATCH}/chat_bench_{args.label}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    cli = shutil.which("openmates")
    if not cli:
        parser.error("installed openmates executable missing")

    import dev_test_account
    from workflow_schedule_real_test import API_URL

    account = dev_test_account.acquire_real_test_account(
        "chat-latency", args.session, "chat-latency", stack_timeout=300, allow_throwaway=True)
    rows: list[dict] = []
    deleted: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="chat-bench-") as state:
            env = {**os.environ, **account.environment, "OPENMATES_STATE_DIR": state, "OPENMATES_PROFILE": ""}
            for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
                env.pop(key, None)
            login = subprocess.run(
                ["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login", "--slot", "",
                 "--api-url", API_URL], cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=180)
            if login.returncode:
                print("login failed", file=sys.stderr)
                return 1
            rows = benchmark(args, cli, API_URL, env)
            ids = [r["chat_id"] for r in rows if r["chat_id"]]
            if ids and not args.keep:
                status, _, err = run_cli(cli, ["chats", "delete", *ids, "--yes"], API_URL, env, 180)
                if status == 0:
                    deleted = ids
                else:
                    print(f"chat delete failed: {err}", file=sys.stderr)
    finally:
        receipt = dev_test_account.finish_real_test_account(account)
        output.write_text(json.dumps({
            "label": args.label, "api_url": API_URL, "rounds": args.rounds, "account_kind": account.kind,
            "finished_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "results": rows, "deleted_chats": deleted, "account_receipt_kind": receipt.get("kind")}, indent=2))
    print(f"wrote {output}")
    return 0 if rows and all(r["exit_status"] == 0 for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
