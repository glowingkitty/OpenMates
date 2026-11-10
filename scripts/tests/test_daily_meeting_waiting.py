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


def test_recently_active_old_done_and_dismissed_chats_are_skipped(tmp_path):
    _chat(tmp_path, "running", [_human(3, "build it"), _msg("assistant", 0.5, "Working on it?")])
    _chat(tmp_path, "old_done", [_human(100, "task"), _msg("assistant", 99, "All finished.")])
    _chat(tmp_path, "dismissed", [_human(10, "task"), _msg("assistant", 9, "Which one?")])
    _chat(tmp_path, "headless", [_msg("assistant", 9, "automated output")])
    result = waiting.waiting_chats(tmp_path, NOW, reviewed={"dismissed": "2026-11-05"})
    assert result == []


def test_questions_rank_before_finished_work_and_task_is_attached(tmp_path):
    _chat(tmp_path, "finished", [_human(6, "x"), _msg("assistant", 5, "Deployed and verified.")])
    _chat(tmp_path, "blocked", [_human(30, "x"), _msg("assistant", 29, "The deploy is blocked and I can't continue.")])
    tasks = [{"id": "TASK-1", "status": "in_progress", "chat": "claude:blocked"}]
    result = waiting.waiting_chats(tmp_path, NOW, tasks)
    assert [c["session"] for c in result] == ["blocked", "finished"]
    assert result[0]["task"] == "TASK-1 (in_progress)"
    done = waiting.waiting_chats(tmp_path, NOW, [{"id": "T", "status": "done", "chat": "claude:blocked"}])
    assert [c["session"] for c in done] == ["finished"]


def test_section_lists_chats_and_handles_none():
    text = "\n".join(briefing._waiting_section({"chats": [{"title": "t", "session": "abcdef123456", "idle_hours": 9.0,
                                                           "signal": "asks you a question", "last_reply": "Which?", "task": ""}],
                                                "omitted": 2}))
    assert "`abcdef12`" in text and "plus 2 more" in text
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
    assert "**Fable model** — _New model is live; it asks whether to bill cached tokens like other models._ (idle" in text
    assert "**Drafts** (idle 20.0 h" in text and gaps == ["1 waiting chat(s) got no one-line summary; they show their last reply only"]


def test_waiting_summary_failure_is_a_data_gap_not_a_crash(monkeypatch):
    def broken(prompt):
        raise RuntimeError("container down")
    monkeypatch.setattr(briefing, "_gemini_json", broken)
    chats, gaps = {"chats": [{"title": "t", "session": "s", "signal": "x", "last_reply": "y"}]}, []
    briefing.summarize_waiting(chats, gaps)
    assert "summary" not in chats["chats"][0] and "container down" in gaps[0]
    briefing.summarize_waiting({}, gaps)
    assert len(gaps) == 1
