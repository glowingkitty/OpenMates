# contract-test-file: tooling
"""Chat lifecycle rules of scripts/claude_idle_chats.py: idle stop, done, cap, held prompts.

Run: python3 -m pytest scripts/tests/test_claude_idle_chats.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import claude_idle_chats as lc  # noqa: E402  (path set above)

NOW = 1_800_000_000.0
HOUR = 3600
CONFIG = dict(lc.DEFAULTS)
MCP = ["npm exec @remotion/mcp@latest", "node /opt/bin/figma-developer-mcp --stdio"]


def chat(**overrides) -> lc.Chat:
    values = dict(pid=1, session_id="chat-a", name="openmates-aa", status="idle", kind="pane",
                  last_activity=NOW - 2 * HOUR, children=list(MCP), last_speaker="assistant",
                  last_text="Deployed to dev in commit abc123. The Task is marked Done.")
    values.update(overrides)
    return lc.Chat(**values)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def test_idle_finished_chat_is_stopped_after_the_idle_limit_and_done_after_a_day():
    assert lc.decide(chat(), NOW, CONFIG, "other").action == "stop"
    assert lc.decide(chat(last_activity=NOW - 30 * HOUR), NOW, CONFIG, "other").action == "done"
    assert lc.decide(chat(last_activity=NOW - 50 * 60), NOW, CONFIG, "other").action == "keep"


def test_idle_limit_and_pressure_limit_are_configurable():
    config = dict(CONFIG, idle_stop_minutes=180)
    assert lc.decide(chat(), NOW, config, "other").action == "keep"
    assert lc.decide(chat(), NOW, config, "other", idle_minutes=15).action == "stop"


@pytest.mark.parametrize(("overrides", "fragment"), [
    ({"status": "busy"}, "state is busy"),
    ({"status": "waiting", "waiting_for": "permission"}, "state is waiting"),
    ({"waiting_for": "input needed"}, "waits for"),
    ({"children": [*MCP, "/bin/bash -c cargo test"]}, "background process"),
    ({"kind": "terminal"}, "not a managed chat"),
    ({"last_speaker": "user", "last_text": "please fix it"}, "no reply"),
    ({"last_speaker": "user", "last_text": lc.REFUSED_PREFIX + ":\nBLOCKED"}, "no reply"),
])
def test_hard_rules_keep_the_chat_even_after_days(overrides, fragment):
    decision = lc.decide(chat(last_activity=NOW - 72 * HOUR, **overrides), NOW, CONFIG, "other")
    assert decision.action == "keep" and decision.hard and fragment in decision.reason


def test_own_chat_is_never_stopped():
    assert not lc.decide(chat(last_activity=NOW - 72 * HOUR), NOW, CONFIG, own_session_id="chat-a").close


@pytest.mark.parametrize("text", [
    "Recommendation: approve it.\n\nShould I approve and deploy it as written?\n\nThe report is in /tmp/report.md.",
    "Project Memory: still waiting on your answer about creating the Project.",
    "Workflows are on in production. Decide whether they appear in this one.",
    "Reply **OK** (or with changes) and I'll start.",
])
def test_open_questions_anywhere_near_the_end_keep_the_chat(text):
    assert lc.asks_something(text)
    assert lc.decide(chat(last_activity=NOW - 30 * HOUR, last_text=text), NOW, CONFIG, "other").action == "keep"


def test_urls_and_code_spans_with_question_marks_are_not_questions():
    assert not lc.asks_something("Done: see https://example.org/a?b=1 and `x ? y : z`. Task marked Done.")


def test_cap_suspends_longest_idle_first_and_never_breaks_hard_rules():
    config = dict(CONFIG, max_running=3)
    chats = [
        chat(session_id="busy", status="busy", last_activity=NOW - 9 * HOUR),
        chat(session_id="old", last_activity=NOW - 5 * HOUR),
        chat(session_id="recent", last_activity=NOW - 5 * 60),
        chat(session_id="mid", last_activity=NOW - 2 * HOUR),
        chat(session_id="held", last_speaker="user", last_text=lc.REFUSED_PREFIX, last_activity=NOW - 8 * HOUR),
    ]
    victims = lc.cap_victims(chats, NOW, config, "other")
    assert [victim.session_id for victim in victims] == ["old", "mid"]
    assert [victim.session_id for victim in lc.cap_victims(chats, NOW, config, "other", room=1)] == ["old", "mid"]
    assert lc.cap_victims(chats[:3], NOW, config, "other") == []


def test_cap_suspends_open_question_chats_last_and_only_after_hours_without_answer():
    config = dict(CONFIG, max_running=1)
    asking = "Should I deploy it?"
    chats = [chat(session_id="q-old", last_text=asking, last_activity=NOW - 6 * HOUR),
             chat(session_id="q-new", last_text=asking, last_activity=NOW - 1 * HOUR),
             chat(session_id="plain", last_activity=NOW - 20 * 60)]
    assert [victim.session_id for victim in lc.cap_victims(chats, NOW, config, "other")] == ["plain", "q-old"]


def test_last_turn_skips_compaction_summaries_and_tool_results_and_sees_refusals():
    records = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "All done."}]}},
        {"type": "user", "isCompactSummary": True, "message": {"content": "Summary of the conversation"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
    ]
    assert lc.last_turn(records) == ("assistant", "All done.")
    refused = {"type": "system", "subtype": "informational", "content": lc.REFUSED_PREFIX + ":\nBLOCKED: x"}
    assert lc.last_turn([*records, refused])[0] == "user"


def test_activity_comes_from_record_timestamps_not_file_mtime(tmp_path):
    """Claude Code rewrites idle transcripts in place; a fresh mtime must not look like activity."""
    project = tmp_path / "projects" / "-home-x"
    project.mkdir(parents=True)
    old = NOW - 30 * HOUR
    lines = [
        {"type": "user", "timestamp": iso(old - 60), "message": {"content": "do it"}},
        {"type": "assistant", "timestamp": iso(old), "message": {"content": [{"type": "text", "text": "Done."}]}},
        {"type": "system", "subtype": "bridge_status", "timestamp": iso(NOW - 60), "content": "reconnected"},
        {"type": "bridge-session", "bridgeSessionId": "cse_x", "lastSequenceNum": 0},
    ]
    transcript = project / "chat-a.jsonl"
    transcript.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    os.utime(transcript, (NOW, NOW))
    newest, speaker, text = lc.transcript_state(tmp_path, "chat-a")
    assert newest == pytest.approx(old) and speaker == "assistant" and text == "Done."


def test_subagent_transcripts_count_as_activity(tmp_path):
    project = tmp_path / "projects" / "-home-x"
    (project / "chat-a" / "subagents").mkdir(parents=True)
    (project / "chat-a.jsonl").write_text(json.dumps({"type": "assistant", "timestamp": iso(NOW - 9 * HOUR)}) + "\n")
    (project / "chat-a" / "subagents" / "agent-1.jsonl").write_text(
        json.dumps({"type": "assistant", "timestamp": iso(NOW - 600)}) + "\n")
    assert lc.transcript_state(tmp_path, "chat-a")[0] == pytest.approx(NOW - 600)


def test_classify_covers_remote_control_workers_and_zellij_panes_only():
    sessions = ["claude", "other"]
    worker = ["claude", "--sdk-url", "https://claude.ai/v1/code/sessions/abc"]
    assert lc.classify(worker, {}, sessions) == "rc_worker"
    pane = {"ZELLIJ_PANE_ID": "47", "ZELLIJ_SESSION_NAME": "claude"}
    assert lc.classify(["claude", "--remote-control", "T"], pane, sessions) == "pane"
    assert lc.classify(["claude"], {**pane, "ZELLIJ_SESSION_NAME": "my-own"}, sessions) == "terminal"
    assert lc.classify(["claude"], {}, sessions) == "terminal"


def test_registry_forgets_resumed_chats_and_marks_old_stops_done():
    registry = {
        "back": {"state": "stopped", "last_activity": iso(NOW - 2 * HOUR)},
        "old": {"state": "stopped", "last_activity": iso(NOW - 30 * HOUR)},
        "fresh": {"state": "stopped", "last_activity": iso(NOW - 2 * HOUR)},
    }
    lc.refresh_registry(registry, [chat(session_id="back")], NOW, CONFIG)
    assert set(registry) == {"old", "fresh"}
    assert registry["old"]["state"] == "done" and registry["fresh"]["state"] == "stopped"


def test_counts_split_working_idle_stopped_done_and_archived():
    registry = {"a": {"state": "stopped"}, "b": {"state": "done"}, "c": {"state": "archived"}}
    live = [chat(status="busy"), chat(session_id="b2", last_activity=NOW - 60), chat(session_id="c2")]
    summary = lc.counts(live, registry, NOW, CONFIG, "other", queued=2)
    assert (summary["running"], summary["working"], summary["idle_running"]) == (3, 2, 1)
    assert (summary["idle_stopped"], summary["done_to_archive"], summary["archived"]) == (1, 1, 1)
    assert summary["queued_new_chats"] == 2 and summary["max_running"] == 20
    assert "3 running of max 20" in lc.status_line(summary)


def test_config_file_overrides_defaults_and_rejects_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"idle_stop_minutes": 90, "max_running": 25}))
    config = lc.load_config(path)
    assert config["idle_stop_minutes"] == 90 and config["max_running"] == 25 and config["done_hours"] == 24
    path.write_text(json.dumps({"idle_minutes": 5}))
    with pytest.raises(SystemExit, match="unknown settings"):
        lc.load_config(path)


def test_mark_records_archived_and_resumed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_CHAT_LIFECYCLE_DIR", str(tmp_path))
    lc.save_registry(tmp_path, {"x": {"state": "done", "last_activity": iso(NOW)}})
    assert lc.mark("x", "archived") == 0
    assert lc.load_registry(tmp_path)["x"]["state"] == "archived"
    assert lc.mark("x", "resumed") == 0
    assert lc.load_registry(tmp_path) == {}


def test_held_prompt_detection_reads_the_input_box():
    screen = "  some reply text\n────────\n❯ [Pasted text #4]\n────────\n  auto mode on\n"
    assert lc.input_line(screen) == "[Pasted text #4]"
    assert lc.input_line("output\n❯ \n") == ""
    held = chat(last_speaker="user", last_text=lc.REFUSED_PREFIX + ": BLOCKED")
    typed = chat(session_id="b", last_speaker="user", last_text="please continue")
    worker = chat(session_id="c", kind="rc_worker", last_speaker="user", last_text=lc.REFUSED_PREFIX)
    assert [item.session_id for item in lc.held_prompts([typed, held, worker])] == ["chat-a"]


def test_release_presses_enter_only_when_the_refused_prompt_is_still_typed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_CHAT_LIFECYCLE_DIR", str(tmp_path))
    held = [chat(session_id="full", pane_id="41", zellij_session="claude", last_speaker="user",
                 last_text=lc.REFUSED_PREFIX, last_activity=NOW - 3 * HOUR),
            chat(session_id="empty", pane_id="42", zellij_session="claude", last_speaker="user",
                 last_text=lc.REFUSED_PREFIX, last_activity=NOW - 2 * HOUR)]
    monkeypatch.setattr(lc, "live_chats", lambda home, config: held)
    calls = []

    def fake_zellij(session, *args):
        calls.append(args)
        text = "❯ [Pasted text #1]\n" if args[-1] == "terminal_41" else "❯ \n"
        return type("Result", (), {"returncode": 0, "stdout": text, "stderr": ""})()

    monkeypatch.setattr(lc, "zellij", fake_zellij)
    assert lc.release(tmp_path, CONFIG, limit=5) == 0
    assert ("write", "--pane-id", "terminal_41", "13") in calls
    assert not any(call[0] == "write" and call[2] == "terminal_42" for call in calls)
    events = (tmp_path / "events.jsonl").read_text()
    assert "held_prompt_released" in events and "held_prompt_lost" in events
