"""Dispatch contract: explicit permissions and no duplicate work after uncertainty.

Uses a protocol fake, without creating chats or running provider calls. Focused
checks cover accepted replay, mismatched operation IDs and lost start replies.
"""

import pytest
from scripts.codex_worker import dispatch


class RPC:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def call(self, method, args):
        self.calls.append((method, args))
        if method == self.fail:
            raise TimeoutError("reply lost")
        return {"thread": {"id": "worker"}, "turn": {"id": "turn"}}


def intent():
    return dict(
        action="create",
        root="/repo",
        title="Worker",
        prompt="Do approved work",
        full_access=True,
    )


# contract-test: tooling
def test_create_registers_before_start_and_sets_explicit_permissions():
    rpc = RPC()
    record = {}
    checkpoints = []
    dispatch(
        rpc,
        record,
        intent(),
        lambda r: checkpoints.append(dict(r)),
        lambda t: checkpoints.append({"registered": t}),
    )
    assert record["state"] == "accepted"
    assert rpc.calls[0][1]["sandbox"] == "danger-full-access"
    assert rpc.calls[-1][1]["sandboxPolicy"] == {"type": "dangerFullAccess"}
    assert rpc.calls[-1][1]["approvalPolicy"] == "never"
    assert checkpoints[0]["state"] == "pending"
    assert {"registered": "worker"} in checkpoints
    count = len(rpc.calls)
    dispatch(rpc, record, intent(), lambda r: None, lambda t: None)
    assert len(rpc.calls) == count


# contract-test: tooling
def test_lost_reply_preserves_known_identity_and_does_not_retry():
    rpc = RPC("turn/start")
    record = {}
    with pytest.raises(TimeoutError):
        dispatch(rpc, record, intent(), lambda r: None, lambda t: None)
    assert record["state"] == "needs_review" and record["thread_id"] == "worker"
    count = len(rpc.calls)
    dispatch(rpc, record, intent(), lambda r: None, lambda t: None)
    assert len(rpc.calls) == count


# contract-test: tooling
def test_operation_reuse_with_changed_prompt_rejected():
    rpc = RPC()
    record = {}
    dispatch(rpc, record, intent(), lambda r: None, lambda t: None)
    with pytest.raises(ValueError):
        dispatch(
            rpc,
            record,
            {**intent(), "prompt": "different"},
            lambda r: None,
            lambda t: None,
        )


# contract-test: tooling
def test_default_does_not_escalate_permissions():
    rpc = RPC()
    dispatch(rpc, {}, dict(intent(), full_access=False), lambda r: None, lambda t: None)
    assert "sandbox" not in rpc.calls[0][1]
    assert "sandboxPolicy" not in rpc.calls[-1][1]


# contract-test: tooling
def test_message_resumes_unloaded_thread_before_start():
    rpc = RPC()
    dispatch(
        rpc,
        {},
        dict(intent(), action="message", thread="old"),
        lambda r: None,
        lambda t: None,
    )
    assert [m for m, _ in rpc.calls] == ["thread/resume", "turn/start"]
    assert rpc.calls[0][1]["excludeTurns"] is True


# contract-test: tooling
def test_explicit_retry_only_replays_definite_message_rejection():
    data = dict(intent(), action="message", thread="old")
    rpc = RPC("turn/start")
    record = {}
    with pytest.raises(TimeoutError):
        dispatch(rpc, record, data, lambda r: None, lambda t: None)
    count = len(rpc.calls)
    dispatch(rpc, record, data, lambda r: None, lambda t: None, True)
    assert len(rpc.calls) == count
    record["error"] = "Codex turn/start rejected: -32600"
    rpc.fail = None
    dispatch(rpc, record, data, lambda r: None, lambda t: None, True)
    assert record["state"] == "accepted"
