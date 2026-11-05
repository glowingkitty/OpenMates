"""Scoped user decision contracts for developer workflow tooling.

Receipts retain provenance identifiers and hashes, never private message text.
Synthetic message stores prove role, scope and revision rejection.
The same matching function serves completion and continuation consumers.
Run with pytest; no live chat or product state is accessed.
"""

# contract-test-file: tooling
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _workflow_decisions import make_receipt, matching_receipt


def user_message(source):
    return {"role": "user", "text": "Stop the UI proof for this task."}


def receipt():
    return make_receipt(
        target="task-1",
        surface="proof",
        revision="abc1234",
        decision="stop",
        source={"provider": "codex", "session_id": "ses-1", "message_id": "msg-1"},
        quote="Stop the UI proof",
        read_message=user_message,
    )


def test_exact_scope_survives_reload_and_only_suppresses_selected_work():
    import json

    record = json.loads(json.dumps(receipt()))
    assert matching_receipt(
        [record],
        target="task-1",
        surface="proof",
        revision="abc1234",
        read_message=user_message,
    )
    for overrides in (
        {"target": "task-2"},
        {"surface": "functional"},
        {"revision": "changed"},
    ):
        scope = dict(target="task-1", surface="proof", revision="abc1234")
        scope.update(overrides)
        assert matching_receipt([record], **scope, read_message=user_message) is None
    assert "Stop the UI" not in json.dumps(record)


def test_appearance_acceptance_is_not_a_proof_waiver():
    record = receipt()
    record["decision"] = "accept"
    assert (
        matching_receipt(
            [record],
            target="task-1",
            surface="proof",
            revision="abc1234",
            read_message=user_message,
        )
        is None
    )


def test_forged_or_missing_provenance_never_grants_waiver():
    for message in (
        {"role": "assistant", "text": "Stop the UI proof"},
        {"role": "user", "text": "Different message"},
    ):
        with pytest.raises(ValueError):
            make_receipt(
                target="task-1",
                surface="proof",
                revision="abc1234",
                decision="stop",
                source={
                    "provider": "codex",
                    "session_id": "ses-1",
                    "message_id": "msg-1",
                },
                quote="Stop the UI proof",
                read_message=lambda _: message,
            )
    record = receipt()
    record["source"]["text_sha256"] = "forged"
    assert (
        matching_receipt(
            [record],
            target="task-1",
            surface="proof",
            revision="abc1234",
            read_message=user_message,
        )
        is None
    )


def test_new_explicit_resume_supersedes_stop():
    stopped = receipt()
    resumed = {**stopped, "decision": "resume"}
    assert (
        matching_receipt(
            [stopped, resumed],
            target="task-1",
            surface="proof",
            revision="abc1234",
            read_message=user_message,
        )
        is None
    )


def test_plan_verifier_accepts_only_scoped_proof_waiver(monkeypatch):
    import _workflow_decisions as decisions
    import plan_verify

    monkeypatch.setattr(decisions, "read_user_message", user_message)
    r = receipt()
    data = {
        "id": "task-1",
        "decisions": [r],
        "implementation_state": {"subject_commit": "abc1234"},
        "demonstration": {
            "eligibility": {"status": "required"},
            "evidence": {"status": "waived", "decision_id": r["id"]},
        },
    }
    assert plan_verify._demonstration_failures(data) == []
    data["implementation_state"]["subject_commit"] = "changed"
    assert plan_verify._demonstration_failures(data)
    data["implementation_state"]["subject_commit"] = "abc1234"
    data["decisions"][0]["surface"] = "appearance"
    assert plan_verify._demonstration_failures(data)




def test_task_bookkeeping_does_not_invalidate_instruction_scope():
    import sessions

    task = {
        "title": "Fix UI",
        "description": "Show model",
        "latest_instruction": "Stop proof",
        "version": 1,
    }
    original = sessions._task_decision_revision(task)
    assert (
        sessions._task_decision_revision({**task, "version": 2, "status": "done"})
        == original
    )
    assert (
        sessions._task_decision_revision({**task, "description": "Different UI"})
        != original
    )


def test_missing_history_does_not_restart_stopped_work_or_grant_a_pass():
    record = receipt()

    def missing(_):
        raise FileNotFoundError("History unavailable")

    scope = dict(
        target="task-1", surface="proof", revision="abc1234", read_message=missing
    )
    assert matching_receipt([record], **scope) is None
    assert (
        matching_receipt([record], preserve_stop=True, **scope)["provenance_status"]
        == "unavailable"
    )


CLAUDE_SESSION = "6f1c2b9e-3d4a-4c1e-9a2b-1234567890ab"


def _write_claude_transcript(home, rows):
    import json

    project = home / "projects" / "-home-dev-project"
    project.mkdir(parents=True)
    (project / f"{CLAUDE_SESSION}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_claude_transcript_human_turn_is_the_decision_source(tmp_path, monkeypatch):
    import _workflow_decisions as decisions

    human = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    _write_claude_transcript(tmp_path, [
        {"type": "user", "uuid": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "sessionId": CLAUDE_SESSION,
         "message": {"role": "user", "content": [{"type": "tool_result", "content": "Stop the UI proof"}]}},
        {"type": "user", "uuid": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "sessionId": CLAUDE_SESSION,
         "origin": {"kind": "task-notification"}, "message": {"role": "user", "content": "Stop the UI proof"}},
        {"type": "user", "uuid": human, "sessionId": CLAUDE_SESSION, "origin": {"kind": "human"},
         "message": {"role": "user", "content": "Please stop the UI proof for this task."}},
        {"type": "assistant", "uuid": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
         "message": {"role": "assistant", "content": "Stop the UI proof"}},
    ])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    source = {"provider": "claude", "session_id": CLAUDE_SESSION, "message_id": ""}
    source["message_id"] = decisions.find_user_message_id(source, "stop the UI proof")
    assert source["message_id"] == human
    record = make_receipt(target="task-1", surface="proof", revision="abc1234", decision="stop",
                          source=source, quote="stop the UI proof")
    assert record["source"]["provider"] == "claude"
    assert matching_receipt([record], target="task-1", surface="proof", revision="abc1234")
    with pytest.raises(ValueError):
        decisions.read_user_message({**source, "message_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"})
    with pytest.raises(ValueError, match="invalid Claude session id"):
        decisions.read_user_message({**source, "session_id": "../escape"})
