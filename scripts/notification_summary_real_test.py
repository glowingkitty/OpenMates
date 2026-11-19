#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference proof for the push/email notification headline.

One real chat on the deployed dev stack (synthetic prompt, personal dev test account,
`@Gemini-3.8-Flash`). When the reply is complete, the pipeline's post-processing has
staged a Vault-sealed headline (type + summary <= 90 chars) for the push dispatcher.
The proof opens that headline inside the API container and shows the push exactly as
the dispatcher builds it: what goes to APNs (generic alert + ciphertext) next to what
a device decrypts, sealed to a throwaway device key. Nothing reaches Apple.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/notification_summary_real_test.py --session ID --revision FULL_SHA \
    --state-dir /tmp/notification-summary-state-UNIQUE \
    --receipt /tmp/notification-summary-proof/receipt.json \
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI. Receipts stay outside the repository. Only this run's chat is deleted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from chat_awareness_real_test import assistant_text, send_new_chat
from code_run_real_test import (
    ROOT, command, delete_owned_chat, personal_test_environment, personal_test_leases, require_runtime_revision,
)
from personal_dev_draft_guard import DraftGuard, DraftGuardError, record_leftovers
from verify_chat_sidebar_title_live import safe_failure
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

MODEL = "@Gemini-3.8-Flash"
CHAT_TITLE = "Taglines for a fictional garden shop"
PROMPT = (f"{MODEL} This is a synthetic notification test. Write three short taglines for a fictional garden "
          "shop called Example Garden Co, then say which one you prefer.")
HEADLINE_SETTLE_SECONDS = 20
PROBE = "/app/backend/scripts/probe_notification_headline_live.py"


def run_probe(email: str) -> str:
    """Open the staged headline in the API container; the e-mail goes over stdin only."""
    result = subprocess.run(
        ["docker", "exec", "-i", "api", "python", PROBE, "--chat-title", CHAT_TITLE],
        input=json.dumps({"email": email}), capture_output=True, text=True, timeout=120, check=False)
    if result.returncode or "live notification headline proof passed" not in result.stdout:
        raise ProofError("headline_probe_failed:" + safe_failure(result.stderr or result.stdout))
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--revision", required=True, help="Exact deployed dev SHA")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--cli", default="openmates", help="Installed global CLI executable")
    parser.add_argument("--personal-dev-test-account", action="store_true", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    args = parser.parse_args()
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        parser.error("real inference is dev-only and cannot run in CI")
    if not args.allow_paid_dev_inference or not 60 <= args.timeout_seconds <= 900:
        parser.error("explicit paid-dev opt-in and a 60-900 second timeout required")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be the full deployed dev SHA")
    state, receipt_path = args.state_dir.resolve(), args.receipt.resolve()
    if state == Path("/tmp") or not state.is_relative_to(Path("/tmp")) or state.exists():
        parser.error("--state-dir must be a fresh path below /tmp")
    if not receipt_path.is_relative_to(Path("/tmp")) or receipt_path.is_relative_to(state) \
            or receipt_path.is_relative_to(ROOT):
        parser.error("private receipt must be below /tmp and outside CLI state/repository")
    cli = shutil.which(args.cli)
    if not cli:
        parser.error("installed global openmates executable missing")
    slug = f"notification-summary-{secrets.token_hex(6)}"
    receipt: dict = {"status": "started", "target": API_URL, "session": args.session,
                     "deployed_revision": args.revision, "started_at": datetime.now(UTC).isoformat(),
                     "model": MODEL, "chats": {"main": {"slug": slug}}, "cleanup": {}}
    leases, created_state, draft_guard = [], False, None
    old_umask = os.umask(0o077)
    try:
        state.mkdir(mode=0o700)
        created_state = True
        receipt_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
        for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
            os.environ.pop(key, None)
        login_env = personal_test_environment()
        leases = personal_test_leases(args.session)
        require_runtime_revision(args.revision)
        login = subprocess.run(["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login",
                                "--slot", "", "--api-url", API_URL], cwd=ROOT, env=login_env,
                               capture_output=True, text=True, check=False, timeout=180)
        if login.returncode:
            receipt["bootstrap_failure"] = safe_failure(login.stderr)
            raise ProofError("personal_account_bootstrap_failed")
        try:
            draft_guard = DraftGuard.start(cli, api_url=API_URL)
        except DraftGuardError as exc:
            raise ProofError(str(exc)) from exc

        print(f"Prompt: {PROMPT}", flush=True)
        chat_id = send_new_chat(cli, PROMPT, slug, args.timeout_seconds)
        receipt["chats"]["main"]["chat_id"] = chat_id
        reply = assistant_text(command(cli, ["chats", "show", chat_id, "--all", "--personal"]))
        print(f"Assistant reply:\n{reply}\n", flush=True)
        time.sleep(HEADLINE_SETTLE_SECONDS)
        output = run_probe(login_env["OPENMATES_TEST_ACCOUNT_EMAIL"])
        print(output, flush=True)
        receipt["probe_output"] = output
        require_runtime_revision(args.revision)
        receipt["status"] = "passed"
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt["error_code"] = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
    finally:
        entry = receipt["chats"]["main"]
        try:
            chat_id = entry.get("chat_id") or command(cli, ["chats", "show", slug, "--personal"]).get("chat", {}).get("id")
            if not chat_id:
                raise ProofError("owned_chat_cleanup_id_missing")
            delete_owned_chat(cli, chat_id)
            receipt["cleanup"]["main"] = "deleted"
        except (ProofError, subprocess.TimeoutExpired, json.JSONDecodeError):
            receipt["cleanup"]["main"] = "failed"
            receipt["status"] = "failed"
        record_leftovers(receipt, draft_guard)
        for lease_id, *_ in reversed(leases):
            try:
                sessions.release_test_resource_lease(lease_id)
            except RuntimeError:
                receipt["cleanup"]["lease"] = "failed"
                receipt["status"] = "failed"
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_receipt(receipt_path, receipt)
        if created_state:
            shutil.rmtree(state)
        os.umask(old_umask)
        print(f"Notification summary real proof {receipt['status']}; receipt: {receipt_path}", flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
