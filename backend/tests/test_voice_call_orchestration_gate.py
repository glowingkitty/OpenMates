"""Call-side gate for interpreting turns (feature.video-call orchestration-continuity)."""

from __future__ import annotations

import asyncio

import pytest

try:
    from backend.core.api.app.routes import voice_call_orchestration as gate_module
except ImportError as _exc:  # pragma: no cover - backend deps missing locally
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")

EVENT = {"event_message_id": "event-2", "action": "report", "created_at": 2}


def _gate(monkeypatch, *, due=True, issue_error=None):
    calls: dict = {"sent": [], "issued": [], "dispatched": [], "requeued": [], "order": []}

    async def pending_due(**_):
        return due

    async def claim_events(**_):
        return [{"event_message_id": "event-1", "action": "finished", "created_at": 1}, EVENT]

    async def requeue_events(**kwargs):
        calls["requeued"].append(kwargs["events"])

    async def dispatch_interpretation(**kwargs):
        calls["order"].append("dispatch")
        calls["dispatched"].append(kwargs)
        return "task-1"

    async def bind_call(**_):
        return None

    for name, fn in {"pending_due": pending_due, "claim_events": claim_events, "requeue_events": requeue_events,
                     "dispatch_interpretation": dispatch_interpretation, "bind_call": bind_call}.items():
        monkeypatch.setattr(gate_module.interpretation, name, fn)

    async def issue(message_id):
        if issue_error:
            raise issue_error
        calls["issued"].append(message_id)

    async def send(event):
        calls["order"].append("send")
        calls["sent"].append(event)

    gate = gate_module.CallInterpretationGate(
        cache_service=object(), directus_service=object(), encryption_service=object(),
        user_id="user-1", chat_id="chat-1", call_id="a" * 32, issue=issue, send=send)
    asyncio.run(gate.bind(90))
    return gate, calls


def _quiet(monkeypatch, gate):
    clock = {"now": 1000.0}
    monkeypatch.setattr(gate_module.time, "monotonic", lambda: clock["now"])
    return clock


# contract-test: supporting surface=rest_api assertions=video-call.chat.orchestration-continuity
def test_no_turn_while_the_assistant_speaks_or_the_user_talks(monkeypatch) -> None:
    gate, calls = _gate(monkeypatch)
    clock = _quiet(monkeypatch, gate)
    asyncio.run(gate.tick(assistant_active=True, speech_pending=False))
    clock["now"] += 0.5
    asyncio.run(gate.tick(assistant_active=False, speech_pending=False))  # still inside the quiet window
    asyncio.run(gate.tick(assistant_active=False, speech_pending=True))
    clock["now"] += 1.0
    asyncio.run(gate.tick(assistant_active=False, speech_pending=False))
    assert calls["dispatched"] == []


# contract-test: supporting surface=rest_api assertions=video-call.chat.orchestration-continuity
def test_quiet_call_speaks_the_combined_updates_once(monkeypatch) -> None:
    gate, calls = _gate(monkeypatch)
    clock = _quiet(monkeypatch, gate)
    asyncio.run(gate.tick(assistant_active=True, speech_pending=False))
    clock["now"] += 2
    asyncio.run(gate.tick(assistant_active=False, speech_pending=False))
    assert calls["issued"] == ["event-2"]
    assert calls["order"] == ["send", "dispatch"]  # the client learns the turn before any answer arrives
    assert calls["sent"][0] == {"type": "orchestration_turn", "call_id": "a" * 32, "message_id": "event-2"}
    dispatched = calls["dispatched"][0]
    assert [e["event_message_id"] for e in dispatched["events"]] == ["event-1", "event-2"]
    assert dispatched["voice_delivery"] == {"voice_mode": True, "voice_call_id": "a" * 32, "voice_turn_id": "event-2",
                                            "voice_heard_boundary": None, "auto_speak_response": True}


# contract-test: supporting surface=rest_api assertions=video-call.chat.orchestration-continuity
def test_updates_not_yet_due_wait(monkeypatch) -> None:
    gate, calls = _gate(monkeypatch, due=False)
    clock = _quiet(monkeypatch, gate)
    clock["now"] += 5
    asyncio.run(gate.tick(assistant_active=False, speech_pending=False))
    assert calls["dispatched"] == [] and calls["sent"] == []


# contract-test: supporting surface=rest_api assertions=video-call.chat.orchestration-continuity
def test_ended_call_hands_the_updates_back_for_a_text_turn(monkeypatch) -> None:
    gate, calls = _gate(monkeypatch, issue_error=ValueError("Call message not authorized"))
    clock = _quiet(monkeypatch, gate)
    clock["now"] += 5
    asyncio.run(gate.tick(assistant_active=False, speech_pending=False))
    assert calls["dispatched"] == [] and calls["sent"] == []
    assert [e["event_message_id"] for e in calls["requeued"][0]] == ["event-1", "event-2"]
