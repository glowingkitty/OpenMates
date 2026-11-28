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


@pytest.fixture(autouse=True)
def no_host_usage_state(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_USAGE_GUARD_DIR", str(tmp_path / "usage-guard"))


def chat(**overrides) -> lc.Chat:
    values = dict(pid=1, session_id="chat-a", name="openmates-aa", status="idle", kind="pane",
                  last_activity=NOW - 2 * HOUR, children=list(MCP), last_speaker="assistant",
                  last_text="Deployed to dev in commit abc123. The Task is marked Done.")
    values.update(overrides)
    return lc.Chat(**values)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def test_a_finished_turn_releases_its_slot_within_minutes_only_when_done_asked_or_waiting():
    """Owner, 2026-11-20: idle chats held 13 of 20 slots. Owner, 2026-11-21 (TASK-7707): a chat is
    closed only when it reported done, asked or registered a waiter; any other turn end is woken."""
    done = dict(pushed_done="done")
    assert lc.decide(chat(**done), NOW, CONFIG, "other").action == "archive"
    assert lc.decide(chat(last_activity=NOW - 5 * 60, **done), NOW, CONFIG, "other").action == "archive"
    assert lc.decide(chat(last_activity=NOW - 2 * 60, **done), NOW, CONFIG, "other").action == "keep"  # just ended
    assert lc.decide(chat(), NOW, CONFIG, "other").action == "continue"  # no ✅: never closed
    assert lc.decide(chat(last_activity=NOW - 30 * HOUR), NOW, CONFIG, "other").action == "continue"


def test_idle_limit_and_pressure_limit_are_configurable():
    config = dict(CONFIG, idle_stop_minutes=180)
    assert lc.decide(chat(), NOW, config, "other").action == "keep"
    pressed = lc.decide(chat(), NOW, config, "other", idle_minutes=15)
    assert pressed.action == "stop" and pressed.reopen  # mid-work under memory pressure: a timer reopens it
    assert not lc.decide(chat(pushed_done="done"), NOW, config, "other", idle_minutes=15).reopen


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
def test_a_chat_waiting_on_the_owner_frees_its_slot_but_keeps_its_question(text):
    assert lc.asks_something(text)
    asking = chat(last_activity=NOW - 30 * HOUR, last_text=text)
    decision = lc.decide(asking, NOW, CONFIG, "other")
    assert decision.action == "stop" and "waits on your answer" in decision.reason  # never "done" or archived
    registry: dict = {}
    lc.record_stop(registry, asking, "stopped", decision.reason)
    assert registry["chat-a"]["open_question"]


def test_urls_and_code_spans_with_question_marks_are_not_questions():
    assert not lc.asks_something("Done: see https://example.org/a?b=1 and `x ? y : z`. Task marked Done.")


def test_cap_suspends_longest_idle_first_and_never_breaks_hard_rules():
    config = dict(CONFIG, max_running=3)
    chats = [
        chat(session_id="busy", status="busy", last_activity=NOW - 9 * HOUR),
        chat(session_id="old", last_activity=NOW - 5 * HOUR, pushed_done="done"),
        chat(session_id="recent", last_activity=NOW - 30, pushed_done="done"),
        chat(session_id="mid", last_activity=NOW - 2 * HOUR, pushed_done="parked"),
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
             chat(session_id="plain", last_activity=NOW - 20 * 60, pushed_done="done")]
    assert [victim.session_id for victim in lc.cap_victims(chats, NOW, config, "other")] == ["plain", "q-old"]


def test_cap_never_suspends_a_chat_in_the_middle_of_its_work():
    """TASK-7707: 4b5c74d7 and 061eb4be ended a turn announcing their next step and were closed."""
    config = dict(CONFIG, max_running=1)
    chats = [chat(session_id="working", last_text="Next: fix the foreground reconnect.", last_activity=NOW - 9 * HOUR),
             chat(session_id="done", pushed_done="done", last_activity=NOW - 20 * 60)]
    assert [victim.session_id for victim in lc.cap_victims(chats, NOW, config, "other")] == ["done"]


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
    assert lc.classify(["claude", "--resume", "/tmp/chat.jsonl"], pane, sessions, "bg") == "rc_worker"
    assert lc.classify(["claude bg-spare", "--bg-spare"], pane, sessions, "bg") == "terminal"

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


def test_counts_split_working_idle_stopped_done_and_archived(monkeypatch):
    monkeypatch.setattr(lc.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(lc.codex_chats, "live", lambda: {"codex-1": {"pid": 9}})
    monkeypatch.setattr(lc.codex_chats, "turn_activity", lambda _: (NOW, "working"))
    registry = {"a": {"state": "stopped"}, "b": {"state": "done"}, "c": {"state": "archived"}}
    live = [chat(status="busy"), chat(session_id="b2", last_activity=NOW - 60), chat(session_id="c2")]
    summary = lc.counts(live, registry, NOW, CONFIG, "other", queued=2)
    assert (summary["running"], summary["working"], summary["idle_running"]) == (4, 3, 1)
    assert (summary["idle_stopped"], summary["done_to_archive"], summary["archived"]) == (1, 1, 1)
    assert summary["queued_new_chats"] == 2 and summary["max_running"] == 20
    assert summary["slots_held"] == 3  # the idle c2 holds none
    assert "3 of 16 slots held by chats at work, 4 processes running" in lc.status_line(summary)


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


def test_mark_archive_releases_only_a_stopped_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_CHAT_LIFECYCLE_DIR", str(tmp_path))
    session_id = "e01f80fe-80b5-4d8a-8530-7b5365a507bc"
    released = []
    monkeypatch.setattr(lc, "release_archived_bindings", lambda _, owners: released.extend(owners))
    monkeypatch.setattr(lc, "live_chats", lambda *args, **kwargs: [])
    monkeypatch.setattr(lc.codex_chats, "live", lambda: {session_id: {"pid": 36}})
    assert lc.mark(session_id, "archived", tmp_path) == 0
    assert released == []
    monkeypatch.setattr(lc.codex_chats, "live", lambda: {})
    assert lc.mark(session_id, "archived", tmp_path) == 0
    assert released == [session_id]


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
        text = "────\n❯ [Pasted text #1]\n────\n" if args[2] == "terminal_41" else "────\n❯ \n────\n"
        return type("Result", (), {"returncode": 0, "stdout": text, "stderr": ""})()

    monkeypatch.setattr(lc, "zellij", fake_zellij)
    monkeypatch.setattr("claude_chat_inputs.PROBE_PAUSE", 0)
    assert lc.release(tmp_path, CONFIG, limit=5) == 0
    assert ("write", "--pane-id", "terminal_41", "13") in calls
    assert not any(call[0] == "write" and call[2] == "terminal_42" and call[3] == "13" for call in calls)
    events = (tmp_path / "events.jsonl").read_text()
    assert "held_prompt_released" in events and "held_prompt_lost" in events


def test_release_never_presses_enter_on_a_claude_suggestion(tmp_path, monkeypatch):
    """2026-11-14/15: Enter every minute on the grey next-prompt suggestion of an empty box."""
    monkeypatch.setenv("OPENMATES_CHAT_LIFECYCLE_DIR", str(tmp_path))
    held = [chat(session_id="ghost", pane_id="43", zellij_session="claude", last_speaker="user",
                 last_text=lc.REFUSED_PREFIX, last_activity=NOW - HOUR)]
    monkeypatch.setattr(lc, "live_chats", lambda home, config: held)
    box, calls = {"typed": ""}, []

    def fake_zellij(session, *args):
        calls.append(args)
        if args[0] == "write-chars":
            box["typed"] += args[-1]
        elif args[0] == "write" and args[-1] == "127":
            box["typed"] = box["typed"][:-1]
        shown = box["typed"] or "go ahead and deploy once they're green"
        return type("Result", (), {"returncode": 0, "stdout": f"────\n❯ {shown}\n────\n", "stderr": ""})()

    monkeypatch.setattr(lc, "zellij", fake_zellij)
    monkeypatch.setattr("claude_chat_inputs.PROBE_PAUSE", 0)
    assert lc.release(tmp_path, CONFIG, limit=5) == 0
    assert not any(call[-1] == "13" for call in calls)
    assert box["typed"] == ""
    assert "held_prompt_lost" in (tmp_path / "events.jsonl").read_text()


# ---------------------------------------------------------------------------
# Background work: running CI jobs and job notifications the host hook refused.
# ---------------------------------------------------------------------------

import sqlite3  # noqa: E402  (grouped with the background-work tests)

import claude_chat_pending as pending  # noqa: E402
import claude_chat_waiters as waiters  # noqa: E402

NOTIFICATION = ("<task-notification><task-id>bsnq24fr0</task-id><output-file>/tmp/x.output</output-file>"
                "<status>completed</status><summary>Wait for strip rerun job</summary></task-notification>")


def refusal(at="2026-11-14T13:20:00Z", kept=False, body=NOTIFICATION) -> dict:
    return {"type": "system", "timestamp": at, "promptSubmitEnding": {"promptKept": kept},
            "content": f"{lc.REFUSED_PREFIX}:\nBLOCKED\nOriginal prompt: {body}"}


def reply(text="Waiting for the CI job.") -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def undelivered_item() -> dict:
    return pending.notifications(NOTIFICATION)[0]


def test_chat_with_running_ci_job_is_kept_until_the_waiter_times_out():
    job = waiters.Waiter("chat-a", "ci", "ci:abcd1234", "CI e2e job abcd1234 (running)", NOW - HOUR, NOW + HOUR)
    decision = lc.decide(chat(last_activity=NOW - 72 * HOUR, waiters=[job]), NOW, CONFIG, "other")
    assert decision.action == "keep" and decision.hard and "waits on ci: CI e2e job abcd1234" in decision.reason


def test_chat_with_undelivered_notification_is_kept_even_after_days():
    decision = lc.decide(chat(last_activity=NOW - 72 * HOUR, undelivered=[undelivered_item()]),
                         NOW, CONFIG, "other")
    assert decision.action == "keep" and decision.hard and "bsnq24fr0" in decision.reason


def test_scan_refusal_after_last_reply_is_undelivered_and_parsed():
    result = pending.scan([reply(), refusal()])
    assert result.task_ids == ["bsnq24fr0"] and result.refusal_kept is False
    assert result.undelivered[0]["output"] == "/tmp/x.output" and result.undelivered[0]["status"] == "completed"
    assert result.undelivered[0]["summary"] == "Wait for strip rerun job"


def test_scan_later_user_record_with_same_task_id_is_delivered():
    delivered = {"type": "user", "message": {"content": NOTIFICATION}}
    assert pending.scan([reply(), refusal(), delivered]).undelivered == []


def test_scan_assistant_reply_after_the_refusal_clears_it():
    assert pending.scan([refusal(), reply("Moving on.")]).undelivered == []


def test_scan_ignores_refusals_without_notifications():
    assert pending.scan([refusal(body="please continue")]).undelivered == []


def fake_zellij_factory(calls, screen_text="❯ \n"):
    def fake(session, *args):
        calls.append(args)
        text = screen_text if args[0] == "dump-screen" else ""
        return type("Result", (), {"returncode": 0, "stdout": text, "stderr": ""})()
    return fake


def test_stalled_pane_chat_is_woken_exactly_once_per_task_set(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(lc, "zellij", fake_zellij_factory(calls))
    stalled_chat = chat(pane_id="41", zellij_session="claude", undelivered=[undelivered_item()])
    first = lc.stalled_chats([stalled_chat], {}, tmp_path, NOW, tmp_path, act=True)
    assert first == []  # woken: not listed as stalled
    typed = [call for call in calls if call[0] == "write-chars"]
    assert len(typed) == 1 and "bsnq24fr0" in typed[0][-1] and ("write", "--pane-id", "terminal_41", "13") in calls
    assert "woken" in (tmp_path / "events.jsonl").read_text()
    calls.clear()
    second = lc.stalled_chats([stalled_chat], {}, tmp_path, NOW + 600, tmp_path, act=True)
    assert not calls and len(second) == 1 and "woken, no reply yet" in second[0]["reason"]
    other_set = chat(pane_id="41", zellij_session="claude",
                     undelivered=[{**undelivered_item(), "task_id": "other1"}])
    lc.stalled_chats([other_set], {}, tmp_path, NOW + 1200, tmp_path, act=True)
    assert any(call[0] == "write-chars" for call in calls)


def test_stalled_wake_clears_a_typed_input_line_first_and_logs_failures(tmp_path, monkeypatch):
    calls: list = []
    screens = iter(["❯ half typed\n", "❯ \n", "❯ \n"])

    def fake(session, *args):
        calls.append(args)
        text = next(screens) if args[0] == "dump-screen" else ""
        return type("Result", (), {"returncode": 0, "stdout": text, "stderr": ""})()

    monkeypatch.setattr(lc, "zellij", fake)
    target = chat(pane_id="41", zellij_session="claude", undelivered=[undelivered_item()])
    lc.stalled_chats([target], {}, tmp_path, NOW, tmp_path, act=True)
    assert ("write", "--pane-id", "terminal_41", "21") in calls
    monkeypatch.setattr(lc, "zellij", lambda session, *args: type(
        "Result", (), {"returncode": 1, "stdout": "", "stderr": "gone"})())
    broken = chat(session_id="chat-b", pane_id="42", zellij_session="claude", undelivered=[undelivered_item()])
    listed = lc.stalled_chats([broken], {}, tmp_path, NOW, tmp_path, act=True)
    assert "wake_failed" in (tmp_path / "events.jsonl").read_text() and len(listed) == 1


def test_stopped_registry_chat_with_undelivered_results_is_listed_but_not_woken(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(lc, "zellij", fake_zellij_factory(calls))
    project = tmp_path / "home" / "projects" / "-home-x"
    project.mkdir(parents=True)
    (project / "gone.jsonl").write_text("\n".join(json.dumps(r) for r in [reply(), refusal()]) + "\n")
    registry = {"gone": {"state": "stopped", "title": "Old chat", "kind": "pane",
                         "last_activity": iso(NOW - 5 * HOUR), "stopped_at": iso(NOW - 4 * HOUR),
                         "reason": "idle 60 min", "resume": "claude --resume gone"}}
    listed = lc.stalled_chats([], registry, tmp_path / "home", NOW, tmp_path, act=True)
    assert not calls
    assert len(listed) == 1 and listed[0]["stopped"] is True and listed[0]["tasks"][0]["task_id"] == "bsnq24fr0"
    done_registry = {"gone": {**registry["gone"], "state": "done"}}
    assert len(lc.stalled_chats([], done_registry, tmp_path / "home", NOW, tmp_path, act=False)) == 1


def test_status_json_carries_stalled_entries(tmp_path):
    entry = {"session_id": "chat-a", "reason": "x"}
    lc.write_status(tmp_path, {"running": 1}, {}, [entry])
    data = json.loads((tmp_path / "status.json").read_text())
    assert data["stalled"] == [entry] and data["stalled_chats"] == 1


def test_held_prompts_skip_not_kept_refusals_and_undelivered_chats():
    kept_false = chat(session_id="a", last_speaker="user", last_text=lc.REFUSED_PREFIX, refusal_kept=False)
    undelivered = chat(session_id="b", last_speaker="user", last_text=lc.REFUSED_PREFIX,
                       undelivered=[undelivered_item()])
    kept = chat(session_id="c", last_speaker="user", last_text=lc.REFUSED_PREFIX, refusal_kept=True)
    assert [item.session_id for item in lc.held_prompts([kept_false, undelivered, kept])] == ["c"]


def test_release_presses_enter_once_per_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_CHAT_LIFECYCLE_DIR", str(tmp_path))
    held = [chat(session_id="full", pane_id="41", zellij_session="claude", last_speaker="user",
                 last_text=lc.REFUSED_PREFIX, refusal_kept=True, refusal_at="t1")]
    monkeypatch.setattr(lc, "live_chats", lambda home, config: held)
    calls: list = []
    monkeypatch.setattr(lc, "zellij", fake_zellij_factory(calls, "────\n❯ [Pasted text #1]\n────\n"))
    monkeypatch.setattr("claude_chat_inputs.PROBE_PAUSE", 0)
    lc.release(tmp_path, CONFIG, limit=5)
    lc.release(tmp_path, CONFIG, limit=5)
    assert calls.count(("write", "--pane-id", "terminal_41", "13")) == 1
    held[0].refusal_at = "t2"  # a new refusal gets its own Enter
    lc.release(tmp_path, CONFIG, limit=5)
    assert calls.count(("write", "--pane-id", "terminal_41", "13")) == 2


def make_queue(path: Path, rows) -> None:
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE jobs (id TEXT, owner TEXT, mode TEXT, state TEXT, created REAL, updated REAL)")
        conn.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)", rows)


def test_ci_waiters_count_queued_and_active_jobs_of_the_chats_sessions(tmp_path):
    make_queue(tmp_path / "logs" / "ci-coordinator" / "queue.sqlite3", [
        ("abcdef123456", "8535", "e2e", "running", NOW, NOW), ("zzzzzzzz9", "8535", "pytest", "queued", NOW, NOW),
        ("done0000000", "8535", "vitest", "success", NOW, NOW), ("11112222333", "9999", "vitest", "running", NOW, NOW)])
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "sessions.json").write_text(json.dumps(
        {"sessions": {"8535": {"agent_task_id": "chat-a"}, "other": {}}}))
    sessions = pending.session_ids_by_chat(tmp_path)
    found = waiters.ci_waiters(tmp_path, sessions, NOW)
    assert sorted(w.key for w in found) == ["ci:abcdef123456", "ci:zzzzzzzz9"]
    assert {w.chat_id for w in found} == {"chat-a"}


def test_ci_waiters_without_queue_are_empty_and_a_broken_db_raises(tmp_path):
    assert waiters.ci_waiters(tmp_path, {"chat-a": ["8535"]}, NOW) == []
    broken = tmp_path / "logs" / "ci-coordinator" / "queue.sqlite3"
    broken.parent.mkdir(parents=True)
    broken.write_text("not a database")
    with pytest.raises(RuntimeError, match="CI queue unreadable"):
        waiters.ci_waiters(tmp_path, {"chat-a": ["8535"]}, NOW)


def test_runs_as_isolated_python_like_the_systemd_unit():
    """The units start `python3 -I -S claude_idle_chats.py`; the sibling import must still resolve."""
    import subprocess

    script = Path(__file__).resolve().parents[1] / "claude_idle_chats.py"
    result = subprocess.run(["/usr/bin/python3", "-I", "-S", str(script), "--help"],
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr


def test_a_question_pushed_to_discord_stays_open_until_the_user_answers(tmp_path):
    """Chat 602f0aeb (2026-11-19): it pushed a ❓ decision, ended its reply without a question mark
    and was stopped as idle after 65 minutes, so the decision looked closed."""
    markers = tmp_path / "questions"
    markers.mkdir()
    (markers / "chat-a.json").write_text(json.dumps({"ts": NOW - 3 * HOUR, "question": "Make resends quiet?", "kind": "❓"}))
    asked = lc.pushed_question("chat-a", last_prompt_at=NOW - 4 * HOUR, markers=markers)
    assert asked == "Make resends quiet?"
    pushed = chat(pushed_question=asked, last_text="Pushed the decision to Discord; stopping here.")
    assert lc.decide(pushed, NOW, CONFIG, "").reason.startswith("waits on your answer")
    assert lc.decide(chat(last_activity=NOW - 30 * HOUR, pushed_question=asked), NOW, CONFIG, "").action == "stop"
    assert lc.decide(chat(last_activity=NOW - 30 * HOUR), NOW, CONFIG, "").action == "continue"  # without it
    assert lc.open_question(pushed) == "Make resends quiet?"
    # answered (a prompt after the push), or finished with a ✅ push: no longer open
    assert lc.pushed_question("chat-a", last_prompt_at=NOW - 2 * HOUR, markers=markers) == ""
    (markers / "chat-a.json").write_text(json.dumps({"ts": NOW - HOUR, "question": "Done.", "kind": "✅"}))
    assert lc.pushed_question("chat-a", last_prompt_at=0, markers=markers) == ""
    (markers / "chat-b.json").write_text(json.dumps({"ts": NOW - HOUR, "question": "Old marker without kind"}))
    assert lc.pushed_question("chat-b", last_prompt_at=0, markers=markers) == "Old marker without kind"


def test_a_chat_that_reported_done_is_archived_at_the_end_of_its_turn_and_a_parked_one_only_stopped(tmp_path):
    markers = tmp_path / "questions"
    markers.mkdir()
    (markers / "chat-a.json").write_text(json.dumps({"ts": NOW - HOUR, "question": "Shipped.", "kind": "✅"}))
    assert lc.pushed_done(lc.pushed("chat-a", NOW - 2 * HOUR, markers)) == "done"
    assert lc.pushed_done(lc.pushed("chat-a", NOW - 10 * 60, markers)) == ""  # the user wrote after it
    (markers / "chat-a.json").write_text(json.dumps({"ts": NOW - HOUR, "question": "Parked.", "kind": "✅",
                                                     "paused_until": "2026-11-27"}))
    assert lc.pushed_done(lc.pushed("chat-a", 0, markers)) == "parked"
    assert lc.decide(chat(pushed_done="done"), NOW, CONFIG, "").action == "archive"
    assert lc.decide(chat(pushed_done="parked"), NOW, CONFIG, "").action == "stop"
    timer = waiters.Waiter("chat-a", "timer", "reg:t", "resume", NOW - HOUR, NOW + HOUR)
    assert lc.decide(chat(pushed_done="done", waiters=[timer]), NOW, CONFIG, "").action == "stop"  # it wakes later
    assert lc.decide(chat(pushed_done="done", last_activity=NOW - 60), NOW, CONFIG, "").action == "keep"
    asked = chat(pushed_done="done", last_text="Shall I also deploy it?")
    assert lc.decide(asked, NOW, CONFIG, "").action == "stop"  # a question wins: listed as waiting, not archived
    # 2026-11-20: a ✅ report that only describes the rule ("a chat waiting on your answer …") is not a
    # question; the chat was stopped as asking instead of archived.
    report = chat(pushed_done="done", last_text="**Answering chats:** a chat waiting on your answer no longer runs "
                                                "in the background.\nIt reopens when you answer.")
    assert lc.decide(report, NOW, CONFIG, "").action == "archive"
    assert lc.decide(chat(last_text=report.last_text), NOW, CONFIG, "").action == "stop"  # no push: the guess holds


def test_task_priorities_come_from_the_tasks_copy(tmp_path):
    cache = tmp_path / "tasks.json"
    cache.write_text(json.dumps({"data": {"tasks": [
        {"status": "todo", "priority_level": "low", "external_chat": {"provider": "claude", "id": "a"}},
        {"status": "in_progress", "priority_level": "urgent", "external_chat": {"provider": "claude", "id": "a"}},
        {"status": "done", "priority_level": "urgent", "external_chat": {"provider": "claude", "id": "b"}},
        {"status": "todo", "priority_level": "high", "external_chat": {"provider": "codex", "id": "c"}},
        {"status": "todo", "priority_level": "high", "external_chat": None}]}}))
    assert lc.task_priorities(cache) == {"a": 0}
    assert lc.task_priorities(tmp_path / "missing.json") == {}


class FakeZellij:
    """zellij(session, *args) stand-in: list-panes --json / list-tabs per session, records closes."""

    def __init__(self, panes: dict[str, list[dict]], tabs: dict[str, list[int]]):
        self.panes, self.tabs, self.closed = panes, tabs, []

    def __call__(self, session, *args):
        import subprocess
        if args[0] == "list-panes":
            return subprocess.CompletedProcess(args, 0, json.dumps(self.panes.get(session, [])), "")
        if args[0] == "list-tabs":
            rows = ["TAB_ID  POSITION  NAME", *(f"{t}  {t}  tab" for t in self.tabs.get(session, []))]
            return subprocess.CompletedProcess(args, 0, "\n".join(rows), "")
        self.closed.append((session, args[0], args[-1]))
        return subprocess.CompletedProcess(args, 0, "", "")


def term(n, tab, **extra):
    return {"id": n, "is_plugin": False, "tab_id": tab, "exited": False, "is_held": False, **extra}


def test_dead_panes_empty_tabs_and_the_link_plugin_are_closed_but_live_panes_never(tmp_path):
    """2026-11-20: 58 dead panes, 57 empty tabs and the link plugin kept the claude zellij server at 110% CPU."""
    link = {"id": 0, "is_plugin": True, "plugin_url": "zellij:link", "tab_id": 0}
    fake = FakeZellij({"claude": [link, term(1, 0), term(2, 1), term(3, 2), term(9, 2)],
                       "partner": [term(4, 0, is_held=True)]},
                      {"claude": [0, 1, 2, 5], "partner": [0]})
    owners = {"claude": {"1", "9"}, "partner": {"4"}}
    first = lc.close_dead_panes(["claude", "partner"], tmp_path, NOW, owners, fake)
    assert first == ["claude plugin_0 (zellij:link)"]  # dead panes and empty tabs wait for a second sighting
    assert lc.close_dead_panes(["claude", "partner"], tmp_path, NOW + 30, owners, fake) == [
        "claude plugin_0 (zellij:link)"]  # too soon
    closed = lc.close_dead_panes(["claude", "partner"], tmp_path, NOW + lc.DEAD_PANE_SECONDS, owners, fake)
    assert "claude empty tab 5" in closed
    assert "claude terminal_2" in closed and "claude terminal_3" in closed and "partner terminal_4" in closed
    assert ("claude", "close-tab", "1") in fake.closed  # its only pane: the tab goes with it
    assert ("claude", "close-pane", "terminal_3") in fake.closed  # tab 2 keeps its live pane 9
    assert not any(target in ("terminal_1", "terminal_9") for _, _, target in fake.closed)


@pytest.mark.parametrize(("listing", "owners"), [
    ([], {"1"}),  # nothing listed (2026-11-20 22:14: every tab closed as "empty")
    ([{"id": 1, "is_plugin": False, "exited": False, "is_held": False}], {"1"}),  # panes without their tab
    ([term(1, 0)], {"1", "7"}),  # a live pane (chat 70004807's) missing from the listing
])
def test_tidy_leaves_a_session_alone_when_its_pane_listing_is_incomplete(tmp_path, listing, owners):
    """TASK-7707: the tidy closed the tabs of working chats 70004807 (18:32) and 4508e325 (22:14)."""
    fake = FakeZellij({"claude": listing}, {"claude": [0, 1, 2, 3]})
    for later in (0, lc.DEAD_PANE_SECONDS, 2 * lc.DEAD_PANE_SECONDS):
        assert lc.close_dead_panes(["claude"], tmp_path, NOW + later, {"claude": owners}, fake) == []
    assert fake.closed == []


def test_tidy_never_closes_a_live_chats_pane_even_when_its_process_looks_gone(tmp_path):
    fake = FakeZellij({"claude": [term(1, 0), term(2, 1)]}, {"claude": [0, 1]})
    for later in (0, lc.DEAD_PANE_SECONDS):
        lc.close_dead_panes(["claude"], tmp_path, NOW + later, {"claude": set()}, fake, protected={"claude": {"2"}})
    assert ("claude", "close-tab", "0") in fake.closed  # pane 1: dead, alone in its tab
    assert not any(target in ("1", "terminal_2") for _, _, target in fake.closed)


# --- wake-ups must be submitted, not only typed (TASK-1338, 2026-11-23) ---

BOX = "────\n❯ {}\n────\n  ⏵⏵ auto mode on\n"


def scripted_zellij(calls, screens):
    """dump-screen returns the next screen of `screens` (the last one repeats)."""
    queue = list(screens)

    def fake(session, *args):
        calls.append(args)
        text = (queue.pop(0) if len(queue) > 1 else queue[0]) if args[0] == "dump-screen" else ""
        return type("Result", (), {"returncode": 0, "stdout": text, "stderr": ""})()
    return fake


def test_wake_counts_only_a_submitted_prompt(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(lc, "_sleep", lambda seconds: None)
    monkeypatch.setattr(lc, "state_dir", lambda: tmp_path)
    # empty box before typing, text still shown after the first Enter, empty after the second
    monkeypatch.setattr(lc, "zellij", scripted_zellij(calls, [
        BOX.format(""), BOX.format("[chat lifecycle] Background work of this"), BOX.format("")]))
    assert lc.wake(chat(pane_id="7", zellij_session="claude"), "[chat lifecycle] Background work of this chat")
    assert calls.count(("write", "--pane-id", "terminal_7", "13")) == 2


def test_wake_left_in_the_box_is_logged_without_its_own_alert(tmp_path, monkeypatch):
    calls: list = []
    posted: list = []
    transcript = tmp_path / "chat.jsonl"
    transcript.write_text("\n".join(json.dumps(entry) for entry in [
        {"type": "assistant", "message": {"content": "waiting"}},
        {"type": "system", "subtype": "informational", "content": "UserPromptSubmit operation blocked by hook:\n"
         "[command hook 2]: python3: can't open file '/w/agent-1/scripts/chat_mailbox.py'\n\nOriginal prompt: x"},
    ]) + "\n")
    monkeypatch.setattr(lc, "_sleep", lambda seconds: None)
    monkeypatch.setattr(lc, "state_dir", lambda: tmp_path)
    import chat_usage_watch
    monkeypatch.setattr(chat_usage_watch, "send", lambda text: posted.append(text) or True)
    stuck = chat(pane_id="7", zellij_session="claude", transcript=str(transcript), title="Live collab")
    monkeypatch.setattr(lc, "zellij", scripted_zellij(calls, [BOX.format(""), BOX.format("[chat lifecycle] Back")]))
    assert not lc.wake(stuck, "[chat lifecycle] Background work of this chat")
    assert calls.count(("write", "--pane-id", "terminal_7", "13")) == lc.WAKE_SUBMIT_TRIES
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "wake_unsent" and "chat_mailbox.py" in events[-1]["reason"]
    assert posted == []  # The watchdog owns any user-facing alert.


def test_wake_ignores_a_suggestion_after_submit(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(lc, "_sleep", lambda seconds: None)
    monkeypatch.setattr(lc, "zellij", scripted_zellij(calls, [BOX.format(""), BOX.format("run the tests again")]))
    assert lc.wake(chat(pane_id="7", zellij_session="claude"), "[chat lifecycle] Background work of this chat")


def test_block_reason_ignores_blocks_before_a_later_turn(tmp_path):
    transcript = tmp_path / "chat.jsonl"
    transcript.write_text("\n".join(json.dumps(entry) for entry in [
        {"type": "system", "content": "UserPromptSubmit operation blocked by hook: old"},
        {"type": "user", "message": {"content": "hi"}},
    ]) + "\n")
    assert lc.submit_block_reason(str(transcript)) == ""


def test_wake_sees_unsent_text_in_a_box_taller_than_the_pane(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(lc, "_sleep", lambda seconds: None)
    monkeypatch.setattr(lc, "state_dir", lambda: tmp_path)
    import chat_usage_watch
    monkeypatch.setattr(chat_usage_watch, "send", lambda text: True)
    text = "[chat lifecycle] Background work of this chat finished; output /tmp/x/tasks/b1oqw8apj.output. Read it."
    tall = ("  finished; output /tmp/x/tas\n  ks/b1oqw8apj.output. Read it.\n"
            "────────────────────────────────────────────────\n  ⏵⏵ auto mode on\n")
    monkeypatch.setattr(lc, "zellij", scripted_zellij(calls, [BOX.format(""), tall]))
    assert not lc.wake(chat(pane_id="7", zellij_session="claude"), text)
    submitted = ("❯ " + text + "\n  ⎿ working\n────\n❯ \n────\n  ⏵⏵ auto mode on\n")
    monkeypatch.setattr(lc, "zellij", scripted_zellij(calls, [BOX.format(""), submitted]))
    assert lc.wake(chat(pane_id="7", zellij_session="claude"), text)


def test_wake_does_not_submit_into_new_session_composer(monkeypatch):
    calls = []
    screen = BOX.format("describe a task for a new session")
    monkeypatch.setattr(lc, "zellij", scripted_zellij(calls, [screen]))
    assert not lc.wake(chat(pane_id="7", zellij_session="partner"), "Continue")
    assert calls == [("dump-screen", "--pane-id", "terminal_7")]


def test_ci_billing_block_is_an_owner_wait_even_with_finished_background_work():
    blocked = chat(last_speaker="assistant", last_text="CI is blocked by GitHub billing.",
                   undelivered=[{"task_id": "ci"}])
    decision = lc.decide(blocked, blocked.last_activity + 3600, dict(lc.DEFAULTS), "")
    assert decision.action == "stop"
    assert not decision.reopen
    assert lc.open_question(blocked) == lc.BILLING_QUESTION



def test_billing_wait_survives_worker_restarts_and_does_not_age_into_done():
    blocked = chat(last_speaker="assistant", last_text="GitHub Actions did not start because of the spending limit.")
    registry = {}
    lc.record_stop(registry, blocked, "stopped", lc.BILLING_QUESTION)
    now = blocked.last_activity + 48 * 3600
    lc.refresh_registry(registry, [blocked], now, dict(lc.DEFAULTS))
    assert registry[blocked.session_id]["state"] == "stopped"
    assert registry[blocked.session_id]["open_question"] == lc.BILLING_QUESTION
    blocked.last_speaker = "user"
    lc.refresh_registry(registry, [blocked], now, dict(lc.DEFAULTS))
    assert blocked.session_id not in registry

def test_reserve_never_types_a_wake_into_claude(monkeypatch):
    monkeypatch.setattr(lc.claude_weekly_model, "needs_handoff", lambda _, **kw: True)
    monkeypatch.setattr(lc, "zellij", lambda *args: pytest.fail("Claude received a wake"))
    assert not lc.wake(chat(pane_id="7", zellij_session="claude"), "Continue")


def test_reap_main_reaches_lifecycle(tmp_path, monkeypatch):
    calls = []

    def run(args, config):
        calls.append((args.command, args.dry_run))
        return [], 0

    monkeypatch.setattr(lc, "run_cycle", run)
    assert lc.main(["reap", "--dry-run", "--claude-home", str(tmp_path)]) == 0
    assert calls == [("reap", True)]



def test_zellij_cleanup_timeout_does_not_abort_chat_admission(tmp_path):
    import subprocess

    calls = []

    def unresponsive_listing(session, *args):
        calls.append((session, args[0]))
        raise subprocess.TimeoutExpired(args, 30)

    assert lc.close_dead_panes(["fixture"], tmp_path, NOW, {}, unresponsive_listing) == []
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "zellij_tidy_skipped"
    assert calls == [("fixture", "list-panes")]



def test_admission_reserves_last_slot_for_production(monkeypatch):
    monkeypatch.setattr(lc, "load_config", lambda: dict(CONFIG))
    monkeypatch.setattr(lc.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(lc.host_load_guard, "gate", lambda _: None)
    monkeypatch.setattr(lc.codex_chats, "live", lambda: {str(i): {} for i in range(15)})
    monkeypatch.setattr(lc.codex_chats, "turn_activity", lambda _: (NOW, "working"))
    requests = []

    def reap(args, config, room):
        requests.append(room)
        return [], 0

    monkeypatch.setattr(lc, "run_cycle", reap)
    assert lc.main(["admit"]) == lc.EXIT_NO_ROOM
    assert lc.main(["admit", "--production"]) == 0
    assert requests == [6, 5]


def test_chat_admission_holds_for_load_before_reaping(monkeypatch, capsys):
    monkeypatch.setattr(lc, "load_config", lambda: dict(CONFIG))
    monkeypatch.setattr(lc.host_load_guard, "gate", lambda _: "host overload")
    monkeypatch.setattr(lc, "run_cycle", lambda *args: pytest.fail("reaping during admission"))
    assert lc.main(["admit", "--production"]) == lc.EXIT_NO_ROOM
    assert "host overload" in capsys.readouterr().out


def test_only_production_waiter_may_use_last_free_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(lc.os, "cpu_count", lambda: 16)
    running = {str(i): {} for i in range(15)}
    monkeypatch.setattr(lc.codex_chats, "live", lambda: running)
    monkeypatch.setattr(lc.codex_chats, "turn_activity", lambda _: (NOW, "working"))
    observed = []

    def deliver(waiters, *args, room, **kwargs):
        observed.append((set(waiters), room))
        return set(), []

    monkeypatch.setattr(lc.claude_chat_waiters, "deliver", deliver)
    config = dict(CONFIG, production_chat_ids=["release"])
    lc.wake_waiting({"release": [], "ordinary": [], "1": []}, [], {}, tmp_path, NOW, config)
    assert observed == [({"release", "1"}, 1)]


def test_admission_counts_only_chats_at_work_and_lists_them(tmp_path, monkeypatch, capsys):
    """2026-11-27: start_chat refused with "15 chats run (admission limit 15)" while 2 chats worked;
    11 idle Codex chats, refused for Codex's usage limit, and an idle terminal chat filled the count."""
    monkeypatch.setenv("OPENMATES_CHAT_LIFECYCLE_DIR", str(tmp_path))
    monkeypatch.setattr(lc, "load_config", lambda: dict(CONFIG))
    monkeypatch.setattr(lc.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(lc.host_load_guard, "gate", lambda _: None)
    monkeypatch.setattr(lc.time, "time", lambda: NOW)
    at_work = [chat(session_id="busy", status="busy", title="Apple notifications"),
               chat(session_id="recent", last_activity=NOW - 60),
               chat(session_id="ci", children=[*MCP, "/bin/bash -c cargo test"])]
    idle = [chat(session_id="asks", pushed_question="Ship it?"), chat(session_id="term", kind="terminal"),
            chat(session_id="pinned", protected=True), chat(session_id="between-continues")]
    codex = {f"codex-{n}": {"pid": 100 + n} for n in range(11)}
    codex["codex-working"] = {"pid": 200}
    monkeypatch.setattr(lc.codex_chats, "live", lambda: codex)
    monkeypatch.setattr(lc.codex_chats, "turn_activity", lambda cid: (
        (NOW - 10, "working") if cid == "codex-working" else (NOW - 90 * 60, "idle")))
    monkeypatch.setattr(lc, "_children", lambda pid: [])
    left = at_work + idle
    monkeypatch.setattr(lc, "run_cycle", lambda args, config, room: (left, 0))
    holding, not_counted = lc.slot_holders(left, NOW, CONFIG, tmp_path)
    assert sorted(row["session_id"] for row in holding) == ["busy", "ci", "codex-working", "recent"]
    assert len(not_counted) == 15
    assert lc.main(["admit"]) == 0  # 4 of 15 slots held: start_chat works again

    left = at_work + [chat(session_id=f"busy-{n}", status="busy") for n in range(11)] + idle
    assert lc.main(["admit"]) == lc.EXIT_NO_ROOM
    out = capsys.readouterr().out
    assert out.startswith("no room: 15 chats hold a slot (admission limit 15); counted:")
    assert "busy claude/pane 'Apple notifications': state is busy" in out
    assert "codex-wo codex/codex '(untitled)': turn running" in out
    assert "running but idle, not counted (15):" in out and "asks claude/pane" in out


def test_codex_chat_with_a_pending_message_holds_its_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(lc.codex_chats, "turn_activity", lambda _: (NOW - HOUR, "idle"))
    monkeypatch.setattr(lc, "_children", lambda pid: [])
    assert lc.codex_slot_reason("c", 1, NOW, CONFIG, tmp_path) == ""
    (tmp_path / "connector-deliveries.json").write_text(json.dumps({"c": {}}))
    assert lc.codex_slot_reason("c", 1, NOW, CONFIG, tmp_path) == "a message or background process is pending"


def test_codex_chats_that_reported_done_are_archived_without_a_reopen():
    """28 stopped Codex chats sat in "done to archive": the connector reopens a Claude chat to
    /exit it, which a Codex chat has no use for (no app session, cwd gone)."""
    registry = {"done": {"state": "stopped", "kind": "codex", "reason": "reported done", "last_activity": iso(NOW)},
                "old": {"state": "done", "kind": "codex", "reason": "reported done", "last_activity": iso(NOW)},
                "asked": {"state": "done", "kind": "codex", "reason": "asked the owner",
                          "last_activity": iso(NOW - 30 * HOUR)},
                "claude": {"state": "stopped", "kind": "pane", "reason": "reported done with a ✅ push",
                           "last_activity": iso(NOW - 30 * HOUR)}}
    lc.refresh_registry(registry, [], NOW, CONFIG)
    assert registry["done"]["state"] == registry["old"]["state"] == "archived"
    assert registry["asked"]["state"] == "done"  # waits on Marco: left for him
    assert registry["claude"]["state"] == "done"
