#!/usr/bin/env python3
# contract-test-file: infrastructure
"""List (dry run) or delete leftovers of the agentic cloud Project web proof.

  python3 scripts/agentic_cloud_project_cleanup.py --session ID
  python3 scripts/agentic_cloud_project_cleanup.py --session ID --delete --ids ID1,ID2

Uses the personal dev test account through the same lease and isolated CLI home
as the other real tests. A candidate is a Project created on or after the proof
work began whose name mentions the recipe app, or a chat created then that sits
in a candidate Project or whose title mentions the recipe app. --delete removes
exactly the listed ids and only when they are candidates. Never prints secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from verify_chat_sidebar_title_live import safe_failure
from workflow_schedule_real_test import API_URL, ProofError
import dev_test_account

ROOT = Path(__file__).resolve().parents[1]
SINCE = datetime(2026, 11, 14, tzinfo=UTC)
WORDING = re.compile(r"recipe", re.IGNORECASE)


def cli_json(cli: str, args: list[str]) -> object:
    result = subprocess.run([cli, *args, "--api-url", API_URL, "--json"], cwd=ROOT,
                            capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise ProofError(f"cli_{args[0]}_{args[1]}_failed: {safe_failure(result.stderr)}")
    return json.loads(result.stdout)


def items(payload: object, *keys: str) -> list[dict]:
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), list):
                return payload[key]
        return []
    return payload if isinstance(payload, list) else []


def pick(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (str, int)) and value != "":
            return str(value)
    return ""


def created_at(row: dict) -> datetime | None:
    raw = pick(row, "created_at", "createdAt", "created")
    if raw.isdigit():
        number = int(raw)
        return datetime.fromtimestamp(number / 1000 if number > 10**11 else number, UTC)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def collect(cli: str, verified: frozenset[str] = frozenset()) -> tuple[list[dict], list[dict], list[str]]:
    """Return (candidates, excluded recipe-like items, notes)."""
    projects = items(cli_json(cli, ["projects", "list", "--personal"]), "projects", "items")
    chats: list[dict] = []
    for page in range(1, 21):
        batch = items(cli_json(cli, ["chats", "list", "--limit", "100", "--page", str(page), "--personal"]), "chats", "items")
        chats.extend(batch)
        if len(batch) < 100:
            break
    candidates, excluded = [], []
    project_ids: set[str] = set()
    for row in projects:
        pid, name, when = pick(row, "project_id", "id"), pick(row, "name", "title"), created_at(row)
        entry = {"id": pid, "kind": "project", "title": name, "created": when.isoformat() if when else "unknown"}
        if not WORDING.search(name):
            continue
        # The CLI Project list carries no creation time; an operator may name
        # recipe Projects whose creation date they checked elsewhere.
        if (when and when >= SINCE) or pid in verified:
            candidates.append(entry if when else {**entry, "created": "verified by operator"})
            project_ids.add(pid)
        else:
            excluded.append({**entry, "why": "created before 2026-11-14 or creation time unknown"})
    for row in chats:
        cid, title, when = pick(row, "id", "chat_id"), pick(row, "title", "name"), created_at(row)
        in_project = pick(row, "project_id", "projectId") in project_ids
        entry = {"id": cid, "kind": "chat", "title": title or "(untitled)", "created": when.isoformat() if when else "unknown"}
        if not (in_project or WORDING.search(title)):
            continue
        if when and when >= SINCE:
            candidates.append(entry)
        else:
            excluded.append({**entry, "why": "created before 2026-11-14 or creation time unknown"})
    return candidates, excluded, [f"{len(projects)} projects and {len(chats)} chats listed"]


def delete(cli: str, row: dict) -> bool:
    if row["kind"] == "chat":
        args = ["chats", "delete", row["id"], "--yes", "--personal", "--api-url", API_URL]
    else:
        args = ["projects", "delete", row["id"], "--confirm", row["id"], "--personal", "--api-url", API_URL]
    return subprocess.run([cli, *args], cwd=ROOT, capture_output=True, text=True, timeout=120, check=False).returncode == 0


def table(rows: list[dict], extra: str = "") -> None:
    for row in rows:
        print(f"{row['id']}\t{row['kind']}\t{row['title']}\t{row['created']}" + (f"\t{row[extra]}" if extra else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--cli", default="openmates")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--ids", default="")
    parser.add_argument("--verified-projects", default="",
                        help="recipe Project ids whose creation on or after 2026-11-14 was checked out of band")
    args = parser.parse_args()
    wanted = [i for i in args.ids.split(",") if i]
    if args.delete and not wanted:
        parser.error("--delete needs --ids")
    cli = shutil.which(args.cli)
    if not cli:
        parser.error("installed global openmates executable missing")
    state = Path(tempfile.mkdtemp(prefix="agentic-cleanup-state-", dir="/tmp"))
    os.chmod(state, 0o700)
    for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
        os.environ.pop(key, None)
    os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
    account = None
    status = 0
    try:
        account = dev_test_account.acquire_real_test_account(
            "agentic-cleanup", args.session, "agentic-cleanup", stack_timeout=1800, allow_throwaway=False)
        login = subprocess.run(["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login",
                                "--slot", "", "--api-url", API_URL], cwd=ROOT, env=account.environment,
                               capture_output=True, text=True, check=False, timeout=180)
        if login.returncode:
            raise ProofError(f"login_failed: {safe_failure(login.stderr)}")
        candidates, excluded, notes = collect(cli, frozenset(i for i in args.verified_projects.split(',') if i))
        print("# " + "; ".join(notes))
        print("id\tkind\ttitle\tcreated")
        table(candidates)
        if excluded:
            print("\n# recipe-like items excluded")
            table(excluded, "why")
        if args.delete:
            by_id = {row["id"]: row for row in candidates}
            unknown = [i for i in wanted if i not in by_id]
            if unknown:
                raise ProofError(f"ids_not_candidates: {','.join(unknown)}")
            for item_id in wanted:  # chats before Projects is not required; ids are explicit
                ok = delete(cli, by_id[item_id])
                print(f"{item_id}: {'deleted' if ok else 'FAILED'}")
                status |= 0 if ok else 1
    except (ProofError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        status = 1
    finally:
        if account is not None:
            dev_test_account.finish_real_test_account(account)
        shutil.rmtree(state, ignore_errors=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
