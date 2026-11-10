#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real chats for the Jobs focus modes and Jobs search.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/jobs_focus_real_test.py --session ID \
    --state-dir /tmp/jobs-focus-state-UNIQUE --output-dir /tmp/jobs-focus-UNIQUE \
    --allow-paid-dev-inference [--case create-cv]

Runs scripted multi-turn conversations through the installed CLI with the
personal dev-test account in isolated CLI state. Never run in CI. Transcripts
are synthetic and stay outside the repository; only this run's chats are deleted.
Each case records whether the expected focus mode activated and simple content
checks; judging answer quality is left to the reader of the transcripts.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from code_run_real_test import command, delete_owned_chat, personal_test_environment, personal_test_leases
from personal_dev_draft_guard import DraftGuard, DraftGuardError
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

ROOT = Path(__file__).resolve().parents[1]

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
                delete_owned_chat(cli, chat_id)
                result["chat_deleted"] = True
            except (ProofError, subprocess.TimeoutExpired):
                result["chat_deleted"] = False
    return result


def run_profile_reuse(cli: str, out: Path, timeout: int) -> dict:
    """Chat 1 asks the assistant to save a career profile Memory; chat 2 must use it unprompted."""
    result: dict = {"label": "profile-reuse", "status": "failed"}
    chats: list[str] = []
    flags = ["--personal", "--auto-approve", "--response-timeout-seconds", str(timeout)]
    try:
        first = command(cli, ["chats", "new", "Please save my career profile as a memory so I never have to "
                              "repeat it. " + PERSON, *flags], timeout=timeout + 30)
        write_receipt(out / "profile-reuse-save.json", first)
        if not isinstance(first, dict) or not first.get("chatId"):
            raise ProofError("created_chat_id_missing")
        chats.append(first["chatId"])
        writes = first.get("memoryWrites") or []
        result["memory_writes"] = [{k: w.get(k) for k in ("action", "status", "errorCode", "undoAvailable")}
                                   for w in writes if isinstance(w, dict)]
        result["saved"] = any(w.get("status") == "applied" for w in writes if isinstance(w, dict))
        second = command(cli, ["chats", "new", "Write a short cover letter in English for this job, using what "
                               "you know about me. " + POSTING, *flags], timeout=timeout + 30)
        write_receipt(out / "profile-reuse-use.json", second)
        if not isinstance(second, dict) or not second.get("chatId"):
            raise ProofError("created_chat_id_missing")
        chats.append(second["chatId"])
        shown = command(cli, ["chats", "show", second["chatId"], "--personal"])
        write_receipt(out / "profile-reuse-use-chat.json", shown)
        text = json.dumps(shown).lower()
        result["profile_used"] = "example retail" in text and "15" in text
        result["status"] = "passed" if result["saved"] and result["profile_used"] else "failed"
    except (ProofError, subprocess.TimeoutExpired) as exc:
        result["reason"] = str(exc) if isinstance(exc, ProofError) else "timeout"
    finally:
        if chats and result.get("saved"):
            try:
                command(cli, ["settings", "memories", "undo", "--chat", chats[0]])
                result["memory_removed"] = True
            except (ProofError, subprocess.TimeoutExpired):
                result["memory_removed"] = False
        for chat_id in chats:
            try:
                delete_owned_chat(cli, chat_id)
            except (ProofError, subprocess.TimeoutExpired):
                result["chat_deleted"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cli", default="openmates")
    parser.add_argument("--case", action="append", choices=sorted([*CASES, "profile-reuse"]))
    parser.add_argument("--timeout-seconds", type=int, default=420)
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
