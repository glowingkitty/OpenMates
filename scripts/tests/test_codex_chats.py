"""Codex chat registry, launch command, transcript mirror and usage reading (TASK-4476)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_chats  # noqa: E402

THREAD = "99999999-2222-4333-8444-555555555555"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_CODEX_CHATS_DIR", str(tmp_path / "chats"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    return tmp_path


def _rollout(home, items):
    path = home / "codex" / "sessions" / "2026" / "11" / "23" / f"rollout-2026-11-23T10-00-00-{THREAD}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(i) + "\n" for i in items))
    return path


# contract-test: tooling
def test_models_astra_only_when_named():
    assert codex_chats.check_model("codex", False) == "gpt-6.2-sol"
    assert codex_chats.check_model("Astra", True) == "gpt-6.2-astra"
    with pytest.raises(codex_chats.CodexChatError):
        codex_chats.check_model("gpt-6.2-astra", False)


# contract-test: tooling
def test_launch_command_fixes_model_effort_and_identity(home):
    record = codex_chats.new_record("Fix a typo", "gpt-6.2-sol", "medium", "/repo", False)
    command = codex_chats.tab_command(record, "do it")
    assert f"OPENMATES_CHAT_ID={record['chat_id']}" in command and f"CLAUDE_CODE_SESSION_ID={record['chat_id']}" in command
    assert 'model_reasoning_effort="medium"' in command and "features.hooks=true" in command
    assert command[-1] == "do it" and command[command.index("--model") + 1] == "gpt-6.2-sol"
    resumed = codex_chats.tab_command(record, "next", resume_thread=THREAD)
    assert resumed[resumed.index("resume") + 1] == THREAD


# contract-test: tooling
def test_mirror_writes_claude_records_and_usage_reads_rate_limits(home):
    record = codex_chats.new_record("Fix a typo", "gpt-6.2-sol", "medium", "/repo", False)
    record["thread_id"] = THREAD
    codex_chats.save(record)
    _rollout(home, [
        {"timestamp": "2026-11-23T10:00:01Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Fix it"}},
        {"timestamp": "2026-11-23T10:00:02Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "shell", "arguments": "{\"command\": [\"ls\"]}", "call_id": "c1"}},
        {"timestamp": "2026-11-23T10:00:03Z", "type": "event_msg", "payload": {"type": "agent_message", "message": "Done."}},
        {"timestamp": "2026-11-23T10:00:04Z", "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 20.0, "window_minutes": 300, "resets_in_seconds": 600},
            "secondary": {"used_percent": 35.5, "window_minutes": 10080, "resets_at": 1764000000}}}},
    ])
    rows = [json.loads(line) for line in codex_chats.mirror(record["chat_id"]).read_text().splitlines()]
    assert rows[0] == {"type": "custom-title", "customTitle": "Fix a typo", "sessionId": record["chat_id"]}
    assert [r["type"] for r in rows[1:]] == ["user", "assistant", "assistant"]
    assert rows[2]["message"]["content"][0]["name"] == "Bash" and rows[3]["message"]["model"] == "codex:gpt-6.2-sol"
    usage = codex_chats.usage()
    assert usage["weekly"]["remaining_percent"] == 64.5 and usage["five_hour"]["remaining_percent"] == 80.0
    assert codex_chats.transcripts() == {record["chat_id"]: codex_chats.transcript_path(record["chat_id"])}


# contract-test: tooling
def test_usage_without_readings_says_so(home):
    assert codex_chats.usage()["known"] is False


# contract-test: tooling
def test_reap_stops_only_done_or_asking_idle_chats(home, monkeypatch):
    ids = {}
    for name in ("done", "asks", "busy", "waits"):
        record = codex_chats.new_record(name, "gpt-6.2-sol", "medium", "/repo", False)
        codex_chats.save(record)
        ids[name] = record["chat_id"]
    monkeypatch.setattr(codex_chats, "live", lambda: {cid: {"pid": n} for n, cid in enumerate(ids.values(), 100)})
    monkeypatch.setattr(codex_chats, "last_times", lambda cid: (1000.0, 900.0))
    markers = {ids["done"]: {"kind": "✅", "ts": 950}, ids["asks"]: {"kind": "❓", "ts": 950},
               ids["waits"]: {"kind": "✅", "ts": 950}}
    killed = []
    stopped = codex_chats.reap(lambda cid, _at: markers.get(cid, {}), 3, {ids["waits"]}, now=2000.0,
                               signal_fn=lambda pid, sig: killed.append(pid))
    assert sorted(e["chat_id"] for e in stopped) == sorted([ids["done"], ids["asks"]]) and len(killed) == 2
    assert codex_chats.reap(lambda cid, _at: markers.get(cid, {}), 3, set(), now=1050.0, act=False) == []


# contract-test: tooling
def test_exhausted_codex_windows_end_when_the_limit_resets():
    from datetime import datetime, timezone

    reading = {"five_hour": {"used_percent": 100, "resets_at": "2026-11-23T18:00:00+00:00"},
               "weekly": {"used_percent": 80, "resets_at": "2026-11-30T18:00:00+00:00"}}
    before = datetime(2026, 11, 23, 17, tzinfo=timezone.utc)
    after = datetime(2026, 11, 23, 19, tzinfo=timezone.utc)
    assert codex_chats.exhausted_windows(reading, before) == ["five_hour:2026-11-23T18:00:00+00:00"]
    assert codex_chats.exhausted_windows(reading, after) == []
