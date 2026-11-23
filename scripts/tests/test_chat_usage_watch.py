"""chat_usage_watch: one owner notice per chat with unusually many sub-agents or tokens, nothing stopped."""
# contract-test-file: tooling
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat_usage_watch as w  # noqa: E402  (path set above)

NOW = 1_800_000_000.0
CHAT = "061eb4be-b818-4e13-b31e-bef055ce25ca"


def usage_line(input_tokens=0, cache_read=0, output=0) -> str:
    return json.dumps({"type": "assistant", "message": {"usage": {
        "input_tokens": input_tokens, "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": cache_read, "output_tokens": output}}}) + "\n"


def make_chat(project: Path, lines: list[str], agents: int = 0) -> Path:
    transcript = project / f"{CHAT}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("".join(lines))
    sub = project / CHAT / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    for n in range(agents):
        (sub / f"agent-{n:04x}.jsonl").write_text(usage_line(input_tokens=10))
    return transcript


def test_weights_follow_the_investigation():
    record = json.loads(usage_line(input_tokens=100, cache_read=1000, output=10))
    assert w.record_units(record) == 100 + 100 + 50
    assert w.record_units({"type": "user", "message": "hi"}) == 0


def test_reading_is_incremental_and_ignores_a_partial_last_line(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(usage_line(input_tokens=5) + '{"message": {"usage"')
    entry = w.read_new(path, {})
    assert entry["units"] == 5 and entry["offset"] == len(usage_line(input_tokens=5))
    with path.open("a") as handle:
        handle.write(': {"input_tokens": 7}}}\n')
    assert w.read_new(path, entry)["units"] == 12


def test_crossing_a_threshold_notifies_once_and_names_the_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_USAGE_WATCH_FILE", str(tmp_path / "state.json"))
    project = tmp_path / "project"
    make_chat(project, [usage_line(input_tokens=w.TOKEN_NOTICE_UNITS)], agents=w.AGENT_NOTICE_COUNT)
    sent = []
    post = lambda text: sent.append(text) or True  # noqa: E731  (tiny fake)
    import os
    os.utime(project / f"{CHAT}.jsonl", (NOW, NOW))
    assert w.run(NOW, project_dir=project, post=post) == [f"{CHAT[:8]} notified=True"]
    assert "100M weighted tokens and 40 sub-agents" in sent[0] and "No handoff yet" in sent[0]
    assert w.run(NOW + 60, project_dir=project, post=post) == []  # once per chat
    assert len(sent) == 1


def test_several_chats_crossing_together_bring_one_message(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("OPENMATES_USAGE_WATCH_FILE", str(tmp_path / "state.json"))
    project = tmp_path / "project"
    for chat, title in (("aaaaaaaa-1", "Recipe preview"), ("bbbbbbbb-2", "Calendar sync")):
        path = project / f"{chat}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "custom-title", "customTitle": title}) + "\n"
                        + usage_line(input_tokens=w.TOKEN_NOTICE_UNITS))
        os.utime(path, (NOW, NOW))
    sent = []
    assert len(w.run(NOW, project_dir=project, post=lambda text: sent.append(text) or True)) == 2
    assert len(sent) == 1 and "Recipe preview" in sent[0] and "Calendar sync" in sent[0]


def test_a_normal_chat_and_an_old_chat_are_quiet(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("OPENMATES_USAGE_WATCH_FILE", str(tmp_path / "state.json"))
    project = tmp_path / "project"
    transcript = make_chat(project, [usage_line(input_tokens=1000)], agents=3)
    os.utime(transcript, (NOW, NOW))
    assert w.run(NOW, project_dir=project, post=lambda text: True) == []
    transcript.write_text(usage_line(input_tokens=w.TOKEN_NOTICE_UNITS))
    os.utime(transcript, (NOW - 2 * w.ACTIVE_WITHIN_SECONDS,) * 2)
    assert w.run(NOW, project_dir=project, post=lambda text: True) == []


def test_reap_entry_point_starts_a_detached_scan_at_most_every_ten_minutes(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_USAGE_WATCH_FILE", str(tmp_path / "state.json"))
    started = []
    w.save_state(tmp_path / "state.json", {"files": {}, "notified": {}, "last_scan": NOW})
    assert not w.maybe_scan(NOW + 60, spawn=started.append)
    assert w.maybe_scan(NOW + w.SCAN_EVERY_SECONDS, spawn=started.append)
    assert started and started[0][-1] == "scan"
    assert not w.maybe_scan(NOW + w.SCAN_EVERY_SECONDS + 60, spawn=started.append)  # one still running
    assert len(started) == 1


def test_notice_names_the_chat_by_title_and_handoff_state(tmp_path):
    """Owner, 23 Nov: plain-words title, not just the id, and whether a handoff happened."""
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "sessions.json").write_text(json.dumps(
        {"sessions": {"ab12": {"agent_task_id": CHAT, "task": "Projects live preview recipe proof"}}}))
    project = tmp_path / "project"
    other = "ffffffff-0000"
    project.mkdir()
    (project / f"{other}.jsonl").write_text(json.dumps(
        {"type": "user", "message": {"content": "Fix the   calendar sync on Apple Watch"}}) + "\n")
    totals = {CHAT: {"units": w.TOKEN_NOTICE_UNITS, "agents": 1},
              other: {"units": 1.0, "agents": w.AGENT_NOTICE_COUNT}}
    found = dict(w.notices(totals, {}, NOW, root=root, project_dir=project))
    assert found[CHAT].startswith('"Projects live preview recipe proof"')
    assert "No handoff yet; it is told to hand off" in found[CHAT]
    assert found[other].startswith('"Fix the calendar sync on Apple Watch"')
    assert "No handoff yet (compacted 0 times" in found[other]
    lifecycle = root / "logs" / "claude-chat-lifecycle"
    lifecycle.mkdir(parents=True)
    (lifecycle / "handed_off.json").write_text(json.dumps({CHAT: {"successor": "pane 3"}}))
    found = dict(w.notices(totals, {}, NOW, root=root, project_dir=project))
    assert "It already handed off to a fresh chat." in found[CHAT]


def test_oversized_chats_are_listed_for_the_handoff_hook(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("OPENMATES_USAGE_WATCH_FILE", str(tmp_path / "state.json"))
    project = tmp_path / "project"
    make_chat(project, [usage_line(input_tokens=w.TOKEN_NOTICE_UNITS)])
    os.utime(project / f"{CHAT}.jsonl", (NOW, NOW))
    w.run(NOW, project_dir=project, post=lambda text: True)
    assert json.loads((tmp_path / "state.json").read_text())["oversized"] == {CHAT: w.TOKEN_NOTICE_UNITS}


def test_codex_scan_uses_cumulative_counters_once_and_reports_title(tmp_path, monkeypatch):
    import os

    rollout = tmp_path / "rollout.jsonl"
    chat = "58dadecc-e0cb-421c-905c-b9df66e5eb13"
    monkeypatch.setattr(w.codex_chats, "records", lambda: [
        {"chat_id": chat, "thread_id": "unused", "title": "Ship calendar sync"},
    ])
    monkeypatch.setattr(w.codex_chats, "rollout_path", lambda _: rollout)
    monkeypatch.setattr(w, "canonical_root", lambda: tmp_path)
    monkeypatch.setenv("OPENMATES_USAGE_WATCH_FILE", str(tmp_path / "state.json"))

    row = json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": 110000000, "cached_input_tokens": 10000000, "output_tokens": 200},
    }}}) + "\n"
    rollout.write_text(row + row)
    os.utime(rollout, (NOW, NOW))
    sent = []
    assert w.run(NOW, project_dir=tmp_path / "claude", post=lambda text: sent.append(text) or True)
    assert 'Ship calendar sync' in sent[0] and '101M weighted tokens' in sent[0]
    assert 'No handoff yet' in sent[0]
    assert w.run(NOW, project_dir=tmp_path / "claude", post=lambda text: sent.append(text) or True) == []
    assert len(sent) == 1
