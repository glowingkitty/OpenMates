# contract-test-file: tooling
"""Compaction counter, policy notes and handoff prompt of scripts/chat_compaction_handoff.py."""

import argparse
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import chat_compaction_handoff as h  # noqa: E402


@pytest.fixture(autouse=True)
def no_host_usage_state(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_USAGE_GUARD_DIR", str(tmp_path / "usage-guard"))


NOTE = """## Done
Live preview renders (commit abc123).
## Not done
Final proof video.
## Next step
Rerun the recipe proof on dev.
## Open decisions
none
## References
Commit abc123, frontend/apps/web_app/tests/x.spec.ts, session ab12
"""


def _run(tmp_path, chat="c1", **extra):
    payload = {"source": "compact", "session_id": chat, **extra}
    return h.hook(json.dumps(payload), tmp_path / "c.json")


def test_counts_per_chat_and_policy(tmp_path):
    """Owner, 23 Nov: announce at the 1st compaction, hand off from the 2nd on."""
    first = _run(tmp_path)
    assert "compacted 1 time" in first and "next compaction" in first
    assert "Hand off NOW" in _run(tmp_path)
    assert "Hand off NOW" in _run(tmp_path)  # 3rd still instructs
    assert "next compaction" in _run(tmp_path, chat="c2")
    assert json.loads((tmp_path / "c.json").read_text())["c2"] == 1

def test_only_compact_counts(tmp_path):
    for source in ("startup", "resume", "clear"):
        assert h.hook(json.dumps({"source": source, "session_id": "c1"}), tmp_path / "c.json") == ""
    assert not (tmp_path / "c.json").exists()


def test_note_text_names_the_note_sections():
    assert h.policy_note(0) == "" and "next compaction" in h.policy_note(1)
    now = h.policy_note(2)
    assert "NOW" in now and all(name in now for name in h.NOTE_SECTIONS) and "send no push" in now


def test_subagent_ignored(tmp_path):
    for _ in range(5):
        assert _run(tmp_path, agent_id="a1") == ""
    assert not (tmp_path / "c.json").exists()


def test_fails_open(tmp_path):
    assert h.hook("not json", tmp_path / "c.json") == ""
    assert h.hook("[]", tmp_path / "c.json") == ""
    assert h.hook(json.dumps({"source": "compact", "session_id": "x"}), tmp_path / "missing" / "\0") == ""


def test_handoff_dry_run_builds_prompt_without_launching(tmp_path, capsys):
    summary = tmp_path / "s.md"
    summary.write_text(NOTE)
    sessions = tmp_path / ".claude"
    sessions.mkdir()
    (sessions / "sessions.json").write_text(json.dumps(
        {"sessions": {"ab12": {"agent_task_id": "chat-1", "worktree": {"path": "/wt/ab12"}}}}))
    args = argparse.Namespace(summary_file=str(summary), session="", chat="chat-1", task="", dry_run=True)
    with mock.patch.object(h, "canonical_root", return_value=tmp_path), \
         mock.patch.object(h, "_find_task", return_value="task-9"), \
         mock.patch.dict(sys.modules, {"claude_dispatch": mock.Mock()}) as mods:
        assert h.handoff(args) == 0
        mods["claude_dispatch"].launch_claude_chat.assert_not_called()
    out = json.loads(capsys.readouterr().out)
    assert out["session"] == "ab12" and out["task"] == "task-9"
    assert "worktree bind-task --session ab12" in out["prompt"] and "Commit abc123" in out["prompt"]


def test_note_sections_are_required():
    assert h.missing_sections(NOTE) == []
    assert h.missing_sections("Done: X\nNot done: Y\nNext steps: Z\nOpen decisions: none\nReferences: abc") == []
    assert h.missing_sections("## Done\nX\n## Not done\n## Next step\nZ") == ["Not done", "Open decisions",
                                                                               "References"]
    assert h.missing_sections("I am done with this and have not done much") == list(h.NOTE_SECTIONS)


def test_handoff_refuses_a_note_without_sections_and_a_chat_with_several_tasks(tmp_path, capsys):
    bad = tmp_path / "bad.md"
    bad.write_text("Goal: ship X")
    args = argparse.Namespace(summary_file=str(bad), session="", chat="chat-1", task="", dry_run=False)
    assert h.handoff(args) == 2 and "lacks Done, Not done" in capsys.readouterr().err
    good = tmp_path / "good.md"
    good.write_text(NOTE)
    args.summary_file = str(good)
    with mock.patch.object(h, "canonical_root", return_value=tmp_path), \
         mock.patch.object(h, "_find_task", return_value=""):
        assert h.handoff(args) == 2 and "pass --task" in capsys.readouterr().err


def test_handoff_writes_the_note_to_the_task_and_archives_the_old_chat(tmp_path):
    good = tmp_path / "good.md"
    good.write_text(NOTE)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "sessions.json").write_text(json.dumps({"sessions": {}}))
    args = argparse.Namespace(summary_file=str(good), session="", chat="chat-1", task="task-9", dry_run=False)
    dispatch = mock.Mock()
    dispatch.ChatQueued = type("ChatQueued", (Exception,), {})
    dispatch.DispatchError = type("DispatchError", (Exception,), {})
    dispatch.launch_claude_chat.return_value = "pane %7"
    with mock.patch.object(h, "canonical_root", return_value=tmp_path), \
         mock.patch.object(h.subprocess, "run") as run, \
         mock.patch.dict(sys.modules, {"claude_dispatch": dispatch}):
        run.side_effect = [
            mock.Mock(returncode=0, stdout='{"task":{"external_chat":{"provider":"claude","id":"chat-1"}}}'),
            mock.Mock(returncode=0, stdout='{"entry":{"message":"note"}}'),
            mock.Mock(returncode=0, stdout='{"task":{"external_chat":null}}'),
        ]
        assert h.handoff(args) == 0
        assert h.handoff(args) == 0
        dispatch.launch_claude_chat.assert_called_once()
        assert run.call_args_list[-1].args[0][2:] == [
            "release", "task-9", "--external-chat", "claude:chat-1", "--json",
        ]
    messages = [call.args[0][6] for call in run.call_args_list if "activity" in call.args[0]]
    assert "Handoff note of chat chat-1" in messages[0] and "Rerun the recipe proof" in messages[0]
    assert "Handoff note from the old chat" in dispatch.launch_claude_chat.call_args.args[1]
    marker = json.loads((tmp_path / "logs" / "claude-idle-chats" / "questions" / "chat-1.json").read_text())
    assert marker["kind"] == "✅" and marker["ts"] > 0
    handed = json.loads((tmp_path / "logs" / "claude-chat-lifecycle" / "handed_off.json").read_text())
    assert handed["chat-1"]["successor"] == "pane %7"


def test_prompt_hook_repeats_the_note_for_due_chats_only(tmp_path):
    paths = {"counts_path": tmp_path / "c.json", "usage_path": tmp_path / "u.json",
             "handed_path": tmp_path / "h.json"}
    prompt = lambda chat, **extra: h.hook_prompt(json.dumps({"session_id": chat, **extra}), **paths)  # noqa: E731
    (tmp_path / "c.json").write_text(json.dumps({"twice": 2, "once": 1}))
    (tmp_path / "u.json").write_text(json.dumps({"oversized": {"big": 572_000_000}}))
    assert "Hand off NOW" in prompt("twice") and "compacted 2 times" in prompt("twice")
    assert "oversized: 572M weighted tokens" in prompt("big")
    assert prompt("once") == "" and prompt("twice", agent_id="a1") == ""
    (tmp_path / "h.json").write_text(json.dumps({"twice": {"successor": "x"}}))
    assert prompt("twice") == ""
    assert h.hook_prompt("not json", **paths) == ""

def test_codex_uses_native_compaction_records_and_context_window(tmp_path):
    transcript = tmp_path / "rollout.jsonl"
    paths = dict(counts_path=tmp_path / "c.json", usage_path=tmp_path / "u.json", handed_path=tmp_path / "h.json",
                 codex_path=transcript)
    prompt = json.dumps({"session_id": "codex-1", "codex_thread_id": "native-thread"})
    compacted = {"type": "compacted", "payload": {}}
    extra = {"type": "event_msg", "payload": {"type": "context_compacted"}}
    transcript.write_text("".join(json.dumps(row) + "\n" for row in [compacted, extra]))
    assert not h.hook_prompt(prompt, **paths)
    with transcript.open("a") as stream:
        stream.write(json.dumps(compacted) + "\n")
    assert "compacted 2 times" in h.hook_prompt(prompt, **paths)
    transcript.write_text(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": 410000, "cached_input_tokens": 12345, "output_tokens": 100},
        "last_token_usage": {"input_tokens": 390000}, "model_context_window": 475000,
    }}}) + "\n")
    assert "80% of its context window" in h.hook_prompt(prompt, **paths)


def test_handoff_needs_confirmed_activity_and_task_release(tmp_path):
    dispatch = mock.Mock()
    task = {"external_chat": {"provider": "claude", "id": "chat-1"}, "status": "todo"}
    for replies in (
        [mock.Mock(returncode=0, stdout='{"delivery":{"status":"pending"}}', stderr="")],
        [mock.Mock(returncode=0, stdout='{"entry": {"message":"note"}}'),
         mock.Mock(returncode=1, stdout='{"error":{}}', stderr="Task link belongs to a different chat")],
    ):
        with mock.patch.object(h.subprocess, "run", side_effect=replies), \
             mock.patch.dict(sys.modules, {"claude_dispatch": dispatch}):
            assert h.launch_successor(tmp_path, "chat-1", "ab12", "task-id", "Title", "Prompt", NOTE,
                                      task=task) == 2
    dispatch.launch_claude_chat.assert_not_called()
    assert not h.handed_off_file(tmp_path).exists()


def test_claude_oversized_context_blocks_the_first_stop(tmp_path):
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(json.dumps({"type": "assistant", "message": {"usage": {
        "input_tokens": 2000, "cache_read_input_tokens": 181000,
    }}}) + "\n")
    payload = {"session_id": "test-chat", "transcript_path": str(transcript)}
    with mock.patch.object(h, "canonical_root", return_value=tmp_path):
        blocked = json.loads(h.hook_stop(json.dumps(payload)))
        assert blocked["decision"] == "block" and "180,000 tokens" in blocked["reason"]
        assert not h.hook_stop(json.dumps({**payload, "stop_hook_active": True}))

def test_paused_note_is_reused_for_reserve_handover(tmp_path, monkeypatch):
    source = "0b6c7f1e-1111-4222-8333-944455556667"
    for key in ("OPENMATES_CHAT_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.setenv(key, "another-chat")
    monkeypatch.setattr(h, "canonical_root", lambda: tmp_path)
    monkeypatch.setattr(h, "_find_task", lambda chat, hint: "task-id")
    replies = [
        mock.Mock(returncode=0, stdout=json.dumps({"task": {
            "external_chat": {"provider": "claude", "id": source}, "status": "todo",
        }})),
        mock.Mock(returncode=0, stdout=json.dumps({"entries": [{"message": "Handoff note\n" + NOTE}]})),
    ]
    with mock.patch.object(h.subprocess, "run", side_effect=replies), \
         mock.patch.dict(sys.modules, {"claude_dispatch": mock.Mock(codex_wait_reason=lambda: "")}), \
         mock.patch.object(h, "launch_successor", return_value=0) as launch:
        assert h.resume_on_codex(source, "CI finished", admitted=True) == "ok"
    assert launch.call_args.kwargs == {"codex": True, "admitted": True, "note_already_saved": True,
                                      "task": {"status": "todo", "external_chat": {
                                          "provider": "claude", "id": source}}}
    assert "CI finished" in launch.call_args.args[5]


def test_saved_note_requires_sections_before_transfer():
    assert h.saved_handoff({"entries": [{"message": "Handoff note\nJust try again."}]}) == ""
    old = "\n".join(("HANDOFF for a fresh Codex chat, dev commit abc123.",
                     "DONE on dev: Recipe preview", "NOT DONE: Video", "NEXT: Run proof", "OPEN: none"))
    assert h.missing_sections(h.saved_handoff({"entries": [{"message": old}]})) == []


def test_waiter_can_name_one_of_several_linked_tasks(monkeypatch):
    source = "0b6c7f1e-1111-4222-8333-944455556667"
    first = "5ba50f79-a8cb-4f8b-b6d1-000000000000"
    second = "3c85715e-a812-4f8b-b6d1-000000000000"
    tasks = [{"task_id": key, "status": "todo", "external_chat": {"provider": "claude", "id": source}}
             for key in (first, second)]
    monkeypatch.setattr(h.subprocess, "run", lambda *args, **kwargs:
                        mock.Mock(returncode=0, stdout=json.dumps({"tasks": tasks})))
    assert not h._find_task(source)
    assert h._find_task(source, "Resume from Task 5ba50f79") == first


def test_handover_can_locate_an_archived_workspace(tmp_path, monkeypatch):
    folder = tmp_path / ".claude"
    folder.mkdir()
    record = {"agent_task_id": None, "archived_agent_task_id": "old-chat"}
    (folder / "sessions.json").write_text(json.dumps({"sessions": {"ab12": record}}))
    monkeypatch.setattr(h, "canonical_root", lambda: tmp_path)
    assert h._find_session("old-chat") == ""
    assert h._find_session("old-chat", include_archived=True) == "ab12"


def test_archived_workspace_handover_leaves_binding_available_for_successor(tmp_path):
    data = {"sessions": {"ab12": {"agent_task_id": None, "archived_agent_task_id": "old-chat"}}}
    sessions = mock.Mock(_mutate_sessions=lambda change: change(data))
    dispatch = mock.Mock()
    dispatch.ChatQueued = type("ChatQueued", (Exception,), {})
    dispatch.DispatchError = type("DispatchError", (Exception,), {})
    dispatch.launch_claude_chat.return_value = "Codex tab"
    release = mock.Mock(returncode=0, stdout='{"task":{"external_chat":null}}')
    with mock.patch.object(h.subprocess, "run", return_value=release), \
         mock.patch.dict(sys.modules, {"sessions": sessions, "claude_dispatch": dispatch}):
        used = h.launch_successor(tmp_path, "old-chat", "ab12", "task-id", "Title", "Prompt", NOTE,
                                  note_already_saved=True, codex=True)
    assert used == 0 and data["sessions"]["ab12"]["agent_task_id"] is None
    assert h.handed_off_file(tmp_path).is_file()


def test_host_cli_calls_have_no_unrelated_chat_identity(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "operator")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "operator")
    monkeypatch.setenv("OPENMATES_CHAT_ID", "operator")
    with mock.patch.object(h.subprocess, "run") as run:
        h.task_cli("show", "task-id")
    env = run.call_args.kwargs["env"]
    assert not {"CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "OPENMATES_CHAT_ID"} & env.keys()


def test_stopped_source_without_note_recovers_but_running_source_is_refused(tmp_path, monkeypatch):
    source = "0b6c7f1e-1111-4222-8333-944455556667"
    details = {"task_id": "task-id", "status": "todo",
               "external_chat": {"provider": "claude", "id": source}}
    monkeypatch.setattr(h, "canonical_root", lambda: tmp_path)
    monkeypatch.setattr(h, "source_running", lambda _: True)
    with mock.patch.object(h, "task_cli") as cli:
        assert h.resume_on_codex(source, "CI finished", task_id="task-id") == "The source chat is still running"
        cli.assert_not_called()
    monkeypatch.setattr(h, "source_running", lambda _: False)
    with mock.patch.object(h, "task_cli", side_effect=[
        mock.Mock(returncode=0, stdout=json.dumps({"task": details})),
        mock.Mock(returncode=0, stdout='{"entries":[]}'),
    ]), mock.patch.dict(sys.modules, {"claude_dispatch": mock.Mock(codex_wait_reason=lambda: "")}), \
            mock.patch.object(h, "launch_successor", return_value=0) as launch:
        assert h.resume_on_codex(source, "CI finished", task_id="task-id") == "ok"
    assert "No complete handoff note" in launch.call_args.args[5]


def test_live_different_task_owner_is_never_released(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "task_links", lambda _: {"claude:source"})
    monkeypatch.setattr(h, "owner_is_stopped", lambda *_: False)
    with mock.patch.object(h, "task_cli") as cli:
        assert h.launch_successor(tmp_path, "source", "", "task-id", "Title", "Prompt", NOTE,
                                  task={"external_chat": {"provider": "codex", "id": "other"}}) == 2
    cli.assert_not_called()
