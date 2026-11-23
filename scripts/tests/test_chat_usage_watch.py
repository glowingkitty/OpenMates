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
    assert "100M weighted tokens and 40 sub-agents" in sent[0] and "Nothing was stopped" in sent[0]
    assert w.run(NOW + 60, project_dir=project, post=post) == []  # once per chat
    assert len(sent) == 1


def test_several_chats_crossing_together_bring_one_message(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("OPENMATES_USAGE_WATCH_FILE", str(tmp_path / "state.json"))
    project = tmp_path / "project"
    for chat in ("aaaaaaaa-1", "bbbbbbbb-2"):
        path = project / f"{chat}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(usage_line(input_tokens=w.TOKEN_NOTICE_UNITS))
        os.utime(path, (NOW, NOW))
    sent = []
    assert len(w.run(NOW, project_dir=project, post=lambda text: sent.append(text) or True)) == 2
    assert len(sent) == 1 and "aaaaaaaa" in sent[0] and "bbbbbbbb" in sent[0]


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
