#!/usr/bin/env python3
"""Emergency chat start for the owner: starts a chat whatever the running-chat slot limit says.

  python3 scripts/force_chat.py start --title "Fix the login bug" --prompt "..." [--model claude-opus-5-5]
  python3 scripts/force_chat.py pending     # start every queued chat (logs/claude-dispatch/pending) now

The normal paths queue a start when 20 chats run. This one skips that check (the launch
log records `forced`) and still applies the model rules (no Fable without --model naming it).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import claude_dispatch  # noqa: E402  (path set above)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="start one chat now")
    start.add_argument("--title", required=True)
    start.add_argument("--prompt", required=True)
    start.add_argument("--model", default=claude_dispatch.CLAUDE_MODEL)
    sub.add_parser("pending", help="start all queued chats now")
    args = parser.parse_args(argv)
    if args.command == "pending":
        for outcome in claude_dispatch.start_pending(limit=100, force=True):
            print(outcome)
        return 0
    explicit = args.model != claude_dispatch.CLAUDE_MODEL
    print(claude_dispatch.launch_claude_chat(args.title, args.prompt, model=args.model, explicit_model=explicit,
                                             force=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
