#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real chats for the Jobs focus modes and Jobs search.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/jobs_focus_real_test.py --session ID \
    --state-dir /tmp/jobs-focus-state-UNIQUE --output-dir /tmp/jobs-focus-UNIQUE \
    --allow-paid-dev-inference [--case create-cv]
  Native Rust CLI built from this checkout (profile-reuse needs it, see below):
    ... --native-cli /abs/target/debug/openmates \
        --native-session-import /abs/target/debug/native-cli-session-import

Runs scripted multi-turn conversations through the installed CLI with the
personal dev-test account in isolated CLI state. With --native-cli the native
binary runs every chat command; native `login` is browser pairing only, so the
session is admitted by scripts/native_cli_session_import (shared Rust core
password login into the same fresh /tmp state) instead of the npm login. Never run in CI. Transcripts
are synthetic and stay outside the repository; only this run's chats are deleted.
Each case records whether the expected focus mode activated and simple content
checks; judging answer quality is left to the reader of the transcripts.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import struct
import threading
import time
from pathlib import Path
from uuid import uuid4

from code_run_real_test import command, delete_owned_chat
from personal_dev_draft_guard import DraftGuard, DraftGuardError
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

ROOT = Path(__file__).resolve().parents[1]
APP_URL = "https://app.dev.openmates.org"
NATIVE = {"enabled": False}
NARRATE = {"enabled": False}


def narrate(title: str, body: str = "") -> None:
    """Readable progress for terminal recordings (--narrate); synthetic data only."""
    if NARRATE["enabled"]:
        print(f"\n=== {title} ===", flush=True)
        if body:
            print(body.strip()[:1800], flush=True)


def totp(secret: str, offset: int = 0) -> str:
    """RFC 6238 code matching scripts/openmates_cli_test_account.mjs generateTotp."""
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret.replace(" ", "")) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time() // 30) + offset), hashlib.sha1).digest()
    start = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[start:start + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def native_login(importer: str, login_env: dict[str, str]) -> None:
    """Admit a password-login session into the fresh native state; never prints credentials."""
    for offset in (0, -1, 1):
        env = dict(login_env, OPENMATES_APP_URL=APP_URL,
                   OPENMATES_TEST_ACCOUNT_TOTP=totp(login_env["OPENMATES_TEST_ACCOUNT_OTP_KEY"], offset))
        done = subprocess.run([importer], cwd=ROOT, env=env, capture_output=True, text=True,
                              check=False, timeout=180)
        if not done.returncode:
            return
    raise ProofError("personal_account_native_login_failed")


def admitted_chat_id(transport: Path) -> str | None:
    """Chat id of a turn the server acknowledged before the native CLI failed."""
    try:
        stderr = json.loads(transport.read_text()).get("stderr") or ""
        error = json.loads(stderr.strip().splitlines()[-1]).get("error") or {}
    except (OSError, ValueError, IndexError, AttributeError):
        return None
    chat_id = error.get("chat_id") if error.get("admitted") else None
    return chat_id if isinstance(chat_id, str) and chat_id else None


def npm_show(chat_id: str) -> dict:
    """Read-only transcript through the installed npm CLI in its own fresh /tmp state."""
    reader = NATIVE["npm_reader"]
    env = dict(os.environ, OPENMATES_STATE_DIR=reader["state"])
    shown = subprocess.run([reader["cli"], "chats", "show", chat_id, "--personal", "--api-url", API_URL, "--json"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=False)
    try:
        return {"returncode": shown.returncode, "chat": json.loads(shown.stdout)}
    except json.JSONDecodeError:
        return {"returncode": shown.returncode, "stdout": shown.stdout[-2000:], "stderr": shown.stderr[-500:]}


def delete_chat(cli: str, chat_id: str) -> None:
    """npm prints a count line; the native CLI returns {"deleted": [ids]} with --json."""
    if not NATIVE["enabled"]:
        delete_owned_chat(cli, chat_id)
        return
    deleted = command(cli, ["chats", "delete", chat_id, "--yes", "--personal"])
    if not isinstance(deleted, dict) or deleted.get("deleted") != [chat_id]:
        raise ProofError("owned_chat_cleanup_failed")

PERSON = (
    "My details (all synthetic test data): Alex Example, Berlin, alex@example.org, +49 30 0000000. "
    "Work: 03/2022 - present, Customer Support Specialist at Example Retail GmbH, Berlin: answered about 40 "
    "tickets a day, built weekly ticket reports in Excel and later SQL, cut repeat contacts by 15 percent with a "
    "new FAQ. 09/2019 - 02/2022, Working Student in Controlling at Sample Logistics AG, Hamburg: monthly cost "
    "reports, data cleaning in Excel. Education: B.Sc. Business Administration, University of Hamburg, "
    "10/2017 - 09/2021. Skills: SQL, Excel, Python basics, Tableau. Languages: German native, English fluent."
)
POSTING = (
    "Job posting (synthetic): Junior Data Analyst (m/f/d), Example Mobility GmbH, Berlin, hybrid. Tasks: build "
    "dashboards in Tableau, write SQL queries on customer and operations data, prepare weekly reports for the "
    "operations team. Requirements: degree in business, statistics or similar; good SQL; experience with a BI "
    "tool; fluent German and English. Nice to have: Python. Apply with CV and cover letter in German or English."
)
CASES: dict[str, dict] = {
    "create-cv": {"focus": "create_cv", "expect_any": ["docx", "document"], "turns": [
        "I have no CV yet and want to apply for junior data analyst jobs in Germany. Please create one for me.",
        "Skip the remaining questions, here is everything. CV in English, for Germany, no photo and no date of "
        "birth. " + PERSON,
        "Confirmed, that is all correct. Please write the CV now.",
        "Is this CV readable by applicant tracking systems? Tell me plainly what passes.",
    ]},
    "write-application": {"focus": "write_application", "expect_any": ["docx", "document"], "turns": [
        "Write a cover letter in English for this job. " + POSTING + " " + PERSON,
        "Why this employer: I use their bike sharing every day and want to work on operations data. Highlight the "
        "FAQ project and my SQL reports. I write plainly and directly, short sentences. Skip further questions "
        "and write it.",
    ]},
    "prepare-interview": {"focus": "prepare_interview", "expect_any": ["?"], "turns": [
        "I have a video interview on Thursday for this role and I'm nervous about the weakness question. "
        + POSTING + " " + PERSON + " Skip further questions and give me the preparation plan.",
        "Start a practice interview now.",
        "I worked in support, where I noticed the same questions kept coming. I wrote a new FAQ and repeat "
        "contacts went down 15 percent.",
    ]},
    "career-insights": {"focus": "career_insights", "expect_any": ["?"], "turns": [
        "I'm stuck in customer support and don't know what to do next with my career. Help me find a direction.",
    ]},
    "jobs-search": {"focus": None, "expect_any": ["arbetsformedlingen", "embed"], "turns": [
        "Search for current data analyst jobs in Stockholm, Sweden and show me five.",
    ]},
}


def run_case(cli: str, label: str, case: dict, out: Path, timeout: int) -> dict:
    result: dict = {"label": label, "status": "failed", "turns": []}
    chat_id = None
    try:
        for index, prompt in enumerate(case["turns"]):
            args = (["chats", "new", prompt] if chat_id is None else ["chats", "send", "--chat", chat_id, prompt])
            reply = command(cli, [*args, "--personal", "--auto-approve", "--response-timeout-seconds", str(timeout)],
                            timeout=timeout + 30)
            write_receipt(out / f"{label}-turn{index + 1}.json", {"prompt": prompt, "reply": reply})
            if not isinstance(reply, dict):
                raise ProofError("cli_reply_shape_unexpected")
            chat_id = chat_id or reply.get("chatId")
            if not isinstance(chat_id, str) or not chat_id:
                raise ProofError("created_chat_id_missing")
            result["chat_id"] = chat_id
            result["turns"].append({"status": reply.get("status"), "chars": len(json.dumps(reply))})
        shown = command(cli, ["chats", "show", chat_id, "--personal"])
        write_receipt(out / f"{label}-chat.json", shown)
        text = json.dumps(shown).lower()
        focus = case["focus"]
        result["focus_activated"] = None if focus is None else f"jobs-{focus}" in text or f"jobs.{focus}" in text
        result["content_check"] = any(token in text for token in case["expect_any"])
        result["status"] = "passed" if result["content_check"] and result["focus_activated"] is not False else "failed"
    except (ProofError, subprocess.TimeoutExpired) as exc:
        result["reason"] = str(exc) if isinstance(exc, ProofError) else "timeout"
    finally:
        if chat_id:
            try:
                delete_chat(cli, chat_id)
                result["chat_deleted"] = True
            except (ProofError, subprocess.TimeoutExpired):
                result["chat_deleted"] = False
    return result


MODEL = "@Gemini-3.8-Flash"
MODEL_NAME = "Gemini 3.8 Flash"


def persisted_models(shown: object) -> set[str]:
    """Every assistant ``modelName`` recorded in a ``chats show`` transcript."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            name = node.get("modelName")
            if isinstance(name, str) and name:
                found.add(name)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(shown)
    return found


def run_profile_reuse(cli: str, out: Path, timeout: int) -> dict:
    """Chat 1 asks the assistant to save a career profile Memory; chat 2 must use it unprompted."""
    result: dict = {"label": "profile-reuse", "status": "failed"}
    chats: list[str] = []
    baseline: set[str] = set()
    slugs: list[str] = []
    flags = ["--personal", "--auto-approve", "--response-timeout-seconds", str(timeout)]
    try:
        before = command(cli, ["settings", "memories", "list"])
        baseline = {json.dumps(entry, sort_keys=True) for entry in before} if isinstance(before, list) else set()
        save_prompt = f"{MODEL} Please save my career profile as a memory so I never have to repeat it. " + PERSON
        narrate("Chat 1: you ask the assistant to remember your career profile", save_prompt)
        first = command(cli, ["chats", "new", save_prompt, *flags], timeout=timeout + 30)
        write_receipt(out / "profile-reuse-save.json", first)
        if not isinstance(first, dict) or not first.get("chatId"):
            raise ProofError("created_chat_id_missing")
        chats.append(first["chatId"])
        writes = first.get("memoryWrites") or []
        result["memory_writes"] = [{k: w.get(k) for k in ("action", "status", "errorCode", "undoAvailable")}
                                   for w in writes if isinstance(w, dict)]
        result["saved"] = any(w.get("status") == "applied" for w in writes if isinstance(w, dict))
        narrate("Assistant answer (chat 1)", str(first.get("assistant") or ""))
        narrate("Memory written by the assistant", json.dumps(
            [{k: w.get(k) for k in ("action", "status", "title", "undoAvailable")} for w in writes
             if isinstance(w, dict)], indent=2))
        listed = command(cli, ["settings", "memories", "list"])
        write_receipt(out / "profile-reuse-memories.json", listed)
        added = [entry for entry in listed if json.dumps(entry, sort_keys=True) not in baseline] \
            if isinstance(listed, list) else []
        result["memories_added"] = len(added)
        result["memory_listed"] = "example retail" in json.dumps(added).lower()
        narrate("Settings > Memories now lists", "\n".join(
            str(((entry.get("data") or {}).get("title")) if isinstance(entry, dict) else entry) for entry in added))
        # Assistant-saved Memories load as ask_first; the native CLI approves a
        # Memory-load consent request only with --auto-approve-memories.
        second_slug = f"profile-reuse-{uuid4().hex}"
        slugs.append(second_slug)
        transport = out / "profile-reuse-use-transport.json"
        try:
            use_prompt = (f"{MODEL} Write a short cover letter in English for this job, using what you know about me. "
                          + POSTING)
            narrate("Chat 2 (new chat): you ask for a cover letter, without repeating your profile", use_prompt)
            second = command(cli, ["chats", "new", use_prompt, "--slug", second_slug, *flags,
                                   "--auto-approve-memories"], timeout=timeout + 30, diagnostic_path=transport)
        except ProofError:
            admitted = admitted_chat_id(transport)
            if not admitted or not NATIVE.get("npm_reader"):
                raise
            # The server acknowledged the turn but the native CLI could not read
            # the reply; keep the failure and read the transcript for evidence.
            chats.append(admitted)
            result["second_native_error"] = "admitted_turn_unreadable"
            write_receipt(out / "profile-reuse-use-chat-npm.json", npm_show(admitted))
            raise
        write_receipt(out / "profile-reuse-use.json", second)
        if not isinstance(second, dict) or not second.get("chatId"):
            raise ProofError("created_chat_id_missing")
        chats.append(second["chatId"])
        result["second_status"] = second.get("status")
        narrate("Memory load request in chat 2 (Ask first, approved)", json.dumps(
            second.get("appSettingsMemoryRequests"), indent=2))
        narrate("Assistant answer (chat 2) uses the saved profile", str(second.get("assistant") or ""))
        try:
            shown = command(cli, ["chats", "show", second["chatId"], "--personal"],
                            diagnostic_path=out / "profile-reuse-use-show-transport.json")
        except ProofError:
            # Evidence for the failure: does another reader decrypt the same
            # chat, and does the native reader still open the saving chat?
            if NATIVE.get("npm_reader"):
                write_receipt(out / "profile-reuse-use-chat-npm.json", npm_show(second["chatId"]))
            try:
                write_receipt(out / "profile-reuse-save-chat.json",
                              command(cli, ["chats", "show", chats[0], "--personal"]))
            except ProofError as exc:
                write_receipt(out / "profile-reuse-save-chat.json", {"error": str(exc)})
            raise
        write_receipt(out / "profile-reuse-use-chat.json", shown)
        text = json.dumps(shown).lower()
        result["profile_used"] = "example retail" in text and "15" in text
        result["models"] = sorted(persisted_models(shown))
        result["model_pinned"] = result["models"] == [MODEL_NAME]
        result["status"] = ("passed" if result["saved"] and result["memory_listed"] and result["profile_used"]
                            and result["model_pinned"] else "failed")
    except (ProofError, subprocess.TimeoutExpired) as exc:
        result["reason"] = str(exc) if isinstance(exc, ProofError) else "timeout"
    finally:
        if chats and result.get("saved"):
            try:
                undone = command(cli, ["settings", "memories", "undo", "--chat", chats[0]])
                narrate("Undo the assistant's memory write", json.dumps(undone, indent=2))
                write_receipt(out / "profile-reuse-undo.json", undone)
                after = command(cli, ["settings", "memories", "list"])
                write_receipt(out / "profile-reuse-memories-after-undo.json", after)
                result["memory_removed"] = isinstance(after, list) and not [
                    entry for entry in after if json.dumps(entry, sort_keys=True) not in baseline]
            except (ProofError, subprocess.TimeoutExpired):
                result["memory_removed"] = False
        for slug in slugs[len(chats) - 1:] if chats else []:
            # A failed send may still have created its chat; find it by its unique slug only.
            try:
                found = command(cli, ["chats", "show", slug, "--personal"])
                chat_id = ((found.get("chat") or {}).get("id") if isinstance(found, dict) else None)
                if chat_id and chat_id not in chats:
                    chats.append(chat_id)
            except (ProofError, subprocess.TimeoutExpired):
                pass
        for chat_id in chats:
            try:
                delete_chat(cli, chat_id)
            except (ProofError, subprocess.TimeoutExpired):
                result["chat_deleted"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cli", default="openmates")
    parser.add_argument("--native-cli", type=Path, help="Native Rust openmates binary (absolute path)")
    parser.add_argument("--native-session-import", type=Path,
                        help="Built scripts/native_cli_session_import binary (required with --native-cli)")
    parser.add_argument("--case", action="append", choices=sorted([*CASES, "profile-reuse"]))
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    parser.add_argument("--narrate", action="store_true", help="Print prompts and answers for a terminal recording")
    parser.add_argument("--personal-only", action="store_true",
                        help="Wait for the personal account instead of using a throwaway account when it is busy")
    args = parser.parse_args()
    NARRATE["enabled"] = args.narrate
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        parser.error("real inference is dev-only and cannot run in CI")
    if not args.allow_paid_dev_inference or not 60 <= args.timeout_seconds <= 1200:
        parser.error("explicit paid-dev opt-in and a 60-1200 second timeout required")
    state, out = args.state_dir.resolve(), args.output_dir.resolve()
    for path in (state, out):
        if path == Path("/tmp") or not path.is_relative_to(Path("/tmp")) or path.exists():
            parser.error("--state-dir and --output-dir must be fresh paths below /tmp")
    if args.native_cli:
        native_bins = [args.native_cli, args.native_session_import]
        if not all(path and path.is_absolute() and path.is_file() and os.access(path, os.X_OK)
                   for path in native_bins):
            parser.error("--native-cli and --native-session-import must be absolute executable files")
        cli, importer = str(args.native_cli), str(args.native_session_import)
        NATIVE["enabled"] = True
    else:
        cli, importer = shutil.which(args.cli), None
    if not cli:
        parser.error("installed global openmates executable missing")
    receipt: dict = {"status": "started", "target": API_URL, "session": args.session, "cases": [],
                     "cli": "native" if importer else "npm"}
    leases, stop, guard, real_account = [], threading.Event(), None, None
    old_umask = os.umask(0o077)
    try:
        state.mkdir(mode=0o700)
        out.mkdir(mode=0o700, parents=True)
        os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
        for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
            os.environ.pop(key, None)
        if importer:
            # Same isolation as native CI: no desktop keyring (owner-only file
            # store inside the fresh state dir), no profile, plain output.
            os.environ.pop("OPENMATES_PROFILE", None)
            os.environ.update(DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent/openmates-no-bus",
                              NO_COLOR="1", OPENMATES_APP_URL=APP_URL)
        import dev_test_account

        # Personal account when free, else a throwaway dev account (chats are
        # backed up, then the account is deleted); --personal-only waits instead.
        real_account = dev_test_account.acquire_real_test_account(
            "jobs-focus", args.session, "jobs-focus", stack_timeout=120,
            allow_throwaway=not args.personal_only)
        login_env, leases = real_account.environment, real_account.leases
        receipt["account_role"] = ("personal_dev_test" if real_account.kind == "personal"
                                   else "throwaway_dev_test")

        def renew() -> None:
            while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                for lease_id, owner, resources, mode in leases:
                    sessions.renew_test_resource_lease(lease_id, owner, resources, mode=mode)

        threading.Thread(target=renew, daemon=True).start()
        if importer:
            native_login(importer, login_env)
            npm_cli = shutil.which(args.cli)
            if npm_cli:
                # Evidence-only reader for turns the native CLI cannot display;
                # npm session lives in its own subdirectory of the fresh state.
                npm_state = state / "npm-reader"
                npm_state.mkdir(mode=0o700)
                npm_login = subprocess.run(["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login",
                                            "--slot", "", "--api-url", API_URL], cwd=ROOT,
                                           env=dict(login_env, OPENMATES_STATE_DIR=str(npm_state)),
                                           capture_output=True, text=True, check=False, timeout=180)
                if not npm_login.returncode:
                    NATIVE["npm_reader"] = {"cli": npm_cli, "state": str(npm_state)}
        else:
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
            result = (run_profile_reuse(cli, out, args.timeout_seconds) if label == "profile-reuse"
                      else run_case(cli, label, CASES[label], out, args.timeout_seconds))
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
        if real_account is not None:
            receipt["account_cleanup"] = dev_test_account.finish_real_test_account(real_account)
        shutil.rmtree(state, ignore_errors=True)
        os.umask(old_umask)
        if out.is_dir():
            write_receipt(out / "receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "cases"}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
