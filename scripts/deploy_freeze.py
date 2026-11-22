#!/usr/bin/env python3
"""Temporary dev deploy freeze (owner rule, receipt 91e24b7e4cf1b651, 2026-11-22).

While a freeze is active, nothing is deployed to dev: `sessions.py deploy` refuses at its
start, and the shared git pre-push hook (installed by `install-hook`) refuses every push
to `dev`, also from chats whose worktree still runs an older `sessions.py`. Pushes to other
branches (the dev->main release branch, `main`) are not affected.

A freeze starts at `starts_at` and lasts until it is cleared. Only the owner's go clears
it; `clear` records that go (receipt or quote).

State: <main checkout>/logs/deploy-freeze.json
  {"starts_at": ISO, "reason": str, "set_at": ISO, "cleared_at": ISO|null, "cleared_by": str|null}

Commands:
  status                                   Print the freeze and whether it is active now.
  set --from ISO --reason TEXT             Schedule (or start) a freeze.
  clear --approved-by "<receipt or quote>" End the freeze on the owner's go.
  check [--ref REF]                        Exit 1 with the reason while active (for hooks).
  install-hook                             Install the pre-push hook in the shared git dir.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FREEZE_NAME = "deploy-freeze.json"
HOOK_MARK = "# openmates deploy freeze (scripts/deploy_freeze.py)"


def main_root(start: Path | None = None) -> Path:
    """The main checkout (shared git dir's parent), also when run from a worktree."""
    start = start or Path(__file__).resolve().parent
    result = subprocess.run(["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).parent
    return Path(__file__).resolve().parents[1]


def state_path(root: Path | None = None) -> Path:
    override = os.environ.get("OPENMATES_DEPLOY_FREEZE_FILE")
    return Path(override) if override else (root or main_root()) / "logs" / FREEZE_NAME


def load(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or state_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(record: dict, path: Path | None = None) -> None:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def active_reason(now: datetime | None = None, record: dict | None = None) -> str:
    """'' when deploys may run, else the refusal text."""
    record = load() if record is None else record
    if not record.get("starts_at") or record.get("cleared_at"):
        return ""
    now = now or datetime.now(timezone.utc)
    try:
        starts = _parse(str(record["starts_at"]))
    except ValueError:
        return ""
    if now < starts:
        return ""
    return (f"Dev deploy freeze since {record['starts_at']}: {record.get('reason') or 'owner freeze'}. "
            "No deploy or push to dev until the owner gives the go and the freeze is cleared "
            "(python3 scripts/deploy_freeze.py status). Keep the work committed in your worktree or "
            "park it (worktree_wip.py park); do not ask the owner to lift it.")


def refuse_if_frozen() -> None:
    """sessions.py deploy calls this first."""
    reason = active_reason()
    if reason:
        print(f"Error: {reason}", file=sys.stderr)
        sys.exit(1)


def _hook_path() -> Path:
    result = subprocess.run(["git", "-C", str(main_root()), "rev-parse", "--path-format=absolute",
                             "--git-common-dir"], capture_output=True, text=True, check=True)
    return Path(result.stdout.strip()) / "hooks" / "pre-push"


HOOK = f"""#!/usr/bin/env bash
{HOOK_MARK}
# Refuses pushes to dev while logs/deploy-freeze.json holds an active freeze.
script="$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/deploy_freeze.py"
[ -f "$script" ] || exit 0
while read -r local_ref local_sha remote_ref remote_sha; do
  if [ "$remote_ref" = "refs/heads/dev" ]; then
    python3 "$script" check --ref "$remote_ref" || exit 1
  fi
done
exit 0
"""


def install_hook() -> str:
    path = _hook_path()
    if path.exists() and HOOK_MARK not in path.read_text(encoding="utf-8", errors="replace"):
        raise SystemExit(f"{path} exists and is not ours; add the freeze check to it by hand")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HOOK, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p_set = sub.add_parser("set")
    p_set.add_argument("--from", dest="starts_at", required=True, help="ISO time, e.g. 2026-11-23T08:00:00+01:00")
    p_set.add_argument("--reason", required=True)
    p_clear = sub.add_parser("clear")
    p_clear.add_argument("--approved-by", required=True, help="the owner's go: receipt id or quote")
    p_check = sub.add_parser("check")
    p_check.add_argument("--ref", default="")
    sub.add_parser("install-hook")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    if args.command == "set":
        _save({"starts_at": _parse(args.starts_at).isoformat(), "reason": args.reason,
               "set_at": now.isoformat(timespec="seconds"), "cleared_at": None, "cleared_by": None})
    elif args.command == "clear":
        record = load()
        if not record:
            print("no freeze recorded")
            return 0
        record.update({"cleared_at": now.isoformat(timespec="seconds"), "cleared_by": args.approved_by})
        _save(record)
    elif args.command == "check":
        reason = active_reason(now)
        if reason:
            print(f"deploy freeze: push to {args.ref or 'dev'} refused. {reason}", file=sys.stderr)
            return 1
        return 0
    elif args.command == "install-hook":
        print(f"installed {install_hook()}")
        return 0
    record = load()
    print(json.dumps({**record, "active_now": bool(active_reason(now, record))}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
