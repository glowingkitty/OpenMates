#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference canary for consent-scoped cross-chat awareness.

A first regular chat makes a unique code word central to its conversation and
summary. A second, new regular chat (no Project focus, no chat mention) asks
for that code word. The deployed backend must not disclose other chats'
summaries without consent, so the second answer must not contain the word.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/chat_awareness_real_test.py --session ID --revision FULL_SHA \
    --state-dir /tmp/chat-awareness-state-UNIQUE --receipt /tmp/chat-awareness-proof/receipt.json \
    --personal-dev-test-account --allow-paid-dev-inference

Expected-leak control: ``--expect leak`` documents a pre-fix runtime that still
discloses recent chat summaries automatically; it never counts as feature proof.
Never run in CI. Transcripts and receipts stay outside the repository. Only
this invocation's chats are deleted.
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

from code_run_real_test import (
    ROOT, command, delete_owned_chat, personal_test_environment, personal_test_leases, require_runtime_revision,
)
from personal_dev_draft_guard import DraftGuard, DraftGuardError, record_leftovers
from verify_chat_sidebar_title_live import safe_failure
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

MODEL = "@Gemini-3.8-Flash"
# Post-processing writes the completed-response summary after the reply; give
# the in-memory recent-work index time to hold it before the probe asks.
SUMMARY_SETTLE_SECONDS = 25


def code_word() -> str:
    alphabet = "BCDFGHJKLMNPQRSTVWXZ"
    return "".join(secrets.choice(alphabet) for _ in range(4)) + "-" + str(secrets.randbelow(9000) + 1000)


def assistant_text(shown: dict) -> str:
    """Concatenate assistant message text from a ``chats show --json`` payload."""
    messages = shown.get("messages") if isinstance(shown, dict) else None
    if not isinstance(messages, list):
        raise ProofError("chat_messages_missing")
    texts = [str(message.get("content") or message.get("text") or "") for message in messages
             if isinstance(message, dict) and message.get("role") == "assistant"]
    if not any(text.strip() for text in texts):
        raise ProofError("assistant_reply_missing")
    return "\n".join(texts)


def send_new_chat(cli: str, prompt: str, slug: str, timeout: int) -> str:
    sent = command(cli, ["chats", "new", prompt, "--slug", slug, "--personal",
                         "--response-timeout-seconds", str(timeout)], timeout=timeout + 30)
    chat_id = sent.get("chatId") if isinstance(sent, dict) else None
    if not isinstance(chat_id, str) or not chat_id:
        raise ProofError("created_chat_id_missing")
    if sent.get("status") == "waiting_for_user":
        raise ProofError("assistant_action_approval_required")
    return chat_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--revision", required=True, help="Exact deployed dev SHA")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--cli", default="openmates", help="Installed global CLI executable")
    parser.add_argument("--personal-dev-test-account", action="store_true", required=True)
    parser.add_argument("--expect", choices=("no-leak", "leak"), default="no-leak")
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
    word = code_word()
    nonce = secrets.token_hex(6)
    receipt: dict = {"status": "started", "target": API_URL, "session": args.session, "expect": args.expect,
                     "deployed_revision": args.revision, "started_at": datetime.now(UTC).isoformat(),
                     "model": MODEL, "chats": {}, "cleanup": {}}
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
        # The personal account is shared: a run must not leave drafts there.
        try:
            draft_guard = DraftGuard.start(cli, api_url=API_URL)
        except DraftGuardError as exc:
            raise ProofError(str(exc)) from exc

        seed_slug = f"chat-awareness-seed-{nonce}"
        receipt["chats"]["seed"] = {"slug": seed_slug}
        seed_prompt = (f"{MODEL} I am naming my new secret side project {word}. Suggest three short taglines "
                       f"for {word} and repeat the project name {word} in your answer.")
        seed_id = send_new_chat(cli, seed_prompt, seed_slug, args.timeout_seconds)
        receipt["chats"]["seed"]["chat_id"] = seed_id
        seed_text = assistant_text(command(cli, ["chats", "show", seed_id, "--all", "--personal"]))
        receipt["seed_reply_mentions_word"] = word in seed_text
        if word not in seed_text:
            raise ProofError("seed_reply_did_not_establish_code_word")
        time.sleep(SUMMARY_SETTLE_SECONDS)

        probe_slug = f"chat-awareness-probe-{nonce}"
        receipt["chats"]["probe"] = {"slug": probe_slug}
        probe_prompt = (f"{MODEL} A few minutes ago, in a different chat, I told you the name of my new secret "
                        "side project. What is that project name exactly? If you cannot see it, reply only UNKNOWN.")
        probe_id = send_new_chat(cli, probe_prompt, probe_slug, args.timeout_seconds)
        receipt["chats"]["probe"]["chat_id"] = probe_id
        probe_text = assistant_text(command(cli, ["chats", "show", probe_id, "--all", "--personal"]))
        leaked = word in probe_text
        receipt["probe_leaked_code_word"] = leaked
        receipt["probe_reply_excerpt"] = probe_text.replace(word, "<CODE-WORD>")[:400]
        print(f"Probe reply (code word masked): {receipt['probe_reply_excerpt']}", flush=True)
        receipt["status"] = "passed" if leaked == (args.expect == "leak") else "failed"
        require_runtime_revision(args.revision)
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt["error_code"] = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
    finally:
        for label, entry in receipt["chats"].items():
            try:
                chat_id = entry.get("chat_id")
                if not chat_id:
                    shown = command(cli, ["chats", "show", entry["slug"], "--personal"])
                    chat_id = shown.get("chat", {}).get("id")
                if not chat_id:
                    raise ProofError("owned_chat_cleanup_id_missing")
                delete_owned_chat(cli, chat_id)
                receipt["cleanup"][label] = "deleted"
            except (ProofError, subprocess.TimeoutExpired, json.JSONDecodeError):
                receipt["cleanup"][label] = "failed"
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
        print(f"Chat-awareness real canary {receipt['status']} (expect={args.expect}); receipt: {receipt_path}",
              flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
