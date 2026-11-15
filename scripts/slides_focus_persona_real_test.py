#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only beginner persona run for the Slides "Plan a presentation" focus mode.

Example (after deploying the candidate to dev; paid inference needs opt-in):
  python3 scripts/slides_focus_persona_real_test.py --session ID --revision SHA \
    --output-dir /tmp/slides-focus-UNIQUE --allow-paid-dev-inference --throwaway-account

A 16-year-old student with no presentation experience (synthetic persona) must
pitch a school hackathon project in five minutes. She picks the focus explicitly
and talks to it in one CLI chat until a deck with speaker notes exists and was
reviewed. Persona replies and the verdict come from stateless incognito chats
with @Gemini-3.8-Flash. Deterministic checks (focus active, Gemini only, goal and
audience asked first, outline confirmed before the deck, >= 5 slides all with
speaker notes, review step afterwards) and the judge rubric must both pass.
The full transcript and the CLI recording path are saved in the receipt; the
run's chat is deleted also on failure. Never runs in CI.
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
from spec_authoring_focus_real_test import (EMBED_REF, MODEL, chat_reply, delete_run_tasks, incognito,
                                            plain)
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

ROOT = Path(__file__).resolve().parents[1]
FOCUS_ID = "slides-plan_presentation"
FOCUS_MENTION = "@focus:slides:plan_presentation"
MAX_TURNS = 14
REVIEW_TURNS_AFTER_DECK = 2
SLIDE_OPEN = re.compile(r"<slide[\s>]")
NOTES = re.compile(r"<notes>\s*\S")
FENCE = re.compile(r"```slides\s*\n(.*?)(?:```|\Z)", re.DOTALL)
CONFIRM = re.compile(r"\b(yes|yeah|yep|ok|okay|sounds good|looks good|good|fine|perfect|go|do it|make it|"
                     r"create|nice|cool|works|let's)\b", re.IGNORECASE)
TOPIC = re.compile(r"\b(goal|audience|who|judges|jury|teacher|listen|purpose|present(ing)? to|for whom)\b",
                   re.IGNORECASE)
OUTLINE = re.compile(r"(^\s*(?:\d+[.)]|[-*])\s+\S.*\n){4,}|outline", re.IGNORECASE | re.MULTILINE)
REVIEW = re.compile(r"\b(review|feedback|change|adjust|improve|too (long|much)|rehears|practice|notes|what do you think|"
                    r"anything)\b", re.IGNORECASE)

PERSONA = (
    "Mia Example is 16 and has never built a presentation (synthetic test persona). Her school hackathon needs a "
    "5-minute pitch of her team's project: an app that helps students find study partners (matching by subject, "
    "free time and learning style; a prototype exists; the team has three people). She has a vague idea of Canva "
    "and feels lost. She writes short, unsure, casual messages of one or two sentences, sometimes with "
    "lowercase and 'idk' or 'hm'. She answers only what she is asked and never volunteers structure. "
    "At least once she asks what a word the assistant used means (for example 'what is an audience hook' or "
    "'what do you mean by call to action'). The judges are teachers and a few local founders. She does not "
    "say yes to an outline before the assistant has actually shown one; once an outline is shown, she confirms "
    "it casually (for example 'ok looks good, make the slides') unless something is clearly off. When she sees the "
    "finished slides she gives one small piece of feedback, then says thanks."
)
OPENING = (f"{MODEL} {FOCUS_MENTION} hi, i have to present our hackathon project in 5 minutes next week "
           "and i have no idea how to start with slides")
RUBRIC = {
    "beginner_language": "The assistant uses simple, friendly language suited to a 16-year-old beginner, no jargon left unexplained.",
    "questions_per_turn": "Every assistant turn asks one to three questions, each with a recommendation or example.",
    "explains_terms": "When Mia asks what a word means, the assistant explains it simply and carries on.",
    "story_arc": "The outline is a sensible 5-minute pitch arc (problem, idea, how it works, proof or next steps, ask) that fits the time.",
    "no_walls_of_text": "No assistant turn overwhelms Mia with a wall of text or a long questionnaire.",
    "speaker_notes_helpful": "The speaker notes tell Mia in plain words what to say and are not just a copy of the slide.",
    "review_step": "After the deck the assistant invites feedback or offers practice tips and handles Mia's feedback sensibly.",
}


def deck_texts(cli: str, chat_id: str, messages: list[dict], out: Path) -> list[dict]:
    """Slides markup per assistant message: from ```slides fences and from referenced embeds' stored content."""
    found = []
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content") or ""
        sources = [("fence", m) for m in FENCE.findall(content)]
        for embed_id in dict.fromkeys(EMBED_REF.findall(content)):
            try:
                embed = command(cli, ["embeds", "show", embed_id, "--chat", chat_id, "--personal"])
            except (ProofError, subprocess.TimeoutExpired):
                found.append({"message": index, "source": embed_id, "read_error": True})
                continue
            write_receipt(out / f"embed-{embed_id[:8]}.json", embed)
            stored = embed.get("content") if isinstance(embed, dict) and isinstance(embed.get("content"), dict) else {}
            if stored.get("type") == "focus_mode_activation":
                # The CLI does not expose the encrypted active focus; the activation embed proves it.
                found.append({"message": index, "source": embed_id, "activation": stored.get("focus_id")})
                continue
            body = json.dumps(embed.get("content") if isinstance(embed, dict) else embed, ensure_ascii=False)
            sources.append((f"embed:{embed_id[:8]}", body))
        for source, text in sources:
            slides = SLIDE_OPEN.split(text)[1:]
            if slides:
                found.append({"message": index, "source": source, "slides": len(slides),
                              "with_notes": sum(1 for s in slides if NOTES.search(s))})
    return found


def deterministic_checks(shown: dict, messages: list[dict], decks: list[dict]) -> dict:
    chat = shown.get("chat") if isinstance(shown.get("chat"), dict) else {}
    assistants = [(i, m) for i, m in enumerate(messages) if m.get("role") == "assistant"]
    valid = [d for d in decks if not d.get("read_error") and "activation" not in d]
    deck_at = min((d["message"] for d in valid), default=None)
    best = max(valid, key=lambda d: d["slides"], default=None)
    outline_at = next((i for i, m in assistants if OUTLINE.search(plain(m["content"], 6000))
                       and (deck_at is None or i < deck_at)), None)
    first = plain(assistants[0][1]["content"], 4000) if assistants else ""
    models = [str(m.get("modelName") or "") for _, m in assistants]
    confirmed = (outline_at is not None and deck_at is not None and any(
        m.get("role") == "user" and outline_at < i < deck_at and CONFIRM.search(plain(m["content"], 600))
        for i, m in enumerate(messages)))
    review = deck_at is not None and any(i > deck_at and REVIEW.search(plain(m["content"], 3000))
                                         for i, m in assistants)
    review = review or (deck_at is not None and REVIEW.search(plain(messages[deck_at]["content"].split("```")[-1], 3000))
                        is not None and any(m.get("role") == "user" and i > deck_at for i, m in enumerate(messages)))
    return {
        # The CLI does not expose the encrypted active focus in every build; the activation embed proves it.
        "focus_active": chat.get("activeFocusId") == FOCUS_ID
                        or any(d.get("activation") == FOCUS_ID for d in decks),
        "gemini_only": bool(models) and all("gemini 3.8 flash" in m.lower() for m in models),
        "goal_audience_asked_first": "?" in first and TOPIC.search(first) is not None
                                     and not OUTLINE.search(first) and not decks_in(messages[:2]),
        "outline_shown_before_deck": outline_at is not None,
        "deck_only_after_confirmed_outline": confirmed,
        "deck_has_5_slides": best is not None and best["slides"] >= 5,
        "every_slide_has_notes": best is not None and best["slides"] > 0 and best["with_notes"] == best["slides"],
        "review_after_deck": bool(review),
    }


def decks_in(messages: list[dict]) -> bool:
    return any(FENCE.search(m.get("content") or "") for m in messages)


def persona_reply(cli: str, history: list[tuple[str, str]], out: Path, turn: int) -> str:
    recent = "\n\n".join(f"{who}: {plain(text, 2000)}" for who, text in history[-6:])
    prompt = (f"{MODEL} Role-play writing exercise, not a request for you to do the task. {PERSONA}\n\n"
              f"Recent conversation between Mia and her assistant:\n\n{recent}\n\n"
              "Write ONLY Mia's next chat message replying to the assistant's last message: plain text, "
              "no quotes, no name prefix, no tools, no headings.")
    text = incognito(cli, prompt, out / f"persona-{turn:02d}.json")
    return text.strip().strip('"').removeprefix("Mia:").strip()


def judge(cli: str, messages: list[dict], decks: list[dict], out: Path) -> dict:
    lines = []
    for index, message in enumerate(messages):
        if message.get("role") in {"user", "assistant"} and isinstance(message.get("content"), str):
            tags = [f"deck {d['slides']} slides, {d['with_notes']} with notes" for d in decks
                    if d["message"] == index and not d.get("read_error")]
            lines.append(f"[{index}] {message['role'].upper()}: {plain(message['content'], 2500)}"
                         + (f"\n    (created: {'; '.join(tags)})" if tags else ""))
    rubric = "\n".join(f"- {key}: {text}" for key, text in RUBRIC.items())
    prompt = (f"{MODEL} You are a strict reviewer of a product assistant's conversation with a teenage beginner. "
              f"Judge ONLY from the transcript below. Criteria:\n{rubric}\n\nAnswer with one JSON object as plain "
              'text, without a code block: {"criteria": {"<criterion>": {"pass": true|false, "note": "<one sentence>"}}, '
              '"overall_pass": true|false, "summary": "<two sentences>"}. Do not use tools.\n\n'
              "Transcript:\n" + "\n\n".join(lines))
    text = incognito(cli, prompt, out / "judge.json", response_timeout=600)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        verdict = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        verdict = None
    if not isinstance(verdict, dict) or not isinstance(verdict.get("criteria"), dict):
        raise ProofError("judge_verdict_unparseable")
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cli", default="openmates")
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    parser.add_argument("--throwaway-account", action="store_true",
                        help="use a fresh throwaway dev account (gifted dev credits) instead of the personal one")
    args = parser.parse_args()
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        parser.error("real inference is dev-only and cannot run in CI")
    if not args.allow_paid_dev_inference or not 60 <= args.timeout_seconds <= 1200:
        parser.error("explicit paid-dev opt-in and a 60-1200 second timeout required")
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
    stop, guard, account, chat_id = threading.Event(), None, None, None
    import dev_test_account
    try:
        state.mkdir(mode=0o700)
        os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
        for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
            os.environ.pop(key, None)
        require_runtime_revision(args.revision)
        account = dev_test_account.acquire_real_test_account("slides-focus-personal", args.session,
                                                             "slides-focus-persona", stack_timeout=120,
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
        history: list[tuple[str, str]] = []
        messages: list[dict] = []  # `chats show --all` returns only the latest 20, so keep the transcript per turn
        message, deck_turn = OPENING, None
        for turn in range(1, MAX_TURNS + 1):
            base = ["chats", "new", message] if chat_id is None else ["chats", "send", "--chat", chat_id, message]
            reply = chat_reply(cli, base, args.timeout_seconds, out / f"turn-{turn:02d}.json")
            chat_id = chat_id or reply.get("chatId")
            if not chat_id:
                raise ProofError("created_chat_id_missing")
            receipt["chat_id"] = chat_id
            assistant = str(reply.get("assistant") or "")
            history += [("Mia", plain(message, 4000)), ("Assistant", assistant)]
            messages += [{"role": "user", "content": message},
                         {"role": "assistant", "content": assistant, "modelName": reply.get("modelName")}]
            print(f"turn {turn}: {plain(assistant, 160)!r}", flush=True)
            if deck_turn is None and (FENCE.search(assistant) or EMBED_REF.search(assistant)):
                deck_turn = turn
            if deck_turn is not None and turn >= deck_turn + REVIEW_TURNS_AFTER_DECK:
                break
            message = f"{MODEL} {persona_reply(cli, history, out, turn)}"
        receipt["turns"] = turn
        receipt["transcript"] = [{"role": m["role"], "content": m["content"]} for m in messages]
        write_receipt(out / "transcript.json", receipt["transcript"])
        shown = command(cli, ["chats", "show", chat_id, "--all", "--personal"])
        write_receipt(out / "chat.json", shown)
        receipt["active_focus_id"] = (shown.get("chat") or {}).get("activeFocusId") if isinstance(shown, dict) else None
        decks = deck_texts(cli, chat_id, messages, out)
        receipt["decks"] = decks
        receipt["checks"] = deterministic_checks(shown, messages, decks)
        capture = subprocess.run([sys.executable, str(ROOT / "scripts/cli_video_capture.py"), "--output-dir",
                                  str(out / "terminal"), "--target-environment", API_URL, "--display-number", "198",
                                  "--timeout-seconds", "150", "--no-response-media", "--", cli, "chats", "show",
                                  chat_id, "--all", "--personal", "--api-url", API_URL],
                                 cwd=ROOT, capture_output=True, text=True, check=False, timeout=210)
        write_receipt(out / "capture-diagnostic.json", {"stdout": capture.stdout[-4000:], "stderr": capture.stderr[-4000:]})
        recording = out / "terminal" / "raw-terminal.mp4"
        receipt["recording"] = str(recording) if recording.exists() else "failed"
        receipt["judge"] = judge(cli, messages, decks, out)
        judged = all(isinstance(c, dict) and c.get("pass") is True for c in receipt["judge"]["criteria"].values())
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
        if chat_id:
            try:
                receipt["cleanup"]["tasks"] = delete_run_tasks(cli, chat_id, None)
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"]["tasks"] = "failed"
                receipt["status"] = "failed"
            try:
                delete_owned_chat(cli, chat_id)
                receipt["cleanup"]["chat"] = "deleted"
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"]["chat"] = "failed"
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
        print(f"slides focus persona run {receipt['status']}; receipt: {out / 'receipt.json'}", flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
