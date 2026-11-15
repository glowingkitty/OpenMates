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

NOTIFICATION = ("<task-notification><task-id>bsnq24fr0</task-id><output-file>/tmp/x.output</output-file>"
                "<status>completed</status><summary>Wait for strip rerun job</summary></task-notification>")


def refusal(at="2026-11-14T13:20:00Z", kept=False, body=NOTIFICATION) -> dict:
    return {"type": "system", "timestamp": at, "promptSubmitEnding": {"promptKept": kept},
            "content": f"{lc.REFUSED_PREFIX}:\nBLOCKED\nOriginal prompt: {body}"}


def reply(text="Waiting for the CI job.") -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def undelivered_item() -> dict:
    return pending.notifications(NOTIFICATION)[0]


def test_chat_with_running_ci_job_is_kept_even_after_days():
    decision = lc.decide(chat(last_activity=NOW - 72 * HOUR, ci_jobs=["e2e abcd1234"]), NOW, CONFIG, "other")
    assert decision.action == "keep" and decision.hard and "waits on CI" in decision.reason


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
    screens = iter(["❯ half typed\n", "❯ \n"])

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
        conn.execute("CREATE TABLE jobs (id TEXT, owner TEXT, mode TEXT, state TEXT)")
        conn.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?)", rows)


def test_running_ci_jobs_reads_running_jobs_by_owner_and_maps_chats(tmp_path):
    make_queue(tmp_path / "logs" / "ci-coordinator" / "queue.sqlite3", [
        ("abcdef123456", "8535", "e2e", "running"), ("zzzzzzzz", "8535", "pytest", "queued"),
        ("11112222333", "9999", "vitest", "running")])
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "sessions.json").write_text(json.dumps(
        {"sessions": {"8535": {"agent_task_id": "chat-a"}, "other": {}}}))
    jobs = pending.running_ci_jobs(tmp_path)
    assert jobs == {"8535": ["e2e abcdef12"], "9999": ["vitest 11112222"]}
    sessions = pending.session_ids_by_chat(tmp_path)
    assert pending.ci_jobs_for("chat-a", sessions, jobs) == ["e2e abcdef12"]
    assert pending.ci_jobs_for("chat-z", sessions, jobs) == []


def test_running_ci_jobs_without_queue_is_empty_and_broken_db_raises(tmp_path):
    assert pending.running_ci_jobs(tmp_path) == {}
    broken = tmp_path / "logs" / "ci-coordinator" / "queue.sqlite3"
    broken.parent.mkdir(parents=True)
    broken.write_text("not a database")
    with pytest.raises(RuntimeError, match="CI queue unreadable"):
        pending.running_ci_jobs(tmp_path)


def test_runs_as_isolated_python_like_the_systemd_unit():
    """The units start `python3 -I -S claude_idle_chats.py`; the sibling import must still resolve."""
    import subprocess

    script = Path(__file__).resolve().parents[1] / "claude_idle_chats.py"
    result = subprocess.run(["/usr/bin/python3", "-I", "-S", str(script), "--help"],
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
