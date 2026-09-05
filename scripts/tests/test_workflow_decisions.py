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
        source={"provider": "opencode", "session_id": "ses-1", "message_id": "msg-1"},
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
                    "provider": "opencode",
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


def test_queued_task_stop_cancels_delivery_and_does_not_cancel_unrelated(monkeypatch):
    import _workflow_decisions as decisions
    import sessions

    monkeypatch.setattr(decisions, "read_user_message", user_message)
    r = receipt()
    r["surface"] = "task"
    data = {"sessions": {"abcd": {"opencode_session_id": "ses-1", "decisions": [r]}}}
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    sessions._record_session_continuation(
        "abcd",
        operation_type="task_ready",
        operation_key="one",
        next_action="Resume",
        decision_scope={"target": "task-1", "surface": "task", "revision": "abc1234"},
    )
    assert sessions._claim_session_continuation("abcd") is None
    assert data["sessions"]["abcd"]["continuation"]["status"] == "cancelled"
    sessions._record_session_continuation(
        "abcd",
        operation_type="task_ready",
        operation_key="other",
        next_action="Resume",
        decision_scope={"target": "task-2", "surface": "task", "revision": "abc1234"},
    )
    assert sessions._claim_session_continuation("abcd")["status"] == "delivering"


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
