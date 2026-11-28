# contract-test-file: tooling
"""Working chats are never closed by the chat lifecycle (TASK-7707, owner rule 2026-11-21).

2026-11-20 five chats were closed in the middle of their work: three ended a turn announcing their
next step and were stopped as idle, one had a background sub-agent mid tool call, and the zellij
tidy closed the tabs of two (that part: test_claude_idle_chats.py).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import claude_chat_continue as cc  # noqa: E402  (path set above)
import claude_idle_chats as lc  # noqa: E402

NOW = 1_800_000_000.0
CHAT_ID = "061eb4be-b818-4e13-b31e-bef055ce25ca"


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def reply(ts: float, text: str = "", tool: bool = False) -> dict:
    content = [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}] if tool else [{"type": "text", "text": text}]
    return {"type": "assistant", "timestamp": iso(ts), "message": {"role": "assistant", "content": content}}


def working_chat(**overrides) -> lc.Chat:
    values = dict(pid=1, session_id=CHAT_ID, name="openmates-aa", status="idle", kind="pane",
                  last_activity=NOW - 600, last_speaker="assistant", zellij_session="claude", pane_id="4",
                  last_text="The reconnect banner is fixed. Next: fix the foreground reconnect.")
    values.update(overrides)
    return lc.Chat(**values)


def test_a_turn_that_announces_its_next_step_is_woken_not_closed():
    decision = lc.decide(working_chat(), NOW, dict(lc.DEFAULTS), "other")
    assert decision.action == "continue" and not decision.close
    assert lc.decide(working_chat(pushed_question="Ship it?"), NOW, dict(lc.DEFAULTS), "other").close
    assert lc.decide(working_chat(pushed_done="done"), NOW, dict(lc.DEFAULTS), "other").action == "archive"


def test_continue_wakes_once_per_turn_retries_and_lists_a_chat_that_never_acts(tmp_path, monkeypatch):
    typed = []
    monkeypatch.setattr(lc, "wake", lambda chat, text="": typed.append(text) or True)
    chat = working_chat()
    keep = {CHAT_ID}
    assert lc.continue_unfinished([chat], tmp_path, NOW, keep) == []
    assert len(typed) == 1 and "Continue with your next step" in typed[0]
    assert lc.continue_unfinished([chat], tmp_path, NOW + 60, keep) == []  # same turn, give it time
    assert len(typed) == 1
    for n in range(2, cc.MAX_WAKES + 1):  # the line did not take, or it answered without working
        chat.last_activity = NOW + n * 1000
        lc.continue_unfinished([chat], tmp_path, NOW + n * 1000 + 1, keep)
        assert len(typed) == n
    chat.last_activity = NOW + 9000
    stalled = lc.continue_unfinished([chat], tmp_path, NOW + 9001, keep)
    assert len(typed) == cc.MAX_WAKES and [s["session_id"] for s in stalled] == [CHAT_ID]
    assert "it keeps running" in stalled[0]["reason"]  # listed for the owner, never closed


def test_tool_work_after_a_wake_starts_the_count_over(tmp_path, monkeypatch):
    typed = []
    monkeypatch.setattr(lc, "wake", lambda chat, text="": typed.append(text) or True)
    transcript = tmp_path / "chat.jsonl"
    chat = working_chat(transcript=str(transcript))
    for n in range(cc.MAX_WAKES + 2):  # it works after every wake, then announces the next step again
        woken_at = NOW + n * 1000
        write(transcript, [reply(woken_at + 10, tool=True), reply(woken_at + 20, "Next: the other lane.")])
        chat.last_activity = woken_at - 1
        assert lc.continue_unfinished([chat], tmp_path / "state", woken_at, {CHAT_ID}) == []
    assert len(typed) == cc.MAX_WAKES + 2


def test_a_chat_without_a_pane_is_kept_and_listed(tmp_path):
    stalled = lc.continue_unfinished([working_chat(kind="rc_worker", pane_id="")], tmp_path, NOW, {CHAT_ID})
    assert "cannot be woken here" in stalled[0]["reason"]


def test_a_running_background_sub_agent_keeps_the_chat(tmp_path):
    """70004807 (2026-11-20 18:32): its lane-worker was mid tool call when the chat was closed."""
    transcript = tmp_path / f"{CHAT_ID}.jsonl"
    agents = transcript.with_suffix("") / "subagents"
    started = NOW - 3600
    write(transcript, [reply(NOW - 900, tool=True)])
    for agent_id, shape, last in (("ad37", "background", NOW - 300), ("old1", "background", started - 60),
                                  ("fore", "foreground", NOW - 300)):
        (agents).mkdir(parents=True, exist_ok=True)
        (agents / f"agent-{agent_id}.meta.json").write_text(json.dumps(
            {"agentType": "lane-worker", "description": f"lane {agent_id}", "requestShape": shape}))
        write(agents / f"agent-{agent_id}.jsonl", [reply(last, tool=True)])
    assert cc.running_agents(transcript, started, NOW) == ["lane ad37"]  # not the dead or foreground ones
    blocked = lc.decide(working_chat(agents=["lane ad37"], last_activity=NOW - 3600), NOW, dict(lc.DEFAULTS), "x")
    assert blocked.action == "keep" and blocked.hard and "background sub-agent" in blocked.reason
    with transcript.open("a", encoding="utf-8") as handle:  # it reported back
        handle.write(json.dumps({"type": "user", "timestamp": iso(NOW - 10), "message": {
            "content": "<task-notification>\n<task-id>ad37</task-id>\n<status>completed</status>"}}) + "\n")
    assert cc.running_agents(transcript, started, NOW) == []
    assert cc.running_agents(transcript, started, NOW + 4 * 3600) == []  # a hung agent stops holding it


def test_a_chat_that_handed_off_is_never_nudged_to_continue(tmp_path, monkeypatch):
    typed = []
    monkeypatch.setattr(lc, "wake", lambda chat, text="": typed.append(text) or True)
    (tmp_path / "handed_off.json").write_text(json.dumps({CHAT_ID: {"successor": "pane 7"}}))
    assert lc.continue_unfinished([working_chat()], tmp_path, NOW, {CHAT_ID}) == []
    assert typed == []



def test_unavailable_pane_is_reported_once_until_activity_changes(tmp_path, monkeypatch):
    attempts = []

    def wake(chat, _text):
        attempts.append(chat.session_id)
        return False

    monkeypatch.setattr(lc, "wake", wake)
    chat = working_chat()
    for now in (NOW, NOW + 1000):
        assert lc.continue_unfinished([chat], tmp_path, now, {CHAT_ID})
    assert attempts == [CHAT_ID]
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1
    chat.last_activity = NOW + 1100
    assert lc.continue_unfinished([chat], tmp_path, NOW + 1200, {CHAT_ID})
    assert attempts == [CHAT_ID, CHAT_ID]
