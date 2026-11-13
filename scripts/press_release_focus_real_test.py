#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real chats for the Business "Write press release" focus mode.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/press_release_focus_real_test.py --session ID \
    --state-dir /tmp/press-focus-state-UNIQUE --output-dir /tmp/press-focus-UNIQUE \
    --allow-paid-dev-inference [--case word]

Runs scripted multi-turn conversations through the OpenMates CLI (`--cli`, e.g. a
native build of this checkout) with the
personal dev-test account in isolated CLI state (same harness as
scripts/jobs_focus_real_test.py). Never run in CI. All company data is synthetic
and transcripts stay outside the repository; only this run's chats are deleted.
Each case records whether the focus mode activated, whether the requested
output format was produced, and simple structure checks; judging the writing is
left to the reader of the transcripts.
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
from pathlib import Path

from code_run_real_test import command, delete_owned_chat
from personal_dev_draft_guard import DraftGuard, DraftGuardError
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

ROOT = Path(__file__).resolve().parents[1]
FOCUS = "write_press_release"

NEWS = (
    "All synthetic test data. Company: Example Solar GmbH, Leipzig, founded 2021, 24 employees, makes balcony "
    "solar kits for renters. News: on 18 November 2026 we launch SunShare, an app that lets neighbours in one "
    "building pool their balcony solar power. Pilot: 120 households in Leipzig saved on average 11 percent on "
    "electricity over six months (our own pilot data, May to October 2026). Available from 18 November in "
    "Germany, free for Example Solar customers, 2 EUR a month otherwise, at example.org/sunshare. Quote from "
    "Mara Example, CEO: she wants renters to share energy like they share a stairwell. Media contact: Jonas "
    "Example, press officer, press@example.org, +49 341 0000000. Release for immediate publication."
)
STYLE = (
    "Our press style: always write 'Example Solar' (never 'ExampleSolar'), product name 'SunShare' in camel case, "
    "plain and friendly tone, no superlatives, English with AP style, end with ###. About paragraph: Example "
    "Solar GmbH, based in Leipzig, makes plug-in balcony solar kits for renters. Founded in 2021, the company "
    "has equipped more than 3,000 apartments in Germany."
)
# Embed types the assistant answer references for each requested format.
FORMAT_EMBED_TYPES = {
    "word": {"document"},
    "pdf": {"document"},
    "html": {"code", "website"},
    "react": {"application"},
}
# Checked in the generated release itself (embed content plus answer text).
STRUCTURE_TOKENS = ["leipzig", "sunshare", "about example solar", "###"]
EMBED_REF = re.compile(r'\{"type":\s*"([a-z_]+)",\s*"embed_id":\s*"([0-9a-f-]{36})"')
CASES: dict[str, dict] = {
    "word": {"format": "word", "turns": [
        "Write a press release about our new app launch. " + NEWS,
        "We have no press style yet. " + STYLE + " Do not save it. Skip further questions.",
        "Use your recommended headline, the facts are correct. Write the press release now.",
        "Check it plainly and also write a short pitch email for a tech journalist.",
    ]},
    "pdf": {"format": "pdf", "turns": [
        "Create a press release as a PDF. " + NEWS + " " + STYLE
        + " Skip all questions and the fact check, use your recommended headline and write it now.",
    ]},
    "html": {"format": "html", "turns": [
        "Create our press release as an HTML page for our online newsroom. " + NEWS + " " + STYLE
        + " Skip all questions and the fact check, use your recommended headline and write it now.",
    ]},
    "react": {"format": "react", "turns": [
        "Create our press release as a React page for our website. " + NEWS + " " + STYLE
        + " Skip all questions and the fact check, use your recommended headline and write it now.",
    ]},
    "project-style": {"format": "word", "project": True, "turns": [
        "Set up our press style for press releases and save it to this project. " + STYLE
        + " Media contact: Jonas Example, press officer, press@example.org. Mara Example, CEO, is usually quoted.",
        "Thanks. If the press style is not saved to this project's Memories yet, save it now; otherwise just confirm.",
    ], "reuse_turns": [
        "Write a press release as a Word document about our app launch. " + NEWS
        + " Skip all questions and the fact check, use your recommended headline and write it now.",
    ]},
    "not-investor-outreach": {"format": None, "expect_focus": False, "turns": [
        "Write a cold email to an angel investor for our seed round. We are Example Solar GmbH from Leipzig.",
    ]},
}


PROJECT_NAME = "Example Solar press office"
MEMORY_DIR = ".openmates/memories"


def memory_count(cli: str) -> int:
    listed = command(cli, ["settings", "memories", "list"])
    entries = listed.get("memories", listed.get("entries", [])) if isinstance(listed, dict) else listed
    return len(entries) if isinstance(entries, list) else -1


def project_memory_files(cli: str, project_id: str, out: Path, label: str) -> list[str]:
    """Memory file names under .openmates/memories; the raw listings are kept as receipts."""
    found: set[str] = set()
    for name, args in (("path", ["--path", MEMORY_DIR]), ("tree", ["--depth", "4"])):
        try:
            listed = command(cli, ["projects", "files", "list", project_id, *args],
                             diagnostic_path=out / f"{label}-files-{name}-diagnostic.json")
        except ProofError as exc:
            listed = {"error": str(exc)}
        write_receipt(out / f"{label}-files-{name}.json", listed)
        text = json.dumps(listed)
        found.update(part.split('"')[0].rsplit("/", 1)[-1] for part in re.split(r"(?:\.openmates/)?memories/", text)[1:]
                     if part.split('"')[0].endswith(".md"))
    return sorted(found)


def find_id(value: object) -> str | None:
    """First project id in a CLI JSON reply, whatever wrapper the CLI uses."""
    if isinstance(value, dict):
        for key in ("project_id", "projectId", "id"):
            if isinstance(value.get(key), str) and len(value[key]) >= 8:
                return value[key]
        for nested in value.values():
            found = find_id(nested)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = find_id(item)
            if found:
                return found
    return None


def delete_leftover_projects(cli: str) -> int:
    """Remove this script's own synthetic Project from an earlier interrupted run."""
    listed = command(cli, ["projects", "list"])
    projects = listed.get("projects", []) if isinstance(listed, dict) else listed
    removed = 0
    for project in projects if isinstance(projects, list) else []:
        if isinstance(project, dict) and project.get("name") == PROJECT_NAME:
            project_id = find_id(project)
            if project_id:
                command(cli, ["projects", "delete", project_id, "--confirm", project_id])
                removed += 1
    return removed


def run_project_case(cli: str, label: str, case: dict, out: Path, timeout: int) -> dict:
    """Save the press style to a Project, then reuse it in a second chat of that Project."""
    result: dict = {"label": label, "status": "failed"}
    project_id = None
    try:
        result["leftover_projects_removed"] = delete_leftover_projects(cli)
        created = command(cli, ["projects", "create", PROJECT_NAME, "--write-policy", "apply_and_show"])
        write_receipt(out / f"{label}-project-created.json", created)
        project_id = find_id(created)
        if not isinstance(project_id, str):
            raise ProofError("project_id_missing")
        command(cli, ["projects", "settings", project_id, "--focus-activation", "immediate"])
        personal_before = memory_count(cli)
        save = run_case(cli, f"{label}-save", {**case, "format": None}, out, timeout,
                        project_id=project_id, expect_focus_any=True)
        files = project_memory_files(cli, project_id, out, label)
        memory_text = ""
        for name in files:
            read = command(cli, ["projects", "files", "read", project_id, f"{MEMORY_DIR}/{name}", "--include-ignored"])
            memory_text += json.dumps(read).lower()
        write_receipt(out / f"{label}-project-memories.json", {"files": files})
        result["save"] = save
        result["project_memory_files"] = len(files)
        result["project_memory_has_style"] = "3,000" in memory_text or "3000" in memory_text
        result["personal_memories_unchanged"] = memory_count(cli) == personal_before
        reuse = run_case(cli, f"{label}-reuse", {"format": "word", "turns": case["reuse_turns"]}, out, timeout,
                         project_id=project_id, extra_tokens=["3,000"], expect_focus_any=True)
        result["reuse"] = reuse
        checks = [len(files) >= 1, result["project_memory_has_style"], result["personal_memories_unchanged"],
                  reuse["status"] == "passed"]
        result["status"] = "passed" if all(checks) else "failed"
    except (ProofError, subprocess.TimeoutExpired) as exc:
        result["reason"] = str(exc) if isinstance(exc, ProofError) else "timeout"
    finally:
        if project_id:
            try:
                command(cli, ["projects", "delete", project_id, "--confirm", project_id])
                result["project_deleted"] = True
            except (ProofError, subprocess.TimeoutExpired):
                result["project_deleted"] = False
    return result


def release_text(cli: str, chat_id: str, shown: dict, out: Path, label: str) -> tuple[set[str], str]:
    """Embed types referenced by assistant answers and the lowercased release text."""
    types: set[str] = set()
    parts: list[str] = []
    for message in shown.get("messages", []) if isinstance(shown, dict) else []:
        if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
            continue
        parts.append(message["content"])
        for embed_type, embed_id in EMBED_REF.findall(message["content"]):
            types.add(embed_type)
            try:
                embed = command(cli, ["embeds", "show", embed_id, "--chat", chat_id])
            except ProofError:
                continue
            write_receipt(out / f"{label}-embed-{embed_id[:8]}.json", embed)
            parts.append(json.dumps(embed, ensure_ascii=False))
            # An application keeps its page text in child file embeds (src/App.jsx).
            content = embed.get("content") if isinstance(embed, dict) else None
            for ref in (content or {}).get("file_refs", []) if isinstance(content, dict) else []:
                child_id = ref.get("embed_id") if isinstance(ref, dict) else None
                if not isinstance(child_id, str):
                    continue
                try:
                    child = command(cli, ["embeds", "show", child_id, "--chat", chat_id])
                except ProofError:
                    continue
                write_receipt(out / f"{label}-embed-{child_id[:8]}.json", child)
                parts.append(json.dumps(child, ensure_ascii=False))
    return types, "\n".join(parts).lower()


def run_case(cli: str, label: str, case: dict, out: Path, timeout: int, *, project_id: str | None = None,
             extra_tokens: list[str] | None = None, expect_focus_any: bool = False) -> dict:
    result: dict = {"label": label, "status": "failed", "turns": []}
    chat_id = None
    try:
        for index, prompt in enumerate(case["turns"]):
            args = (["chats", "new", prompt] if chat_id is None else ["chats", "send", "--chat", chat_id, prompt])
            # Like an @Project mention on the web: the new chat is bound to the
            # Project before its first turn, so that turn already loads the Memories.
            if project_id and chat_id is None:
                args += ["--project", project_id]
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
        active_focus = (shown.get("chat") or {}).get("activeFocusId") if isinstance(shown, dict) else None
        result["active_focus"] = active_focus
        activated = active_focus == f"business-{FOCUS}"
        expect_focus = case.get("expect_focus", True)
        # In a Project chat the Project's own focus may stay active; there only the result counts.
        checks = [] if expect_focus_any else [activated is expect_focus]
        if case["format"]:
            types, text = release_text(cli, chat_id, shown, out, label)
            result["embed_types"] = sorted(types)
            result["format_produced"] = bool(types & FORMAT_EMBED_TYPES[case["format"]])
            result["structure_tokens"] = {token: token in text for token in [*STRUCTURE_TOKENS, *(extra_tokens or [])]}
            checks += [result["format_produced"], all(result["structure_tokens"].values())]
        result["status"] = "passed" if all(checks) else "failed"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cli", default="openmates")
    parser.add_argument("--case", action="append", choices=sorted(CASES))
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
        parser.error("openmates CLI executable missing")
    receipt: dict = {"status": "started", "target": API_URL, "session": args.session, "cases": []}
    leases, stop, guard, real_account = [], threading.Event(), None, None
    old_umask = os.umask(0o077)
    try:
        state.mkdir(mode=0o700)
        out.mkdir(mode=0o700, parents=True)
        os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
        for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
            os.environ.pop(key, None)
        # Personal dev test account when free, else a throwaway account for this run.
        import dev_test_account
        real_account = dev_test_account.acquire_real_test_account(
            "press-release-personal", args.session, "press-release", stack_timeout=120)
        login_env, leases = real_account.environment, real_account.leases
        receipt["account_role"] = "personal_dev_test" if real_account.kind == "personal" else "throwaway_dev_test"

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
            runner = run_project_case if CASES[label].get("project") else run_case
            result = runner(cli, label, CASES[label], out, args.timeout_seconds)
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
            account_receipt = dev_test_account.finish_real_test_account(real_account)
            receipt["account_cleanup"] = account_receipt
            if account_receipt.get("lease_release_failed") or account_receipt.get("delete", {}).get("status") == "failed":
                receipt["status"] = "failed"
        shutil.rmtree(state, ignore_errors=True)
        os.umask(old_umask)
        if out.is_dir():
            write_receipt(out / "receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "cases"}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
