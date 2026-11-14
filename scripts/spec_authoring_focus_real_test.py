#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only persona run for the Code "Write specification" focus mode.

Example (after deploying the candidate to dev; paid inference needs opt-in):
  python3 scripts/spec_authoring_focus_real_test.py --session ID --revision SHA \
    --output-dir /tmp/spec-focus-UNIQUE --allow-paid-dev-inference

A realistic persona (a bakery owner, synthetic data) picks the focus explicitly
and talks to it in one CLI chat, from idea to approved Specification to a
started Plan with Tasks. By default the chat runs outside a Project on a
throwaway account (an active Project focus currently blocks app focus
mentions); --in-project uses a disposable Project instead. The persona's replies and the final verdict come from
stateless incognito chats with @Gemini-3.8-Flash, so neither leaves history.
Deterministic checks (focus active, Gemini only, Specification with open
assumptions, Checks, Plan and Tasks only after the approval message) and the
AI judge's rubric must both pass. The chat is recorded with the real CLI, then
this run's chat and Project are deleted, also on failure. Never runs in CI.
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
from datetime import UTC, datetime
from pathlib import Path

from code_run_real_test import command, delete_owned_chat, require_runtime_revision
from personal_dev_draft_guard import DraftGuard, DraftGuardError, record_leftovers
from project_names import natural_project_name
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

ROOT = Path(__file__).resolve().parents[1]
MODEL = "@Gemini-3.8-Flash"
FOCUS_ID = "code-write_specification"
# The user picks the focus explicitly, as when choosing it in the focus picker.
FOCUS_MENTION = "@focus:code:write_specification"
MAX_TURNS = 16
EMBED_REF = re.compile(r'"embed_id":\s*"([0-9a-f-]{36})"')
APPROVAL = re.compile(r"\b(approve|approved|genehmig|freigeb)", re.IGNORECASE)

PERSONA = (
    "Lena Example owns Example Sourdough, a small bakery in Leipzig with three staff (synthetic test persona). "
    "She wants customers to pre-order sourdough loaves online and pick them up, because Saturday queues are long "
    "and she bakes too much or too little. Facts she knows: about 60 loaves on a Saturday, five loaf types, "
    "orders should close at 6 pm the day before pickup, pickup Tuesday to Saturday, card payment online, "
    "her website is a simple site built with a website builder, budget is small, no delivery for now. "
    "She is friendly, busy and not technical; she answers in one to four short sentences, answers only what "
    "she is asked, and says 'I don't know, you decide' for technical details. If the assistant proposes "
    "splitting the work into several Specifications, she says one is enough for her small bakery. She corrects "
    "the assistant once if it assumes something wrong. She says she approves only after the assistant has "
    "shown a drafted Specification and Checks and asked for approval; before that she never uses the word approve."
)
OPENING = (f"{MODEL} {FOCUS_MENTION} Hi! I run a small sourdough bakery in Leipzig. I'd like customers to order bread online "
           "before they come in. Can you help me write a proper spec for that before anyone builds it?")
RUBRIC = {
    "questions_per_turn": "Every assistant turn asks at most three questions, each with a recommendation or example.",
    "phase_summaries_confirmed": "Scope, requirements and design each end with a summary the assistant asks Lena to confirm before moving on.",
    "open_assumptions_explicit": "Summaries keep an explicit 'Open assumptions' list instead of presenting guesses as decisions.",
    "single_spec_default": "One Specification is used unless Lena agreed to a split; any split is proposed with a reason.",
    "approval_before_plan": "No Plan or Tasks are created before Lena approved the drafted Specification and Checks.",
    "specification_quality": "The Specification's requirements are testable, cover Lena's facts and stay within her scope.",
    "checks_cover_requirements": "The acceptance Checks prove the requirements; payment uses a deterministic required source.",
    "handoff_clear": "After approval the assistant creates a Plan with Tasks and explains what happens next.",
}


def chat_reply(cli: str, args: list[str], timeout: int, path: Path) -> dict:
    # No --accept-task-proposals: the hand-off creates Tasks through tasks.create; extracted proposals stay pending.
    reply = command(cli, [*args, "--personal", "--auto-approve",
                          "--response-timeout-seconds", str(timeout)], timeout=timeout + 30, diagnostic_path=path)
    if not isinstance(reply, dict) or reply.get("status") != "completed":
        raise ProofError("chat_turn_not_completed")
    if NO_CREDITS.search(str(reply.get("assistant") or "")):
        raise ProofError("account_out_of_credits")
    return reply


SPEC_REF = re.compile(r'"app_id":\s*"plans",\s*"skill_id":\s*"specification"')
TASKS_REF = re.compile(r'"app_id":\s*"tasks"')
NO_CREDITS = re.compile(r"don't have enough credits", re.IGNORECASE)
ERROR_KEY = re.compile(r"[a-z_]+(\.[a-z_]+)+")


def incognito(cli: str, prompt: str, path: Path) -> str:
    """One stateless reply; a transient provider error (a bare i18n error key) is retried once."""
    for attempt in range(2):
        reply = command(cli, ["chats", "incognito", prompt, "--personal"], timeout=300,
                        diagnostic_path=path.with_name(f"{path.stem}-{attempt}{path.suffix}") if attempt else path)
        text = reply.get("assistant") if isinstance(reply, dict) else None
        if isinstance(text, str) and NO_CREDITS.search(text):
            raise ProofError("account_out_of_credits")
        if isinstance(text, str) and text.strip() and not ERROR_KEY.fullmatch(text.strip()):
            return text.strip()
    raise ProofError("incognito_reply_missing")


def plain(text: str, limit: int) -> str:
    """Assistant text without embed JSON fences or wire mentions, shortened for the persona and the judge."""
    text = re.sub(r"```json\s*\{[^`]*?\"embed_id\"[^`]*?\}\s*```", "[embed]", text)
    # Mentions in quoted text are parsed again by the CLI ("Unknown mention @ai-model:...").
    text = re.sub(r"@(?:ai-model|focus):\S+\s*", "", text.replace(MODEL, "")).strip()
    return text if len(text) <= limit else text[:limit] + " [...]"


def persona_reply(cli: str, history: list[tuple[str, str]], out: Path, turn: int) -> str:
    recent = "\n\n".join(f"{who}: {plain(text, 1800)}" for who, text in history[-6:])
    prompt = (f"{MODEL} Role-play writing exercise, not a request for you to do the task. {PERSONA}\n\n"
              f"Recent conversation between Lena and her assistant:\n\n{recent}\n\n"
              "Write ONLY Lena's next chat message replying to the assistant's last message: plain text, "
              "no quotes, no name prefix, no tools, no headings.")
    text = incognito(cli, prompt, out / f"persona-{turn:02d}.json")
    return text.strip().strip('"').removeprefix("Lena:").strip()


def delete_run_tasks(cli: str, chat_id: str | None, project_id: str | None) -> dict:
    """Delete the Tasks this run's chat or Project created (accepted proposals and hand-off Tasks)."""
    ids: dict[str, None] = {}
    for scope in (["--chat", chat_id] if chat_id else []), (["--project", project_id] if project_id else []):
        if not scope:
            continue
        listed = command(cli, ["tasks", "list", *scope, "--personal", "--json"])
        tasks = listed.get("tasks") if isinstance(listed, dict) else listed
        for task in tasks if isinstance(tasks, list) else []:
            if isinstance(task, dict) and (task.get("id") or task.get("task_id")):
                ids[str(task.get("id") or task.get("task_id"))] = None
    for task_id in ids:
        command(cli, ["tasks", "delete", task_id, "--confirm", "--personal", "--json"])
    return {"deleted": len(ids)}


def classify_embeds(cli: str, chat_id: str, messages: list[dict], out: Path) -> list[dict]:
    """For each assistant message, the plans/tasks skill embeds it references."""
    found = []
    for index, message in enumerate(messages):
        if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
            continue
        for embed_id in dict.fromkeys(EMBED_REF.findall(message["content"])):
            try:
                embed = command(cli, ["embeds", "show", embed_id, "--chat", chat_id, "--personal"])
            except (ProofError, subprocess.TimeoutExpired):
                found.append({"message": index, "embed_id": embed_id, "read_error": True})
                continue
            write_receipt(out / f"embed-{embed_id[:8]}.json", embed)
            content = embed.get("content") if isinstance(embed, dict) and isinstance(embed.get("content"), dict) else {}
            app, skill = content.get("app_id") or content.get("appId"), content.get("skill_id") or content.get("skillId")
            typed = content.get("type") in {"specification", "check", "focus_mode_activation"}
            kind = content.get("type") if typed else f"{app}.{skill}"
            found.append({"message": index, "embed_id": embed_id, "kind": kind,
                          "status": content.get("status") or embed.get("status"), "title": content.get("title"),
                          "requirements": len(content.get("requirements") or []),
                          "assumptions": len(content.get("assumptions") or []),
                          "role": content.get("role") or "",
                          "focus_id": content.get("focus_id") or content.get("focusId")})
    return found


def created_tasks(reply: dict) -> list[str]:
    """Task ids the turn created, from its task events."""
    events = reply.get("taskEvents") if isinstance(reply.get("taskEvents"), list) else []
    return [str(e.get("task_id")) for e in events if isinstance(e, dict) and e.get("event_type") == "created"]


def deterministic_checks(shown: dict, messages: list[dict], embeds: list[dict]) -> dict:
    def first(kinds: set[str]) -> int | None:
        hits = [e["message"] for e in embeds if e.get("kind") in kinds]
        return min(hits) if hits else None

    specs = [e for e in embeds if e.get("kind") in {"specification", "plans.specification"}]
    spec_at = first({"specification", "plans.specification"})
    # Hand-off Tasks arrive as created task events, not always as a tasks.create embed.
    task_events = [i for i, m in enumerate(messages) if m.get("role") == "assistant" and created_tasks(m)]
    handoff = [i for i in (first({"plans.create", "tasks.create"}), *task_events) if i is not None]
    plan_at = min(handoff) if handoff else None
    approvals = [i for i, m in enumerate(messages) if m.get("role") == "user"
                 and isinstance(m.get("content"), str) and APPROVAL.search(m["content"])
                 and spec_at is not None and i > spec_at]
    models = [str(m.get("modelName") or "") for m in messages if m.get("role") == "assistant"]
    chat = shown.get("chat") if isinstance(shown.get("chat"), dict) else {}
    return {
        # The CLI does not expose the encrypted active focus; the activation embed proves it.
        "focus_active": chat.get("activeFocusId") == FOCUS_ID or any(
            e.get("kind") == "focus_mode_activation" and e.get("focus_id") == FOCUS_ID for e in embeds),
        "gemini_only": bool(models) and all("gemini 3.8 flash" in m.lower() for m in models),
        "specification_with_assumptions": any(s.get("status") == "finished" and s["requirements"] >= 3
                                              and s["assumptions"] >= 1 for s in specs),
        "single_specification": len({s.get("title") for s in specs}) == 1 and not any(s.get("role") for s in specs),
        "checks_drafted": any(e.get("kind") in {"check", "plans.check"} and e.get("status") == "finished" for e in embeds),
        "plan_created": first({"plans.create"}) is not None,
        "tasks_created": first({"tasks.create"}) is not None or bool(task_events),
        "approval_before_plan": bool(approvals) and plan_at is not None and min(approvals) < plan_at,
    }


def judge(cli: str, messages: list[dict], embeds: list[dict], out: Path) -> dict:
    lines = []
    for index, message in enumerate(messages):
        if message.get("role") in {"user", "assistant"} and isinstance(message.get("content"), str):
            tags = [f"{e.get('kind')}: {e.get('title') or ''}" for e in embeds if e["message"] == index]
            created = len(created_tasks(message))
            tags += [f"{created} Tasks created"] if created else []
            lines.append(f"[{index}] {message['role'].upper()}: {plain(message['content'], 1200)}"
                         + (f"\n    (embeds created: {'; '.join(tags)})" if tags else ""))
    rubric = "\n".join(f"- {key}: {text}" for key, text in RUBRIC.items())
    prompt = (f"{MODEL} You are a strict reviewer of a product assistant's conversation. Judge ONLY from the "
              f"transcript below. Criteria:\n{rubric}\n\nAnswer with one JSON object in a json code block: "
              '{"criteria": {"<criterion>": {"pass": true|false, "note": "<one sentence>"}}, '
              '"overall_pass": true|false, "summary": "<two sentences>"}. Do not use tools.\n\n'
              "Transcript:\n" + "\n\n".join(lines))
    text = incognito(cli, prompt, out / "judge.json")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        verdict = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        verdict = None
    if not isinstance(verdict, dict) or not isinstance(verdict.get("criteria"), dict):
        raise ProofError("judge_verdict_unparseable")
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cli", default="openmates")
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    parser.add_argument("--in-project", action="store_true",
                        help="run inside a disposable Project; its active Project focus currently blocks app focus "
                             "mentions, so the default runs outside a Project on a throwaway account")
    parser.add_argument("--throwaway-account", action="store_true",
                        help="use a fresh throwaway dev account (gifted dev credits) instead of the personal one")
    args = parser.parse_args()
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        parser.error("real inference is dev-only and cannot run in CI")
    if not args.allow_paid_dev_inference or not 60 <= args.timeout_seconds <= 1200:
        parser.error("explicit paid-dev opt-in and a 60-1200 second timeout required")
    if not args.in_project and not args.throwaway_account:
        parser.error("outside a Project, Plans and Specifications are removed only with the throwaway account")
    out = args.output_dir.resolve()
    if out == Path("/tmp") or not out.is_relative_to(Path("/tmp")) or out.exists():
        parser.error("--output-dir must be a fresh path below /tmp")
    cli = shutil.which(args.cli)
    if not cli:
        parser.error("openmates CLI executable missing")
    out.mkdir(mode=0o700, parents=True)
    state = out / "cli-state"
    receipt: dict = {"status": "started", "target": API_URL, "model": MODEL, "focus": FOCUS_ID,
                     "deployed_revision": args.revision, "started_at": datetime.now(UTC).isoformat(), "cleanup": {}}
    stop, guard, account, project_id, chat_id = threading.Event(), None, None, None, None
    import dev_test_account
    try:
        state.mkdir(mode=0o700)
        os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
        for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
            os.environ.pop(key, None)
        require_runtime_revision(args.revision)
        account = dev_test_account.acquire_real_test_account("spec-focus-personal", args.session,
                                                             "spec-authoring-focus", stack_timeout=120,
                                                             prefer_throwaway=args.throwaway_account)
        receipt["account_role"] = "personal_dev_test" if account.kind == "personal" else "throwaway_dev_test"

        def renew() -> None:
            while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                for lease_id, owner, resources, mode in account.leases:
                    sessions.renew_test_resource_lease(lease_id, owner, resources, mode=mode)

        threading.Thread(target=renew, daemon=True).start()
        login = subprocess.run(["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login", "--slot", "",
                                "--api-url", API_URL], cwd=ROOT, env=account.environment,
                               capture_output=True, text=True, check=False, timeout=180)
        if login.returncode:
            raise ProofError("personal_account_login_failed")
        try:
            guard = DraftGuard.start(cli, api_url=API_URL)
        except DraftGuardError as exc:
            raise ProofError(str(exc)) from exc
        if args.in_project:
            project = command(cli, ["projects", "create", natural_project_name("Sourdough bakery"),
                                    "--write-policy", "apply_and_show", "--personal"])
            project_id = (project.get("project") or {}).get("project_id") if isinstance(project, dict) else None
            if not project_id:
                raise ProofError("disposable_project_missing")
            receipt["project_id"] = project_id
            # Suggested focus modes activate at once, as after accepting the countdown on the web.
            command(cli, ["projects", "settings", project_id, "--focus-activation", "immediate", "--personal"])
        history: list[tuple[str, str]] = []
        # `chats show --all` returns only the latest 20 messages, so the transcript is kept per turn.
        messages: list[dict] = []
        message = OPENING
        for turn in range(1, MAX_TURNS + 1):
            scope = ["--project", project_id] if project_id else []
            base = ["chats", "new", message, *scope] if chat_id is None else \
                ["chats", "send", "--chat", chat_id, message]
            reply = chat_reply(cli, base, args.timeout_seconds, out / f"turn-{turn:02d}.json")
            chat_id = chat_id or reply.get("chatId")
            if not chat_id:
                raise ProofError("created_chat_id_missing")
            receipt["chat_id"] = chat_id
            assistant = str(reply.get("assistant") or "")
            history += [("Lena", plain(message, 4000)), ("Assistant", assistant)]
            messages += [{"role": "user", "content": message},
                         {"role": "assistant", "content": assistant, "modelName": reply.get("modelName"),
                          "taskEvents": reply.get("taskEvents")}]
            print(f"turn {turn}: {plain(assistant, 160)!r}", flush=True)
            spec_seen = any(SPEC_REF.search(m["content"]) for m in messages if m["role"] == "assistant")
            if turn > 2 and spec_seen and (TASKS_REF.search(assistant) or created_tasks(reply)):
                break
            message = f"{MODEL} {persona_reply(cli, history, out, turn)}"
        receipt["turns"] = turn
        shown = command(cli, ["chats", "show", chat_id, "--all", "--personal"])
        write_receipt(out / "chat.json", shown)
        receipt["active_focus_id"] = (shown.get("chat") or {}).get("activeFocusId") if isinstance(shown, dict) else None
        embeds = classify_embeds(cli, chat_id, messages, out)
        receipt["embeds"] = embeds
        receipt["checks"] = deterministic_checks(shown, messages, embeds)
        receipt["judge"] = judge(cli, messages, embeds, out)
        judged = all(isinstance(c, dict) and c.get("pass") is True for c in receipt["judge"]["criteria"].values())
        capture = subprocess.run([sys.executable, str(ROOT / "scripts/cli_video_capture.py"), "--output-dir",
                                  str(out / "terminal"), "--target-environment", API_URL, "--display-number", "198",
                                  "--timeout-seconds", "150", "--no-response-media", "--", cli, "chats", "show",
                                  chat_id, "--all", "--personal", "--api-url", API_URL],
                                 cwd=ROOT, capture_output=True, text=True, check=False, timeout=210)
        write_receipt(out / "capture-diagnostic.json", {"stdout": capture.stdout[-4000:], "stderr": capture.stderr[-4000:]})
        recording = out / "terminal" / "raw-terminal.mp4"
        receipt["recording"] = str(recording) if recording.exists() else "failed"
        require_runtime_revision(args.revision)
        passed = all(receipt["checks"].values()) and judged and receipt["judge"].get("overall_pass") is True
        receipt["status"] = "passed" if passed and recording.exists() else "failed"
    except (ProofError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        receipt["status"] = "failed"
        receipt["error_code"] = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
    finally:
        if chat_id and not (out / "chat.json").exists():
            try:
                write_receipt(out / "chat.json", command(cli, ["chats", "show", chat_id, "--all", "--personal"]))
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"]["chat_snapshot"] = "failed"
        if chat_id or project_id:
            try:
                receipt["cleanup"]["tasks"] = delete_run_tasks(cli, chat_id, project_id)
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"]["tasks"] = "failed"
                receipt["status"] = "failed"
        if chat_id:
            try:
                delete_owned_chat(cli, chat_id)
                receipt["cleanup"]["chat"] = "deleted"
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"]["chat"] = "failed"
                receipt["status"] = "failed"
        if project_id:
            try:
                command(cli, ["projects", "delete", project_id, "--confirm", project_id, "--personal"])
                receipt["cleanup"]["project"] = "deleted"
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"]["project"] = "failed"
                receipt["status"] = "failed"
        record_leftovers(receipt, guard)
        stop.set()
        if account is not None:
            account_receipt = dev_test_account.finish_real_test_account(account)
            receipt["account_cleanup"] = account_receipt
            if account_receipt.get("lease_release_failed") or account_receipt.get("delete", {}).get("status") == "failed":
                receipt["status"] = "failed"
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_receipt(out / "receipt.json", receipt)
        shutil.rmtree(state, ignore_errors=True)
        print(f"spec authoring focus run {receipt['status']}; receipt: {out / 'receipt.json'}", flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
