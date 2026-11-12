#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real chats for the Browse example flows.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/web_browse_real_test.py --session ID \
    --state-dir /tmp/browse-flows-state-UNIQUE --output-dir /tmp/browse-flows-UNIQUE \
    --allow-paid-dev-inference [--case catalogue-two-pages]

Each case is an ordinary chat through the installed CLI with the personal
dev-test account in isolated CLI state; routing to Browse is automatic. The
receipt records, per case, whether Browse ran, its outcome, steps, timings,
missing values and credits, plus simple content checks. Never run in CI.
Transcripts stay outside the repository; only this run's chats are deleted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from code_run_real_test import command, delete_owned_chat, personal_test_environment, personal_test_leases
from personal_dev_draft_guard import DraftGuard, DraftGuardError
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

ROOT = Path(__file__).resolve().parents[1]
EMBED_REF = re.compile(r'\\"embed_id\\":\\"([0-9a-f-]{36})\\",\\"app_id\\":\\"web\\",\\"skill_id\\":\\"browse\\"')

# expect_all / expect_any are matched case-insensitively against the whole saved chat.
CASES: dict[str, dict] = {
    "grow-kits": {
        "browse_required": True,
        "expect_any": ["€", "eur", "$", "£"],
        "expect_all": ["law", "kit"],
        "turns": [
            "Search for psilocybin mushroom grow kits I can order online. Open one shop in the browser and list "
            "five kits with name, price and product link."
        ],
    },
    "catalogue-two-pages": {
        "browse_required": True,
        "expect_all": ["a light in the attic", "in her wake"],
        "turns": [
            "Use the browser on https://books.toscrape.com/ and give me title and price of every book on the "
            "first two catalogue pages as a table."
        ],
    },
    "javascript-page": {
        "browse_required": True,
        "expect_all": ["einstein"],
        "turns": [
            "Open https://quotes.toscrape.com/js/ in the browser (it needs JavaScript) and give me the first "
            "three quotes with their authors."
        ],
    },
    "search-form": {
        "browse_required": True,
        "expect_any": ["inspirational", "life", "love"],
        "expect_all": ["austen"],
        "turns": [
            "In the browser, go to https://quotes.toscrape.com/search.aspx, choose the author Jane Austen and any "
            "tag that is offered, run the search and tell me the quote it shows."
        ],
    },
    "own-site": {
        "browse_required": True,
        "expect_all": ["openmates"],
        "turns": [
            "Open https://openmates.org in the browser, follow the main call-to-action button and tell me which "
            "page it leads to and what that page asks me to do."
        ],
    },
    "missing-fact": {
        # Reading a static page without the browser is a correct way to answer this one.
        "browse_required": False,
        "expect_any": ["not", "no phone", "could not", "couldn't", "doesn't", "does not"],
        "forbid": ["+1 ", "(555)"],
        "turns": [
            "Open https://example.com in the browser and give me the page heading and the support phone number "
            "shown on that page."
        ],
    },
}


def browse_results(node: object, found: list[dict]) -> list[dict]:
    """Collect saved Browse result objects from a `chats show` payload of unknown nesting."""
    if isinstance(node, dict):
        if "run_id" in node and "session_id" in node and node.get("status") in RUN_STATUSES:
            found.append(node)
        for value in node.values():
            browse_results(value, found)
    elif isinstance(node, list):
        for value in node:
            browse_results(value, found)
    elif isinstance(node, str) and '"run_id"' in node and '"session_id"' in node:
        try:
            browse_results(json.loads(node), found)
        except ValueError:
            pass
    return found


RUN_STATUSES = ("completed", "no_results", "needs_user", "failed", "cancelled")


def summarize(result: dict) -> dict:
    """Content-free summary of one saved Browse result (metrics are stored flattened as metrics_<name>)."""
    nested = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    metrics = {**nested, **{key[8:]: value for key, value in result.items()
                            if key.startswith("metrics_") and isinstance(value, (int, float, str, bool))}}
    return {
        "status": result.get("status"), "reason": result.get("reason"), "url": result.get("url"),
        "missing": result.get("missing") or [], "sources": len(result.get("sources") or []),
        "has_data": any(result.get(key) not in (None, {}, [], "", "null", "{}") for key in ("data", "data_json")),
        "metrics": metrics,
    }


def run_case(cli: str, label: str, case: dict, out: Path, timeout: int, keep_chat: bool) -> dict:
    result: dict = {"label": label, "status": "failed", "turns": []}
    chat_id = None
    try:
        for index, prompt in enumerate(case["turns"]):
            args = (["chats", "new", prompt] if chat_id is None else ["chats", "send", "--chat", chat_id, prompt])
            started = time.monotonic()
            reply = command(cli, [*args, "--personal", "--auto-approve", "--response-timeout-seconds", str(timeout)],
                            timeout=timeout + 30)
            write_receipt(out / f"{label}-turn{index + 1}.json", {"prompt": prompt, "reply": reply})
            if not isinstance(reply, dict):
                raise ProofError("cli_reply_shape_unexpected")
            chat_id = chat_id or reply.get("chatId")
            if not isinstance(chat_id, str) or not chat_id:
                raise ProofError("created_chat_id_missing")
            result["chat_id"] = chat_id
            result["turns"].append({"status": reply.get("status"),
                                    "outer_seconds": round(time.monotonic() - started, 1)})
        shown = command(cli, ["chats", "show", chat_id, "--personal"])
        write_receipt(out / f"{label}-chat.json", shown)
        text = json.dumps(shown, ensure_ascii=False).lower()
        found = browse_results(shown, [])
        # Saved chats reference the Browse embed; its decrypted content holds the result.
        embed_ids = sorted({m.group(1) for m in EMBED_REF.finditer(json.dumps(shown))})
        for number, embed_id in enumerate(embed_ids, 1):
            embed = command(cli, ["embeds", "show", embed_id, "--chat", chat_id])
            write_receipt(out / f"{label}-embed{number}.json", embed)
            text += json.dumps(embed, ensure_ascii=False).lower()
            browse_results(embed, found)
        runs = [summarize(item) for item in found]
        result["browse_runs"] = runs
        result["browse_ran"] = bool(runs)
        result["browse_delivered"] = any(run["status"] in ("completed", "no_results") for run in runs)
        result["content_check"] = (
            all(token in text for token in case.get("expect_all", []))
            and (not case.get("expect_any") or any(token in text for token in case["expect_any"]))
            and not any(token in text for token in case.get("forbid", []))
        )
        passed = result["content_check"] and (result["browse_delivered"] or not case["browse_required"])
        result["status"] = "passed" if passed else "failed"
    except (ProofError, subprocess.TimeoutExpired) as exc:
        result["reason"] = str(exc) if isinstance(exc, ProofError) else "timeout"
    finally:
        if chat_id and not keep_chat:
            try:
                delete_owned_chat(cli, chat_id)
                result["chat_deleted"] = True
            except (ProofError, subprocess.TimeoutExpired):
                result["chat_deleted"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cli", default="openmates")
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--keep-chats", action="store_true", help="Leave the chats for review in the web app.")
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    args = parser.parse_args()
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        parser.error("real inference is dev-only and cannot run in CI")
    if not args.allow_paid_dev_inference or not 60 <= args.timeout_seconds <= 1200:
        parser.error("explicit paid-dev opt-in and a 60-1200 second timeout required")
    state, out = args.state_dir.resolve(), args.output_dir.resolve()
    for path in (state, out):
        if path == Path("/tmp") or not path.is_relative_to(Path("/tmp")) or path.exists():
            parser.error("--state-dir and --output-dir must be fresh paths below /tmp")
    cli = shutil.which(args.cli)
    if not cli:
        parser.error("installed global openmates executable missing")
    receipt: dict = {"status": "started", "target": API_URL, "session": args.session, "cases": []}
    leases, stop, guard = [], threading.Event(), None
    old_umask = os.umask(0o077)
    try:
        state.mkdir(mode=0o700)
        out.mkdir(mode=0o700, parents=True)
        os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
        for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
            os.environ.pop(key, None)
        login_env = personal_test_environment()
        leases = personal_test_leases(args.session)

        def renew() -> None:
            while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                for lease_id, owner, resources, mode in leases:
                    sessions.renew_test_resource_lease(lease_id, owner, resources, mode=mode)

        threading.Thread(target=renew, daemon=True).start()
        login = subprocess.run(["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login",
                                "--slot", "", "--api-url", API_URL], cwd=ROOT, env=login_env,
                               capture_output=True, text=True, check=False, timeout=180)
        if login.returncode:
            raise ProofError("personal_account_login_failed")
        try:
            guard = DraftGuard.start(cli, api_url=API_URL)
        except DraftGuardError as exc:
            raise ProofError(str(exc)) from exc
        for label in args.case or sorted(CASES):
            result = run_case(cli, label, CASES[label], out, args.timeout_seconds, args.keep_chats)
            receipt["cases"].append(result)
            print(json.dumps(result), flush=True)
        receipt["status"] = "passed" if all(c["status"] == "passed" for c in receipt["cases"]) else "failed"
    except ProofError as exc:
        receipt.update(status="failed", reason=str(exc))
    finally:
        stop.set()
        if guard is not None:
            from personal_dev_draft_guard import record_leftovers
            record_leftovers(receipt, guard)
        for lease_id, *_ in reversed(leases):
            sessions.release_test_resource_lease(lease_id)
        shutil.rmtree(state, ignore_errors=True)
        os.umask(old_umask)
        if out.is_dir():
            write_receipt(out / "receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "cases"}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
