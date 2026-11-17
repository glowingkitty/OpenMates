# contract-test-file: tooling
"""Chats waiting on the founder: detection, ordering and skips."""

from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402
import daily_meeting_waiting as waiting  # noqa: E402

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def _chat(base, name, rows):
    folder = base / "project"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


def _msg(kind, hours_ago, text, **extra):
    stamp = (NOW - timedelta(hours=hours_ago)).isoformat()
    return {"type": kind, "timestamp": stamp, "message": {"content": text}, **extra}


def _human(hours_ago, text):
    return _msg("user", hours_ago, text, turnOrigin="human")


def test_assistant_last_is_waiting_and_human_last_is_not(tmp_path):
    _chat(tmp_path, "asks", [_human(10, "fix the login"), _msg("assistant", 9, "Which branch do you want?")])
    _chat(tmp_path, "answered", [_msg("assistant", 9, "Done."), _human(8, "thanks, now deploy")])
    result = waiting.waiting_chats(tmp_path, NOW)
    assert [c["session"] for c in result] == ["asks"]
    assert result[0]["signal"] == "asks you a question" and result[0]["idle_hours"] == 9.0


def test_recently_active_archived_and_headless_chats_are_skipped_but_old_ones_stay(tmp_path):
    _chat(tmp_path, "running", [_human(3, "build it"), _msg("assistant", 0.5, "Working on it?")])
    _chat(tmp_path, "old_done", [_human(100, "task"), _msg("assistant", 99, "All finished.")])
    _chat(tmp_path, "archived", [_human(10, "task"), _msg("assistant", 9, "Which one?")])
    _chat(tmp_path, "headless", [_msg("assistant", 9, "automated output")])
    result = waiting.waiting_chats(tmp_path, NOW, reviewed={"archived": "2026-11-06"})
    assert [c["session"] for c in result] == ["old_done"] and result[0]["age_days"] == 4


def test_archived_chat_returns_when_it_speaks_again(tmp_path):
    _chat(tmp_path, "again", [_human(100, "task"), _msg("assistant", 5, "Which one?")])
    assert [c["session"] for c in waiting.waiting_chats(tmp_path, NOW, reviewed={"again": "2026-11-01"})] == ["again"]


def test_questions_rank_before_finished_work_and_task_is_attached(tmp_path):
    _chat(tmp_path, "finished", [_human(6, "x"), _msg("assistant", 5, "Deployed and verified.")])
    _chat(tmp_path, "blocked", [_human(30, "x"), _msg("assistant", 29, "The deploy is blocked and I can't continue.")])
    tasks = [{"id": "TASK-1", "status": "in_progress", "chat": "claude:blocked"}]
    result = waiting.waiting_chats(tmp_path, NOW, tasks)
    assert [c["session"] for c in result] == ["blocked", "finished"]  # same importance: oldest wait first
    assert result[0]["task"] == "TASK-1 (in_progress)"
    done = waiting.waiting_chats(tmp_path, NOW, [{"id": "T", "status": "done", "chat": "claude:blocked"}])
    assert [c["session"] for c in done] == ["finished"]


def test_section_lists_chats_and_handles_none():
    text = "\n".join(briefing._waiting_section({"chats": [{"title": "t", "session": "abcdef123456", "idle_hours": 9.0,
                                                           "signal": "asks you a question", "last_reply": "Which?", "task": ""}]}))
    assert "`abcdef12`" in text and "plus" not in text and "no linked Task" in text
    assert "None" in "\n".join(briefing._waiting_section({}))


def test_plain_title_never_shows_untitled_slug_or_id():
    assert waiting.plain_title("Voice call setup", "x", "y") == "Voice call setup"
    assert waiting.plain_title("untitled", "Why does the upload service stop after a PDF?", "ok") \
        == "Why does the upload service stop after a PDF?"
    assert waiting.plain_title("prod-chat-failures-check", "", "The task failed because the user pressed stop") \
        .startswith("The task failed")
    assert waiting.plain_title("", "", "") == "chat without a title"


def test_waiting_section_shows_plain_title_and_task_title_before_ids():
    chat = {"title": "Projects editing", "session": "97f91b74-f2af", "idle_hours": 5, "task": "TASK-9 (todo)",
            "task_title": "Design Projects editing", "signal": "asks you a question", "last_reply": "Due date?"}
    text = "\n".join(briefing._waiting_section({"chats": [chat]}))
    assert text.index("Projects editing") < text.index("TASK-9") and 'Task "Design Projects editing"' in text
    assert "Needs: Due date?" not in text and "Needs: asks you a question" in text


def test_meeting_script_has_plain_language_rule():
    assert "Plain-language rule" in briefing.MEETING_SCRIPT


def test_waiting_chats_get_a_one_line_plain_summary(monkeypatch):
    chats = {"chats": [{"title": "Fable model", "session": "s1", "idle_hours": 11.0, "task": "", "signal": "asks you a question",
                        "last_reply": "Enable cache billing?"},
                       {"title": "Drafts", "session": "s2", "idle_hours": 20.0, "task": "", "signal": "asks you a question",
                        "last_reply": "Fix both?"}]}
    monkeypatch.setattr(briefing, "_gemini_json", lambda prompt: {"chats": [
        {"session": "s1", "summary": "New model is live;\n it asks whether to bill cached tokens like other models."}]})
    gaps: list[str] = []
    briefing.summarize_waiting(chats, gaps)
    text = "\n".join(briefing._waiting_section(chats))
    assert "_New model is live; it asks whether to bill cached tokens like other models._" in text
    assert "**Drafts** — waited 20 h" in text and gaps == ["1 waiting chat(s) got no one-line summary; they show their last reply only"]


def test_waiting_summary_failure_is_a_data_gap_not_a_crash(monkeypatch):
    def broken(prompt):
        raise RuntimeError("container down")
    monkeypatch.setattr(briefing, "_gemini_json", broken)
    chats, gaps = {"chats": [{"title": "t", "session": "s", "signal": "x", "last_reply": "y"}]}, []
    briefing.summarize_waiting(chats, gaps)
    assert "summary" not in chats["chats"][0] and "container down" in gaps[0]
    briefing.summarize_waiting({}, gaps)
    assert len(gaps) == 1


def test_waiting_section_starts_with_the_chat_lifecycle_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_CHAT_LIFECYCLE_DIR", str(tmp_path))
    assert "unavailable" in "\n".join(briefing._waiting_section({}))
    (tmp_path / "status.json").write_text(json.dumps({
        "at": "2026-11-14T19:30:00Z", "running": 18, "max_running": 20, "working": 5, "idle_running": 13,
        "idle_stopped": 9, "done_to_archive": 3, "archived": 4, "queued_new_chats": 0}))
    text = "\n".join(briefing._waiting_section({}))
    assert "18 running of max 20" in text and "9 idle-stopped" in text and "3 done to archive" in text


def _tasks(*extra):
    return [{"id": "TASK-7", "title": "Resume Projects work", "status": "in_progress", "labels": ["paused"],
             "chat": "claude:p1", "pause": waiting.paused_mod.parse_pause(
                 "PAUSED 2026-11-02 until 2026-11-20 11:00 — usage limit\nDone: schema\nNot done: UI\n"
                 "Next step: wire the list\nOpen decisions: none")}, *extra]


def test_no_cap_and_importance_order_then_age(tmp_path):
    for i in range(15):
        _chat(tmp_path, f"c{i}", [_human(60 + i, "tidy"), _msg("assistant", 50 + i, "Which one?")])
    _chat(tmp_path, "mkt", [_human(5, "x"), _msg("assistant", 4, "Marketing launch copy: approve?")])
    _chat(tmp_path, "proj", [_human(9, "x"), _msg("assistant", 8, "Projects sharing: which default?")])
    _chat(tmp_path, "safe", [_human(7, "x"), _msg("assistant", 6, "Safety appeal flow: ship?")])
    result = waiting.waiting_chats(tmp_path, NOW)
    assert len(result) == 18 and waiting.waiting_summary(result, [], NOW)["chats"] == result
    assert [c["session"] for c in result[:3]] == ["mkt", "proj", "safe"]
    assert result[3]["session"] == "c14"  # oldest of the rest first
    assert result[0]["needs"] == "Marketing launch copy: approve?" and result[0]["priority_topic"] == "marketing"


def test_paused_task_is_listed_in_paused_not_waiting_and_resume_date_is_checked(tmp_path):
    _chat(tmp_path, "p1", [_human(60, "x"), _msg("assistant", 50, "Paused for usage; resume Fri.")])
    result = waiting.waiting_chats(tmp_path, NOW, _tasks())
    assert result == []
    paused = waiting.waiting_summary(result, _tasks(), NOW)["paused"]
    assert paused[0]["resume"] == "2026-11-20" and paused[0]["Next step"] == "wire the list" and not paused[0]["missing"]
    assert "flag" not in paused[0]
    late = waiting.waiting_summary([], _tasks(), datetime(2026, 11, 21, tzinfo=timezone.utc))
    assert "resume date 2026-11-20 has passed" in late["flags"][0]


def test_stale_flag_for_waiting_over_seven_days_and_incomplete_pause(tmp_path):
    _chat(tmp_path, "old", [_human(300, "x"), _msg("assistant", 240, "Which one?")])
    _chat(tmp_path, "new", [_human(20, "x"), _msg("assistant", 10, "Which one?")])
    chats = waiting.waiting_chats(tmp_path, NOW)
    bare = [{"id": "TASK-8", "title": "Bare pause", "status": "todo", "labels": ["paused"], "pause": {}}]
    summary = waiting.waiting_summary(chats, bare, NOW)
    assert sum("waited 10 days" in f for f in summary["flags"]) == 1 and len(summary["flags"]) == 2
    assert summary["paused"][0]["missing"] == ["PAUSED block"] and "no resume date" in summary["flags"][1]


def test_paused_and_flag_sections_render_the_saved_state():
    summary = waiting.waiting_summary([], _tasks(), NOW)
    text = "\n".join(briefing._waiting_section(summary))
    assert "## Paused chats (1)" in text and "resume after **2026-11-20 11:00**" in text
    assert "Next step: wire the list" in text and "No-decision check: no waiting or paused" in text
    empty = "\n".join(briefing._waiting_section({}))
    assert "## Paused chats (0)" in empty and "None to discuss: no chat or Task is paused" in empty


def test_meeting_script_requires_one_outcome_per_chat_and_notes_capture_it():
    script = briefing.MEETING_SCRIPT
    assert "exactly one outcome" in script and "answer now" in script and "reschedule" in script
    assert "-> answer now:" in script and "park until" in script and "| archive |" in script


FOCUS = """# focus
## Current priorities
- marketing and sales: press, launch
- agentic coding: claude code
- Projects: project
Noise: baseten, cache warning

## Current week's goals
"""


def _tri(commits=()):
    import daily_meeting_triage as triage
    return triage.Triage(FOCUS, list(commits), NOW.date())


def test_priorities_and_noise_are_read_from_focus_md_with_a_visible_fallback():
    import daily_meeting_triage as triage
    topics, noise, gap = triage.read_priorities(FOCUS)
    assert [n for n, _ in topics] == ["marketing and sales", "agentic coding", "Projects"] and noise == ("baseten", "cache warning") and not gap
    assert "no 'Current priorities'" in triage.read_priorities("# nothing")[2]


def test_triage_labels_now_later_drop_with_reasons():
    tri = _tri([{"subject": "fix(upload): pdf upload stops after first page"}])
    assert tri.chat({"title": "Press release draft", "needs": "ok?"})["label"] == "NOW"
    assert tri.chat({"title": "Tidy icons", "needs": "which?", "signal": "asks you a question"}) == {
        "label": "LATER", "reason": "fits no current priority, still useful", "date": "2026-11-13"}
    assert tri.chat({"title": "Tidy icons", "needs": "", "signal": "reports it is done"})["label"] == "DROP"
    assert tri.chat({"title": "Baseten provider", "needs": "keep?"})["reason"] == "noise (baseten)"
    assert tri.chat({"title": "Payment failed for a user"})["label"] == "NOW"
    assert tri.task({"title": "Old idea", "status": "backlog", "priority": "none"})["label"] == "DROP"
    assert tri.task({"title": "Rate limits", "status": "todo", "priority": "high"})["label"] == "NOW"
    assert tri.paused({"resume": "2026-11-20", "flag": ""}) == {"label": "LATER", "reason": "paused, state saved", "date": "2026-11-20"}
    assert tri.paused({"resume": "2026-11-01", "resume_due": True})["label"] == "NOW"
    assert tri.reminder({"title": "Call the dentist", "list": "Personal Tasks"}, NOW.date())["reason"] == "due today"


def test_errors_and_reports_follow_the_triage_rule_and_likely_fixed_issues_are_side_notes():
    tri = _tri([{"subject": "fix(upload): pdf upload stops after first page"}])
    assert tri.error("dev", {"service": "api", "message": "boom"})["reason"] == "dev-only error"
    assert tri.error("production", {"service": "api", "message": "cache warning x"})["reason"] == "noise (cache warning)"
    assert tri.error("production", {"service": "api", "message": "stream failed"})["label"] == "NOW"
    fixed = tri.issue("production", {"title": "PDF upload stops after the first page", "processed": False})
    assert fixed["label"] == "LATER" and "likely fixed" in fixed["reason"]
    assert tri.issue("production", {"title": "Cannot open settings", "processed": False})["label"] == "NOW"
    assert tri.issue("production", {"title": "Cannot open settings", "processed": True})["label"] == "LATER"


def test_sections_show_now_only_and_side_notes_collect_the_rest_once():
    tri = _tri()
    chats = [{"title": "Press release", "session": "s1", "idle_hours": 5.0, "needs": "ok?", "signal": "asks you a question", "task": ""},
             {"title": "Tidy icons", "session": "s2", "idle_hours": 9.0, "needs": "which?", "signal": "asks you a question", "task": ""}]
    text = "\n".join(briefing._waiting_section({"chats": chats}, tri))
    assert "(1 NOW of 2" in text and "Press release" in text and "Tidy icons" not in text and "[NOW: serves marketing and sales]" in text
    tri.keep("Chat", "Tidy icons (waited 9 h)", tri.chat(chats[1]))  # same item again: still one note
    side = "\n".join(briefing.triage.side_note_lines(tri.notes, "gap text"))
    assert side.count("Tidy icons") == 1 and "**LATER 2026-11-13**" in side and "Triage gap: gap text" in side
    assert "Nothing: every item is NOW" in "\n".join(briefing.triage.side_note_lines([]))


def test_meeting_script_has_the_triage_rule_and_decisions_record_labels():
    script = briefing.MEETING_SCRIPT
    assert "Triage rule" in script and "Talk through NOW items only" in script and "Side notes" in script
    assert "Triage (labels the founder CHANGED" in script and "<NOW|LATER YYYY-MM-DD|DROP> <chat title>" in script
