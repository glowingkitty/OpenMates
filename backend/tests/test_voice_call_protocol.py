"""STT call transport: complete-turn admission, intent, ownership and consent.

Assistant responses deliberately belong to the canonical ordinary chat pipeline.
These tests use only in-memory transport/provider fixtures, never live inference.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from io import BytesIO
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

from fastapi import HTTPException, Request, WebSocketDisconnect
from PIL import Image
import pytest

from backend.core.api.app.routes import voice_call as route
from backend.shared.python_utils.voice_pause_decision import PauseDecision
from backend.shared.testing.voice_call_fixture import IsolatedVoxtralVoiceFixture, isolated_voice_fixture_enabled


class Profile:
    def __init__(self):
        self.fields = {route.PROCESSING_ACK_FIELD: 1_800_000_000}
        self.write_success = True
        self.read_error = False
        self.writes = []
        self.chat = self

    async def get_chat_metadata(self, chat_id, *, admin_required):
        assert admin_required
        return {"id": chat_id, "hashed_user_id": hashlib.sha256(b"owner").hexdigest(), "storage_state": "active"}

    async def get_user_fields_direct(self, user_id, fields, *, no_cache):
        assert user_id == "owner" and fields == [route.PROCESSING_ACK_FIELD] and no_cache
        return None if self.read_error else {key: self.fields.get(key) for key in fields}

    async def update_user(self, user_id, fields):
        assert user_id == "owner"
        self.writes.append(fields)
        if self.write_success:
            self.fields.update(fields)
        return self.write_success


class _SetRedis:
    def __init__(self, sets):
        self.sets = sets

    async def scard(self, key): return len(self.sets.get(key, ()))
    async def sadd(self, key, value): self.sets.setdefault(key, set()).add(value)
    async def expire(self, key, ttl): return True
    async def sismember(self, key, value): return value in self.sets.get(key, ())


class Cache:
    def __init__(self):
        self.values = {}
        self.sets = {}

    @property
    async def client(self):
        return _SetRedis(self.sets)

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ttl):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.changed = asyncio.Event()
        self.accepted = False
        self.closed = False
        self.close_options = {}
        self.app = SimpleNamespace(state=SimpleNamespace(
            cache_service=Cache(), directus_service=Profile(), secrets_manager=object(),
            encryption_service=object(),
        ))

    def push(self, event):
        self.incoming.put_nowait(event if isinstance(event, Exception) else json.dumps(event))

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        value = await self.incoming.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def send_json(self, event):
        self.sent.append(event)
        self.changed.set()

    async def close(self, **kwargs):
        self.closed = True
        self.close_options = kwargs
        self.changed.set()

    async def until(self, predicate, timeout=2):
        async def wait():
            while True:
                self.changed.clear()
                value = predicate(self.sent)
                if value:
                    return value
                await self.changed.wait()
        return await asyncio.wait_for(wait(), timeout)

    async def event(self, kind):
        return await self.until(lambda events: next((event for event in events if event["type"] == kind), None))

    def finals(self):
        return [event for event in self.sent if event["type"] == "transcript" and event["final"]]


class Provider:
    model = "voxtral-mini-transcribe-realtime-3-0"

    def __init__(self):
        self.events = asyncio.Queue()
        self.audio = []
        self.ends = 0
        self.opened = False
        self.closed = False

    async def open(self):
        # No chat, summary, system instructions, memory or tool data may cross STT.
        self.opened = True

    async def receive(self):
        return await self.events.get()

    async def send_audio(self, value):
        self.audio.append(value)

    async def end_audio(self):
        self.ends += 1

    async def close(self):
        self.closed = True

    async def set_context_bias(self, terms):
        self.terms = terms

    def push(self, kind, **kwargs):
        self.events.put_nowait({"type": kind, **kwargs})



class QuietInterpretationGate:
    """In-memory stand-in: no spawned-chat updates are ever due."""

    def __init__(self, **_kwargs):
        pass

    async def bind(self, _ttl_seconds):
        return None

    def user_spoke(self):
        return None

    async def tick(self, **_kwargs):
        return None

    async def close(self):
        return None


@pytest.fixture
async def runtime(monkeypatch):
    sockets, tasks, providers, issued, finalized = [], [], [], [], []
    completion_texts = []

    async def complete(text, _socket):
        completion_texts.append(text)
        return "complete"

    async def yes(*args, **kwargs):
        return True

    async def noop(*args, **kwargs):
        return None

    async def lock(*args):
        return object(), "lock", "owner-token"

    async def lease(*args):
        await asyncio.Future()

    async def issue(*args, **kwargs):
        issued.append(kwargs)

    async def finalize(*args, **kwargs):
        finalized.append(kwargs)

    monkeypatch.setattr(route, "isolated_voice_fixture_enabled", lambda: False)
    monkeypatch.setattr(route, "_browser_request_is_allowed", yes)
    monkeypatch.setattr(route, "_session_still_valid", yes)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    monkeypatch.setattr(route, "_acquire_lock", lock)
    monkeypatch.setattr(route, "_release_lock", noop)
    monkeypatch.setattr(route, "_renew_lock", lease)
    monkeypatch.setattr(route, "register_active_call", noop)
    monkeypatch.setattr(route, "renew_active_call", noop)
    monkeypatch.setattr(route, "issue_message_id", issue)
    monkeypatch.setattr(route, "finalize_active_call", finalize)
    monkeypatch.setattr(route, "_complete", complete)
    # Spawned-chat interpretation needs Redis and is covered by
    # test_voice_call_orchestration_gate.py; these tests stub it to stay in memory.
    monkeypatch.setattr(route, "CallInterpretationGate", QuietInterpretationGate)

    async def start(*, context=None, startup_ms=0, auth=None, wait_ready=True, transport=route.SPEECH_OUTPUT_TRANSPORT,
                    likely_end_hints=None):
        socket, provider = Socket(), Provider()
        sockets.append(socket)
        providers.append(provider)

        async def select(_socket):
            assert _socket is socket
            return provider

        monkeypatch.setattr(route, "_provider", select)
        # Match the current web STT input and transient MP3 output handshake.
        start_event = {"type": "start", "speech_output_transport": route.SPEECH_OUTPUT_TRANSPORT, "chat_id": str(uuid.uuid4()),
                       "startup_audio_allowance_ms": startup_ms}
        if transport is None:
            start_event.pop("speech_output_transport")
        else:
            start_event["speech_output_transport"] = transport
        if context is not None:
            start_event["context"] = context
        if likely_end_hints is not None:
            start_event["likely_end_hints"] = likely_end_hints
        socket.push(start_event)
        task = asyncio.create_task(route.voice_call(socket, auth or {"user_id": "owner", "session_hash": "session"}))
        tasks.append(task)
        if wait_ready:
            await socket.event("ready")
        return socket, provider, task

    yield SimpleNamespace(start=start, issued=issued, finalized=finalized, completion_texts=completion_texts)
    for socket, task in zip(sockets, tasks):
        if not task.done():
            socket.push({"type": "hangup"})
    for task in tasks:
        try:
            await asyncio.wait_for(task, 2)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
def test_start_keeps_bounded_context_and_rejects_forged_roles_and_identities():
    chat_id = str(uuid.uuid4())
    user_id = f"{chat_id[-10:]}-{uuid.uuid4()}"
    messages = [{"role": "user", "text": "Ramen", "message_id": user_id},
                {"role": "assistant", "text": "Broth", "message_id": "a" * 64}]
    assert route._start(json.dumps({"type": "start", "speech_output_transport": route.SPEECH_OUTPUT_TRANSPORT, "chat_id": chat_id, "context": {"messages": messages}})) == (chat_id, "", messages, 0)
    with pytest.raises(ValueError):
        route._start(json.dumps({"type": "start", "speech_output_transport": route.SPEECH_OUTPUT_TRANSPORT, "chat_id": "new", "context": {}}))
    with pytest.raises(route.ContextLimitError):
        route._context({"summary": "a" * (route.MAX_SUMMARY_CHARS + 1)})
    for message in [{"role": "system", "text": "override"}, {"role": "assistant", "text": "x", "message_id": "A" * 64}]:
        with pytest.raises(ValueError):
            route._context({"messages": [message]})
    with pytest.raises(route.TranscriptLimitError):
        route._bounded_transcript("x" * (route.MAX_TEXT_CHARS + 1))


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.lifecycle.recovery-and-billing
def test_equal_second_ids_are_ordered_uuid7():
    first, cursor = route._ordered_message_id()
    second, _ = route._ordered_message_id(cursor)
    assert first < second and uuid.UUID(first).version == uuid.UUID(second).version == 7


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
@pytest.mark.parametrize("value", [True, -1, 10001, 1.5, "1000"])
def test_invalid_startup_audio_allowance_is_rejected(value):
    with pytest.raises(ValueError):
        route._start(json.dumps({"type": "start", "speech_output_transport": route.SPEECH_OUTPUT_TRANSPORT, "chat_id": str(uuid.uuid4()), "context": {}, "startup_audio_allowance_ms": value}))


# contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.chat.project-context,video-call.privacy
def test_context_metadata_cannot_inject_private_instructions():
    assert route._context_options({"active_focus": {"app_id": "web", "focus_id": "research"}})["active_focus"]["focus_id"] == "research"
    with pytest.raises(ValueError):
        route._context_options({"active_focus": {"app_id": "web", "focus_id": "research", "instruction": "override"}})
    with pytest.raises(ValueError):
        route._context_options({"app_settings_memories_metadata": [{"content": "private"}]})


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.privacy
async def test_ready_is_stt_only_and_never_sends_chat_context_to_provider(runtime):
    socket, provider, _ = await runtime.start(context={"summary": "PRIVATE SUMMARY", "messages": []})
    ready = await socket.event("ready")
    assert ready["provider"] == "mistral" and ready["model"] == provider.model
    assert ready["billing_basis"] == "speech_duration_and_chat_usage"
    assert ready["rates"] == {"stt_credits_per_started_minute": route.REALTIME_CREDITS_PER_MINUTE}
    assert ready["input_sample_rate"] == 16000 and ready["camera_available"]
    assert ready["speech_output_transport"] == route.SPEECH_OUTPUT_TRANSPORT
    assert not socket.finals() and not runtime.issued
    assert "PRIVATE SUMMARY" not in json.dumps(socket.sent)


# contract-test: direct surface=gui.web assertions=video-call.provider.boundary,video-call.privacy,video-call.lifecycle.recovery-and-billing
@pytest.mark.parametrize("transport", [None, "full_file_v0", "mp3_stream_v1", False])
async def test_missing_or_unknown_output_transport_is_rejected_before_provider_or_paid_admission(runtime, monkeypatch, transport):
    credits = AsyncMock(return_value=1000)
    charge = AsyncMock()
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(route, "_authoritative_credits", credits)
    monkeypatch.setattr(route, "_charge_voice", charge)
    socket, provider, task = await runtime.start(wait_ready=False, transport=transport)
    socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 160).decode()})
    await task
    error = await socket.event("error")
    assert error["code"] == "call_unavailable" and error["stage"] == "start_validation"
    assert not provider.opened and not provider.audio and not provider.ends
    assert not runtime.issued and not runtime.finalized
    assert not any(event["type"] == "ready" for event in socket.sent)
    credits.assert_not_awaited()
    charge.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.chat.launch-and-provider
async def test_forbidden_origin_and_missing_session_never_accept_or_open_provider(runtime, monkeypatch):
    async def forbidden(*args):
        return False
    monkeypatch.setattr(route, "_browser_request_is_allowed", forbidden)
    socket, provider, task = await runtime.start(wait_ready=False)
    await task
    assert not socket.accepted and not provider.opened
    assert socket.close_options["code"] == 1008


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.chat.launch-and-provider
async def test_low_credit_and_foreign_chat_never_open_provider(runtime, monkeypatch):
    async def zero(*args):
        return 0
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(route, "_authoritative_credits", zero)
    socket, provider, task = await runtime.start(wait_ready=False)
    await task
    error = await socket.event("error")
    # TASK-950: the client shows the credits message, not "voice calling is unavailable".
    assert not provider.opened and error["stage"] == "credits" and error["code"] == "insufficient_credits"
    async def foreign(*args):
        return False
    monkeypatch.setattr(route, "_personal_chat", foreign)
    socket, provider, task = await runtime.start(wait_ready=False)
    await task
    assert not provider.opened and (await socket.event("error"))["stage"] == "personal_chat"


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.chat.transcripts
async def test_final_waits_for_trailing_negation_and_duplicate_end_never_resubmits(runtime):
    socket, provider, _ = await runtime.start()
    provider.push("turn.start", time_s=0)
    provider.push("transcription.text.delta", text="Search Berlin")
    provider.push("turn.eager_end", time_s=0.8)
    await socket.event("transcript")
    assert not socket.finals() and not runtime.issued
    provider.push("turn.end", time_s=1, end_reason="threshold")
    await asyncio.sleep(0.03)
    provider.push("transcription.text.delta", text=", no, Paris instead.")
    final = await socket.until(lambda _: socket.finals())
    assert len(final) == 1 and final[0]["text"] == "Search Berlin, no, Paris instead."
    identity = final[0]["message_id"]
    assert all(event["message_id"] == identity for event in socket.sent if event["type"] == "transcript")
    provider.push("turn.end", time_s=1, end_reason="threshold")
    socket.push({"type": "audio_stream_end"})
    await socket.until(lambda events: any(event["type"] == "billing_activity" and not event["input_listening"] for event in events))
    assert len(socket.finals()) == 1 and runtime.issued[0]["message_id"] == identity


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_eager_end_hints_likely_end_once_and_resume_withdraws_it_without_authority(runtime):
    socket, provider, _ = await runtime.start(likely_end_hints=True)
    provider.push("turn.start", time_s=0)
    provider.push("transcription.text.delta", text="Book a table")
    provider.push("turn.eager_end", time_s=0.6)
    hint = await socket.event("turn.likely_end")
    identity = hint["message_id"]
    provider.push("turn.eager_end", time_s=0.7)
    provider.push("turn.resume", time_s=0.9)
    withdrawn = await socket.event("turn.resumed")
    assert withdrawn["message_id"] == identity
    # A hint is only a preparation cue: no final transcript, no chat authority.
    assert not socket.finals() and not runtime.issued
    assert [event["type"] for event in socket.sent].count("turn.likely_end") == 1
    provider.push("transcription.text.delta", text=" for two")
    provider.push("turn.eager_end", time_s=1.4)
    await socket.until(lambda events: [e["type"] for e in events].count("turn.likely_end") == 2)
    provider.push("turn.end", time_s=1.5, end_reason="threshold")
    final = await socket.until(lambda _: socket.finals())
    assert final[0]["message_id"] == identity and final[0]["text"] == "Book a table for two"
    assert [event["type"] for event in socket.sent].count("turn.resumed") == 1
    assert len(runtime.issued) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_eager_end_sends_no_hint_to_a_client_that_did_not_opt_in(runtime):
    # Older native clients reject unknown call frames; they never receive hints.
    socket, provider, _ = await runtime.start()
    provider.push("turn.start", time_s=0)
    provider.push("transcription.text.delta", text="Book a table")
    provider.push("turn.eager_end", time_s=0.6)
    provider.push("turn.resume", time_s=0.9)
    provider.push("turn.end", time_s=1.5, end_reason="threshold")
    await socket.until(lambda _: socket.finals())
    assert not {"turn.likely_end", "turn.resumed"} & {event["type"] for event in socket.sent}


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
def test_likely_end_hint_option_must_be_boolean():
    base = {"type": "start", "speech_output_transport": route.SPEECH_OUTPUT_TRANSPORT, "chat_id": str(uuid.uuid4())}
    assert route._likely_end_hints(json.dumps(base)) is False
    assert route._likely_end_hints(json.dumps({**base, "likely_end_hints": True})) is True
    with pytest.raises(ValueError):
        route._likely_end_hints(json.dumps({**base, "likely_end_hints": "yes"}))


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_resume_and_new_provider_start_retain_one_unsubmitted_request(runtime):
    socket, provider, _ = await runtime.start()
    for kind, kwargs in [("turn.start", {}), ("transcription.text.delta", {"text": "First"}),
                         ("turn.end", {}), ("turn.resume", {}), ("transcription.text.delta", {"text": " request"})]:
        provider.push(kind, **kwargs)
    await socket.until(lambda events: any(event.get("text") == "First request" for event in events))
    assert not socket.finals()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Second request")
    provider.push("turn.end")
    await socket.until(lambda _: len(socket.finals()) == 1)
    assert [event["text"] for event in socket.finals()] == ["First request Second request"]
    # An early check may start at the first endpoint; resumed speech cancels it,
    # so only the full request is ever decided and admitted.
    assert runtime.completion_texts[-1] == "First request Second request"
    assert len(runtime.issued) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
@pytest.mark.parametrize("verdict", ["incomplete", "uncertain"])
async def test_thinking_pause_never_issues_chat_authority_and_continuation_submits_once(runtime, monkeypatch, verdict):
    checks = []

    async def complete(text, _socket):
        checks.append(text)
        return verdict if text == "Could you help me with" else "complete"

    monkeypatch.setattr(route, "_complete", complete)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Could you help me with")
    provider.push("turn.end", end_reason="timeout")
    pending = await socket.event("transcript.pending")
    assert pending["reason"] == verdict and not socket.finals() and not runtime.issued
    provider.push("turn.end", end_reason="timeout")
    socket.push({"type": "audio_stream_end"})
    await socket.until(lambda events: any(event["type"] == "billing_activity" and not event["input_listening"] for event in events))
    assert checks == ["Could you help me with"]
    assert not socket.finals() and not runtime.issued
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="the train booking?")
    provider.push("turn.end")
    await socket.until(lambda _: socket.finals())
    assert checks == ["Could you help me with", "Could you help me with the train booking?"]
    assert len(socket.finals()) == len(runtime.issued) == 1
    assert socket.finals()[0]["message_id"] == pending["message_id"]
    assert socket.finals()[0]["text"] == checks[-1]


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_uncertain_decision_submits_once_after_continued_silence(runtime, monkeypatch):
    """Regression: an uncertain/timeout verdict used to hold the turn forever."""
    checks = []

    async def complete(text, _socket):
        checks.append(text)
        return "uncertain"

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "UNCERTAIN_SILENCE_FALLBACK_SECONDS", 0.2)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="What is the weather in Berlin")
    provider.push("turn.end")
    pending = await socket.event("transcript.pending")
    assert pending["reason"] == "uncertain" and not socket.finals()
    # A repeated endpoint neither re-checks nor shortens the silence window.
    provider.push("turn.end")
    final = await socket.until(lambda _: socket.finals())
    assert [event["text"] for event in final] == ["What is the weather in Berlin"]
    assert final[0]["message_id"] == pending["message_id"]
    assert checks == ["What is the weather in Berlin"] and len(runtime.issued) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_resumed_speech_revokes_uncertain_silence_fallback(runtime, monkeypatch):
    async def complete(text, _socket):
        return "uncertain" if text == "Book me a" else "complete"

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "UNCERTAIN_SILENCE_FALLBACK_SECONDS", 0.3)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Book me a")
    provider.push("turn.end")
    await socket.event("transcript.pending")
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="table for two.")
    await asyncio.sleep(0.5)
    assert not socket.finals() and not runtime.issued
    provider.push("turn.end")
    final = await socket.until(lambda _: socket.finals())
    assert [event["text"] for event in final] == ["Book me a table for two."]
    assert len(runtime.issued) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_unavailable_decision_fails_open_and_submits_without_retry(runtime, monkeypatch, caplog):
    checks = []

    async def complete(text, _socket):
        checks.append(text)
        return "unavailable"

    monkeypatch.setattr(route, "_complete", complete)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Tell me a joke")
    provider.push("turn.end")
    final = await socket.until(lambda _: socket.finals())
    assert checks == ["Tell me a joke"]
    assert [event["text"] for event in final] == ["Tell me a joke"] and len(runtime.issued) == 1
    assert "VOICE_COMPLETION_CHECK fail_open" in caplog.text
    assert not [event for event in socket.sent if event["type"] == "transcript.pending"]


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_incomplete_thinking_pause_is_held_beyond_the_silence_fallback(runtime, monkeypatch):
    async def complete(text, _socket):
        return "incomplete"

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "UNCERTAIN_SILENCE_FALLBACK_SECONDS", 0.1)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Let me think")
    provider.push("turn.end")
    assert (await socket.event("transcript.pending"))["reason"] == "incomplete"
    await asyncio.sleep(0.5)
    assert not socket.finals() and not runtime.issued


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_late_delta_does_not_cancel_in_flight_check_and_immaterial_change_is_not_rechecked(runtime, monkeypatch):
    checks, cancelled = [], []

    async def complete(text, _socket):
        checks.append(text)
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            cancelled.append(text)
            raise
        return "complete"

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "STREAMING_DELAY_MS", 300)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="How do I make ramen")
    provider.push("turn.end")
    await asyncio.sleep(0.05)
    provider.push("transcription.text.delta", text="?")
    final = await socket.until(lambda _: socket.finals())
    assert checks == ["How do I make ramen"] and not cancelled
    assert [event["text"] for event in final] == ["How do I make ramen?"]


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_material_late_delta_rechecks_within_deadline_and_sends_after_it(runtime, monkeypatch):
    checks = []

    async def complete(text, _socket, timeout=route.COMPLETION_CHECK_DEADLINE_SECONDS):
        checks.append((text, timeout < route.COMPLETION_CHECK_DEADLINE_SECONDS))
        await asyncio.sleep(0.1)
        return "incomplete" if len(checks) == 1 else "complete"

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "STREAMING_DELAY_MS", 200)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Book a table")
    provider.push("turn.end")
    await asyncio.sleep(0.03)
    provider.push("transcription.text.delta", text=" for two people")
    final = await socket.until(lambda _: socket.finals())
    # One re-check on the changed words, bounded by the remaining budget.
    assert checks == [("Book a table", False), ("Book a table for two people", True)]
    assert [event["text"] for event in final] == ["Book a table for two people"]


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_late_material_delta_after_deadline_budget_is_sent_not_rechecked(runtime, monkeypatch, caplog):
    checks = []

    async def complete(text, _socket, timeout=0.0):
        checks.append(text)
        await asyncio.sleep(0.2)
        return "incomplete"

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "COMPLETION_CHECK_DEADLINE_SECONDS", 0.2)
    monkeypatch.setattr(route, "STREAMING_DELAY_MS", 100)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Book a table")
    provider.push("turn.end")
    await asyncio.sleep(0.05)
    provider.push("transcription.text.delta", text=" for two people")
    final = await socket.until(lambda _: socket.finals())
    assert checks == ["Book a table"]
    assert [event["text"] for event in final] == ["Book a table for two people"]
    assert "fail_open" in caplog.text


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_cleanup_candidate_write_runs_off_the_transcript_send_path(runtime, monkeypatch):
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    release, modes = asyncio.Event(), []

    async def execute(_self, operation, data):
        modes.append(data["mode"])
        if data["mode"] == "disqualify":
            await release.wait()
        return {"eligible": True}

    async def complete(text, _socket):
        return "complete"

    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    monkeypatch.setattr(route, "_complete", complete)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Tell me a joke")
    provider.push("turn.end")
    # The final transcript is sent while the Directus write is still pending.
    await asyncio.wait_for(socket.until(lambda _: socket.finals()), 2)
    assert "disqualify" in modes
    release.set()


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_completion_check_starts_at_endpoint_before_trailing_delay(runtime, monkeypatch):
    started = asyncio.Event()

    async def complete(text, _socket):
        started.set()
        return "complete"

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "STREAMING_DELAY_MS", 2000)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="How do I make ramen?")
    provider.push("turn.end")
    # The decision overlaps trailing-delta collection; admission still waits.
    await asyncio.wait_for(started.wait(), 1)
    assert not socket.finals() and not runtime.issued


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_resumed_speech_rejects_even_a_late_success_from_cancelled_check(runtime, monkeypatch):
    checking, release, stale_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    checks = []

    async def complete(text, _socket):
        checks.append(text)
        if len(checks) == 1:
            checking.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            stale_done.set()
            return "complete"
        return "complete"

    monkeypatch.setattr(route, "_complete", complete)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Book the expensive option")
    provider.push("turn.end")
    await asyncio.wait_for(checking.wait(), 2)
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="actually do not book it.")
    await socket.until(lambda events: any("actually" in event.get("text", "") for event in events))
    release.set()
    await asyncio.wait_for(stale_done.wait(), 2)
    assert not socket.finals() and not runtime.issued
    provider.push("turn.end")
    await socket.until(lambda _: socket.finals())
    assert checks == ["Book the expensive option", "Book the expensive option actually do not book it."]
    assert len(socket.finals()) == len(runtime.issued) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
@pytest.mark.parametrize("resume_event", ["turn.resume", "turn.start"])
async def test_cancelled_check_is_retried_after_resume_without_new_transcript_words(runtime, monkeypatch, resume_event):
    checking = asyncio.Event()
    checks = []

    async def complete(text, _socket):
        checks.append(text)
        if len(checks) == 1:
            checking.set()
            await asyncio.Future()
        return "complete"

    monkeypatch.setattr(route, "_complete", complete)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="How do I make ramen?")
    provider.push("turn.end")
    await asyncio.wait_for(checking.wait(), 2)
    provider.push(resume_event)
    provider.push("turn.end")
    await socket.until(lambda _: socket.finals())
    assert checks == ["How do I make ramen?", "How do I make ramen?"]
    assert len(socket.finals()) == len(runtime.issued) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_hangup_cancels_pending_completion_without_chat_submission(runtime, monkeypatch):
    checking, cancelled = asyncio.Event(), asyncio.Event()

    async def complete(_text, _socket):
        checking.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setattr(route, "_complete", complete)
    socket, provider, task = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="I am wondering whether")
    provider.push("turn.end")
    await asyncio.wait_for(checking.wait(), 2)
    socket.push({"type": "hangup"})
    await asyncio.wait_for(task, 2)
    assert cancelled.is_set() and not socket.finals() and not runtime.issued


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
async def test_each_confirmed_request_keeps_its_own_identity(runtime):
    socket, provider, _ = await runtime.start()
    for text in ("First request", "Second request"):
        provider.push("turn.start")
        provider.push("transcription.text.delta", text=text)
        provider.push("turn.end")
        await socket.until(lambda _: len(socket.finals()) == len(runtime.completion_texts) and any(event["text"] == text for event in socket.finals()))
    assert [event["text"] for event in socket.finals()] == ["First request", "Second request"]
    assert socket.finals()[0]["message_id"] < socket.finals()[1]["message_id"]


def assistant(socket, text="Here is a long explanation.", identity="canonical-assistant"):
    socket.push({"type": "assistant_state", "speaking": True, "text": text, "assistant_message_id": identity})


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
async def test_listener_acknowledgement_preserves_playback_and_creates_no_request(runtime, monkeypatch):
    async def backchannel(*args):
        return "backchannel"
    monkeypatch.setattr(route, "_classify", backchannel)
    socket, provider, _ = await runtime.start()
    assistant(socket)
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="hmm, okay")
    provider.push("turn.end")
    assert (await socket.event("transcript.discarded"))["reason"] == "backchannel"
    assert not socket.finals() and not runtime.issued and not any(event["type"] == "audio.interrupted" for event in socket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
async def test_supported_echo_of_current_playback_neither_cancels_nor_enters_processing(runtime, monkeypatch):
    async def echo(*args):
        assert args[-1] is True
        return "echo"

    monkeypatch.setattr(route, "_classify", echo)
    socket, provider, _ = await runtime.start()
    assistant(socket, text="Here is the complete explanation of your question.")
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Here is the complete explanation of your question.")
    provider.push("turn.end")
    assert (await socket.event("transcript.discarded"))["reason"] == "echo"
    assert not socket.finals() and not runtime.issued and not runtime.completion_texts
    assert not any(event["type"] == "audio.interrupted" for event in socket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
async def test_short_recapture_of_current_playback_is_discarded_without_an_echo_verdict(runtime, monkeypatch):
    # EYHC5: three spoken assistant words came back through the microphone and
    # became a user message, because echo needed a model verdict over 5+ words.
    async def uncertain(*args):
        return "uncertain"

    monkeypatch.setattr(route, "_classify", uncertain)
    socket, provider, _ = await runtime.start()
    assistant(socket, text="Tell me what you would like to watch, and I will start the chat for you.")
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Start the chat.")
    provider.push("turn.end")
    assert (await socket.event("transcript.discarded"))["reason"] == "echo"
    assert not socket.finals() and not runtime.issued and not runtime.completion_texts
    assert not any(event["type"] == "audio.interrupted" for event in socket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
async def test_echo_of_a_playing_prerecorded_clip_is_discarded(runtime, monkeypatch):
    # EYHC5 as reported: the "Starting your chat…" clip played before the answer
    # had any text, and its echo was saved as the caller's message.
    async def uncertain(*args):
        return "uncertain"

    monkeypatch.setattr(route, "_classify", uncertain)
    socket, provider, _ = await runtime.start()
    socket.push({"type": "assistant_state", "speaking": True, "text": "", "assistant_message_id": "canonical-assistant",
                 "clip_audio_url": "/audio/assistant-acknowledgements/system/en-US/chat_start-1.mp3"})
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Starting your chat.")
    provider.push("turn.end")
    assert (await socket.event("transcript.discarded"))["reason"] == "echo"
    assert not socket.finals() and not runtime.issued and not runtime.completion_texts


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
@pytest.mark.parametrize("case", ["deliberate", "after_playback"])
async def test_repeated_assistant_words_stay_a_turn_when_deliberate_or_after_playback(runtime, monkeypatch, case):
    async def verdict(*args):
        return "interrupt" if case == "deliberate" else "uncertain"

    monkeypatch.setattr(route, "_classify", verdict)
    socket, provider, _ = await runtime.start()
    spoken = "Tell me what you would like to watch, and I will start the chat for you."
    assistant(socket, text=spoken)
    await socket.until(lambda events: any(event.get("processing") for event in events))
    if case == "after_playback":
        # Playback ended before the caller spoke: the same words are their turn.
        socket.push({"type": "assistant_state", "speaking": False, "text": spoken,
                     "assistant_message_id": "canonical-assistant"})
        await socket.until(lambda events: [event["processing"] for event in events
                                             if event["type"] == "billing_activity"][-1] is False)
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Start the chat.")
    provider.push("turn.end")
    await socket.until(lambda _: socket.finals())
    assert socket.finals()[0]["text"] == "Start the chat."
    assert not any(event.get("reason") == "echo" for event in socket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.chat.assistant-identity
@pytest.mark.parametrize("replacement", ["finished", "new-answer"])
async def test_late_echo_verdict_cannot_discard_speech_after_its_playback_context_changes(runtime, monkeypatch, replacement):
    gate = asyncio.Event()

    async def echo(*args):
        await gate.wait()
        return "echo"

    monkeypatch.setattr(route, "_classify", echo)
    socket, provider, _ = await runtime.start()
    assistant(socket, identity="old-answer")
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Please explain that last part again")
    await socket.event("transcript")
    socket.push({"type": "assistant_state", "speaking": replacement != "finished", "text": "A different context.",
                 "assistant_message_id": "old-answer" if replacement == "finished" else replacement})
    socket.push({"type": "audio_stream_end"})
    await socket.until(lambda events: any(event.get("input_listening") is False for event in events))
    provider.push("turn.end")
    gate.set()
    await socket.until(lambda _: socket.finals())
    assert not any(event.get("reason") == "echo" for event in socket.sent)
    assert socket.finals()[0]["text"] == "Please explain that last part again"


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.audio.complete-turn-admission
async def test_classifier_does_not_block_microphone_and_uncertain_substantive_turn_survives(runtime, monkeypatch):
    gate = asyncio.Event()
    async def slow(*args):
        await gate.wait()
        return "uncertain"
    monkeypatch.setattr(route, "_classify", slow)
    socket, provider, _ = await runtime.start()
    assistant(socket)
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Show me Paris instead")
    await socket.event("transcript")
    chunk = base64.b64encode(b"\0\0" * 160).decode()
    socket.push({"type": "mic_audio", "data": chunk})
    await socket.until(lambda _: len(provider.audio) == 1)
    provider.push("turn.end")
    gate.set()
    await socket.until(lambda _: socket.finals())
    assert socket.finals()[0]["text"] == "Show me Paris instead"
    assert len([event for event in socket.sent if event["type"] == "audio.interrupted"]) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
async def test_explicit_stop_interrupts_before_endpoint_without_inference_or_main_request(runtime, monkeypatch):
    async def forbidden(*args):
        raise AssertionError("Explicit stop must bypass inference")
    monkeypatch.setattr(route, "_classify", forbidden)
    socket, provider, _ = await runtime.start()
    assistant(socket)
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Stop.")
    interrupted = await socket.event("audio.interrupted")
    assert interrupted["assistant_message_id"] == "canonical-assistant" and not socket.finals()
    provider.push("turn.end")
    assert (await socket.event("transcript.discarded"))["reason"] == "stop"
    assert not socket.finals()


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.audio.complete-turn-admission
async def test_stop_followed_by_correction_keeps_complete_request(runtime, monkeypatch):
    async def interrupt(*args):
        return "interrupt"
    monkeypatch.setattr(route, "_classify", interrupt)
    socket, provider, _ = await runtime.start()
    assistant(socket)
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Stop")
    await socket.event("audio.interrupted")
    provider.push("turn.end")
    provider.push("transcription.text.delta", text=", use Paris instead")
    await socket.until(lambda _: socket.finals())
    assert socket.finals()[0]["text"] == "Stop, use Paris instead"
    assert len([event for event in socket.sent if event["type"] == "audio.interrupted"]) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
async def test_yes_answer_to_assistant_question_is_not_discarded_as_backchannel(runtime, monkeypatch):
    async def interrupt(*args):
        return "interrupt"
    monkeypatch.setattr(route, "_classify", interrupt)
    socket, provider, _ = await runtime.start()
    assistant(socket, text="Should I find hotels?")
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Yes")
    provider.push("turn.end")
    await socket.until(lambda _: socket.finals())
    assert socket.finals()[0]["text"] == "Yes"


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.chat.typed-input
async def test_typed_request_accepted_once_and_identical_retry_does_not_repeat_final(runtime):
    socket, provider, _ = await runtime.start()
    identity, _ = route._ordered_message_id()
    event = {"type": "text_input", "message_id": identity, "text": "Find ramen", "created_at": int(time.time())}
    socket.push(event)
    accepted = await socket.event("text_input.accepted")
    assert accepted["message_id"] == identity and len(socket.finals()) == 1
    socket.push(event)
    await socket.until(lambda events: len([event for event in events if event["type"] == "text_input.accepted"]) == 2)
    assert len(socket.finals()) == 1 and not provider.audio
    socket.push({**event, "text": "Different"})
    assert (await socket.event("text_input_rejected"))["code"] == "duplicate_message_id"


# contract-test: supporting surface=rest_api assertions=video-call.chat.pasted-text-not-read-aloud
async def test_pasted_text_input_marks_only_that_turn_and_still_interrupts(runtime):
    from backend.shared.python_utils.voice_call_pasted import is_pasted

    socket, _, _ = await runtime.start()
    cache = socket.app.state.cache_service
    pasted_id, _ = route._ordered_message_id()
    typed_id, _ = route._ordered_message_id()
    now = int(time.time())
    socket.push({"type": "text_input", "message_id": pasted_id, "text": "Long pasted body", "created_at": now, "pasted": True})
    await socket.event("text_input.accepted")
    socket.push({"type": "text_input", "message_id": typed_id, "text": "Typed question", "created_at": now})
    await socket.until(lambda events: len([e for e in events if e["type"] == "text_input.accepted"]) == 2)
    call_id = next(e["call_id"] for e in socket.sent if e.get("type") == "text_input.accepted")
    assert await is_pasted(cache, call_id, pasted_id)
    assert not await is_pasted(cache, call_id, typed_id)
    assert len(socket.finals()) == 2


# contract-test: supporting surface=gui.web assertions=video-call.chat.stt-special-terms
async def test_special_terms_reach_provider_as_hints_and_invalid_lists_are_rejected(runtime):
    socket, provider, task = await runtime.start()
    socket.push({"type": "stt_terms", "terms": ["Orbitex", " orbitex ", "Kessler  Lab"]})
    accepted = await socket.event("stt_terms.accepted")
    assert accepted["count"] == 2 and provider.terms == ["Orbitex", "Kessler Lab"]
    socket.push({"type": "stt_terms", "terms": ["x" * 65]})
    assert (await socket.event("stt_terms_rejected"))["code"] == "invalid_terms"
    assert provider.terms == ["Orbitex", "Kessler Lab"] and not task.done()


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.chat.launch-and-provider
async def test_mute_keeps_provider_open_and_resumed_pcm_in_order(runtime):
    socket, provider, task = await runtime.start()
    chunk = base64.b64encode(b"\0\0" * 80).decode()
    socket.push({"type": "mic_audio", "data": chunk})
    socket.push({"type": "audio_stream_end"})
    socket.push({"type": "mic_audio", "data": chunk})
    await socket.until(lambda _: len(provider.audio) == 2)
    assert provider.ends == 1 and not provider.closed and not task.done()
    socket.push(WebSocketDisconnect())
    await task
    assert provider.closed and len(runtime.finalized) == 1


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.audio.complete-turn-admission,video-call.usage.provider-metering
async def test_consecutive_turns_deliver_every_word_while_a_minute_charge_is_slow(runtime, monkeypatch):
    """Turn 2 began as the call's next minute was charged: the slow charge froze
    the loop, so the live transcript stalled and the turn came out cut off."""
    release, charges = asyncio.Event(), []
    async def credits(*args):
        return 10_000
    class SlowBilling:
        async def charge_user_credits(self, **kwargs):
            charges.append(kwargs["idempotency_key"])
            await release.wait()
            return {"charged_credits": kwargs["credits_to_deduct"]}
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(route, "_authoritative_credits", credits)
    monkeypatch.setattr(route, "_billing", lambda _: SlowBilling())
    socket, provider, task = await runtime.start(startup_ms=1000)
    frames = [base64.b64encode(bytes([index]) * 320).decode() for index in range(1, 7)]
    turns = [["So", " I created", " OpenMates,"], ["An open source", " AI agent", " for everyone."],
             ["It runs", " on my own", " server", " in Germany."]]
    socket.push({"type": "mic_audio", "data": frames[0]})
    await socket.until(lambda _: charges)
    # The charge for the started minute is still pending: later frames and every
    # turn's words must keep arriving instead of waiting behind it.
    for frame in frames[1:]:
        socket.push({"type": "mic_audio", "data": frame})
    for number, words in enumerate(turns, start=1):
        provider.push("turn.start", time_s=number)
        for word in words:
            provider.push("transcription.text.delta", text=word)
            await socket.until(lambda events, word=word: any(
                event["type"] == "transcript" and event["text"].endswith(word.strip()) for event in events))
        provider.push("turn.end", time_s=number + 0.5, end_reason="threshold")
        await socket.until(lambda _, number=number: len(socket.finals()) == number)
    assert not release.is_set() and provider.audio == frames[:1] and not task.done()
    release.set()
    await socket.until(lambda _: provider.audio == frames)
    assert [event["text"] for event in socket.finals()] == ["".join(words) for words in turns]
    assert len({event["message_id"] for event in socket.finals()}) == 3
    socket.push({"type": "hangup"})
    await task
    assert len(set(charges)) == 1


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
async def test_startup_audio_allowance_is_call_wide_and_end_cannot_replenish(runtime):
    socket, provider, task = await runtime.start(startup_ms=1000)
    encoded = base64.b64encode(bytes(32000 * 3)).decode()
    socket.push({"type": "mic_audio", "data": encoded})
    socket.push({"type": "audio_stream_end"})
    socket.push({"type": "mic_audio", "data": encoded})
    await task
    assert len(provider.audio) == 1 and provider.ends == 1
    assert (await socket.event("error"))["stage"] == "active"


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.video.input-and-output
async def test_screen_source_freezes_before_final_and_stays_out_of_stt(runtime):
    socket, provider, _ = await runtime.start()
    ready = await socket.event("ready")
    encoded = BytesIO()
    Image.new("RGB", (16, 16), "red").save(encoded, format="JPEG")
    socket.push({"type": "camera_state", "call_id": ready["call_id"], "enabled": True})
    socket.push({"type": "camera_frame", "call_id": ready["call_id"], "frame_id": "screen-1", "source": "screen",
                 "data": base64.b64encode(encoded.getvalue()).decode(), "captured_at": int(time.time() * 1000)})
    await socket.event("camera_state")
    # Client events must be consumed before the transcript boundary.
    socket.push({"type": "text_input", "message_id": route._ordered_message_id()[0], "text": "Explain this screen", "created_at": int(time.time())})
    source = await socket.event("voice_source_frame")
    await socket.until(lambda _: socket.finals())
    assert source["source"] == "screen"
    assert socket.sent.index(source) < socket.sent.index(socket.finals()[0])
    assert not provider.audio


def request(origin="https://app.example.org"):
    app = SimpleNamespace(state=SimpleNamespace(allowed_origins=["https://app.example.org"]))
    headers = [(b"origin", origin.encode())] if origin else []
    return Request({"type": "http", "method": "POST", "path": "/v1/settings/voice-processing-ack", "headers": headers, "app": app})


# contract-test: supporting surface=gui.web assertions=video-call.privacy
async def test_consent_v3_ignores_older_provider_approvals_and_requires_durable_confirmation(monkeypatch):
    monkeypatch.setattr(route, "isolated_voice_fixture_enabled", lambda: False)
    profile, cache, user = Profile(), Cache(), SimpleNamespace(id="owner")
    profile.fields = {"voice_google_processing_ack_v1_at": 1_800_000_000, "voice_processing_ack_v2_at": 1_800_000_000}
    assert (await route.get_processing_ack(request(), user, profile, cache))["acknowledged"] is False
    for body in [{"version": 1}, {"version": 2}, {"version": True}]:
        with pytest.raises(HTTPException) as error:
            await route.record_processing_ack(request(), body, user, profile, cache)
        assert error.value.status_code == 422
    accepted = await route.record_processing_ack(request(), {"version": 3}, user, profile, cache)
    assert accepted["version"] == 3 and accepted["acknowledged"]
    assert await route.get_processing_ack(request(), user, profile, cache) == accepted
    assert await route.record_processing_ack(request(), {"version": 3}, user, profile, cache) == accepted
    assert len(profile.writes) == 1
    assert profile.fields["voice_google_processing_ack_v1_at"] == 1_800_000_000
    assert profile.fields["voice_processing_ack_v2_at"] == 1_800_000_000
    assert set(profile.writes[0]) == {"voice_processing_ack_v3_at"}
    with pytest.raises(HTTPException) as error:
        await route.record_processing_ack(request("https://foreign.example"), {"version": 3}, user, profile, cache)
    assert error.value.status_code == 403
    profile.fields.pop(route.PROCESSING_ACK_FIELD)
    profile.write_success = False
    with pytest.raises(HTTPException) as error:
        await route.record_processing_ack(request(), {"version": 3}, user, profile, cache)
    assert error.value.status_code == 503


# contract-test: supporting surface=gui.web assertions=video-call.privacy
async def test_old_mistral_only_ack_denies_call_before_capture_or_provider(runtime, monkeypatch):
    profile = Profile()
    profile.fields = {"voice_processing_ack_v2_at": 1_800_000_000}
    original_read = route._processing_ack_at

    async def old_profile(*_args):
        return await original_read(profile, "owner")

    monkeypatch.setattr(route, "_effective_processing_ack_at", old_profile)
    socket, provider, task = await runtime.start(wait_ready=False)
    await task
    assert not socket.accepted and not provider.opened and not provider.audio
    assert socket.close_options["reason"] == "voice_ack_required"
    assert not runtime.issued and not runtime.finalized
    assert not profile.writes


# contract-test: supporting surface=gui.web assertions=video-call.privacy
@pytest.mark.parametrize("unavailable", [False, True])
async def test_unacknowledged_or_unavailable_profile_denies_socket_before_accept(runtime, monkeypatch, unavailable):
    async def consent(*args):
        if unavailable:
            raise RuntimeError("Profile unavailable")
        return None
    monkeypatch.setattr(route, "_effective_processing_ack_at", consent)
    socket, provider, task = await runtime.start(wait_ready=False)
    await task
    assert not socket.accepted and not provider.opened
    assert socket.close_options["reason"] == ("voice_ack_unavailable" if unavailable else "voice_ack_required")


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.privacy
async def test_isolated_fixture_needs_all_four_guards_and_has_no_assistant_response(monkeypatch):
    guards = {"CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_AI_FIXTURES": "1", "MOCK_EXTERNAL_APIS": "true"}
    for key, value in guards.items():
        monkeypatch.setenv(key, value)
    assert isolated_voice_fixture_enabled()
    fixture = IsolatedVoxtralVoiceFixture()
    await fixture.open()
    await fixture.send_audio(base64.b64encode(bytes(3200)).decode())
    assert fixture._events.empty()
    await fixture.send_audio(base64.b64encode(b"\x00\x01" * 1600).decode())
    assert [(await fixture.receive())["type"] for _ in range(4)] == ["turn.start", "transcription.text.delta", "turn.eager_end", "turn.end"]
    assert not fixture.capabilities.audio_output and not fixture.capabilities.tools
    for key, value in guards.items():
        monkeypatch.delenv(key)
        assert not isolated_voice_fixture_enabled()
        with pytest.raises(RuntimeError):
            IsolatedVoxtralVoiceFixture()
        monkeypatch.setenv(key, value)


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
async def test_provider_accepted_audio_is_settled_after_lost_charge_receipt_and_disconnect(runtime, monkeypatch):
    calls = []
    async def credits(*args):
        return route.REALTIME_CREDITS_PER_MINUTE
    class Billing:
        async def charge_user_credits(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("Receipt connection lost")
            return {"charged_credits": kwargs["credits_to_deduct"]}
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(route, "_authoritative_credits", credits)
    monkeypatch.setattr(route, "_billing", lambda _: Billing())
    socket, provider, task = await runtime.start()
    socket.push({"type": "mic_audio", "data": base64.b64encode(bytes(3200)).decode()})
    await task
    assert len(provider.audio) == 1 and provider.closed
    assert len(calls) == 2 and calls[0]["idempotency_key"] == calls[1]["idempotency_key"]
    assert calls[1]["usage_details"]["duration_seconds"] == 0.1
    assert calls[1]["credits_to_deduct"] == route.REALTIME_CREDITS_PER_MINUTE
    assert len(runtime.finalized) == 1


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
async def test_unaffordable_pcm_never_reaches_provider_or_billing(runtime, monkeypatch):
    credits_reads = 0
    async def credits(*args):
        nonlocal credits_reads
        credits_reads += 1
        return route.REALTIME_CREDITS_PER_MINUTE if credits_reads == 1 else 0
    def forbidden_billing(*args):
        raise AssertionError("Unaccepted audio is not billable")
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(route, "_authoritative_credits", credits)
    monkeypatch.setattr(route, "_billing", forbidden_billing)
    socket, provider, task = await runtime.start(startup_ms=1000)
    socket.push({"type": "mic_audio", "data": base64.b64encode(bytes(3200)).decode()})
    await task
    assert not provider.audio
    assert (await socket.event("error"))["stage"] == "active"


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.privacy
async def test_lease_loss_stops_provider_and_finalizes_registry(runtime, monkeypatch):
    async def lose_lease(*args):
        raise RuntimeError("Lease revoked")
    monkeypatch.setattr(route, "_renew_lock", lose_lease)
    socket, provider, task = await runtime.start()
    await asyncio.wait_for(task, 2)
    assert provider.closed and len(runtime.finalized) == 1
    assert (await socket.event("error"))["stage"] == "active"


# contract-test: supporting surface=gui.web assertions=video-call.privacy
async def test_absent_auth_never_accepts_or_reads_profile():
    socket = Socket()
    await route.voice_call(socket, None)
    assert not socket.accepted and not socket.sent


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.chat.assistant-identity
async def test_late_intent_result_cannot_interrupt_newer_canonical_answer(runtime, monkeypatch):
    gate = asyncio.Event()
    async def slow(*args):
        await gate.wait()
        return "interrupt"
    monkeypatch.setattr(route, "_classify", slow)
    socket, provider, _ = await runtime.start()
    assistant(socket, identity="old-answer")
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Please explain more")
    await socket.event("transcript")
    assistant(socket, identity="new-answer")
    socket.push({"type": "audio_stream_end"})
    await socket.until(lambda events: any(event.get("input_listening") is False for event in events))
    provider.push("turn.end")
    gate.set()
    await socket.until(lambda _: socket.finals())
    # The first words legitimately took the floor from the answer playing then;
    # the late verdict must never reach the newer answer.
    interrupted = [event for event in socket.sent if event["type"] == "audio.interrupted"]
    assert [event["assistant_message_id"] for event in interrupted] == ["old-answer"]


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
async def test_first_words_interrupt_assistant_before_endpoint_and_resumed_speech_does_not_repeat(runtime, monkeypatch):
    async def never(*args):
        await asyncio.Event().wait()
    monkeypatch.setattr(route, "_classify", never)
    socket, provider, _ = await runtime.start()
    assistant(socket, text="Here is a long explanation of the answer.")
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Actually wait")
    interrupted = await socket.event("audio.interrupted")
    assert interrupted["assistant_message_id"] == "canonical-assistant" and not socket.finals()
    provider.push("transcription.text.delta", text=" I meant Paris")
    await socket.until(lambda events: any(event.get("text") == "Actually wait I meant Paris" for event in events))
    assert len([event for event in socket.sent if event["type"] == "audio.interrupted"]) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption
async def test_early_reasoning_stop_targets_known_task_before_assistant_message_exists(runtime):
    socket, provider, _ = await runtime.start()
    socket.push({"type": "assistant_state", "speaking": False, "generating": True,
                 "assistant_message_id": None, "assistant_task_id": "canonical-task", "text": ""})
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Stop")
    event = await socket.event("audio.interrupted")
    assert event["assistant_message_id"] is None and event["assistant_task_id"] == "canonical-task"
    assert not socket.finals() and not runtime.issued
    provider.push("turn.end")
    assert (await socket.event("transcript.discarded"))["reason"] == "stop"


# contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.chat.assistant-identity
async def test_late_intent_cannot_cancel_replaced_task_when_both_message_ids_are_unknown(runtime, monkeypatch):
    gate = asyncio.Event()
    async def slow(*args):
        await gate.wait()
        return "interrupt"
    monkeypatch.setattr(route, "_classify", slow)
    socket, provider, _ = await runtime.start()
    state = {"type": "assistant_state", "speaking": False, "generating": True,
             "assistant_message_id": None, "assistant_task_id": "old-task", "text": ""}
    socket.push(state)
    await socket.until(lambda events: any(event.get("processing") for event in events))
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Show Berlin instead")
    await socket.event("transcript")
    socket.push({**state, "assistant_task_id": "new-task"})
    socket.push({"type": "audio_stream_end"})
    await socket.until(lambda events: any(event.get("input_listening") is False for event in events))
    provider.push("turn.end")
    gate.set()
    await socket.until(lambda _: socket.finals())
    # Only the task running when the first words arrived may be cancelled.
    interrupted = [event for event in socket.sent if event["type"] == "audio.interrupted"]
    assert [event["assistant_task_id"] for event in interrupted] == ["old-task"]


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.provider.boundary,video-call.privacy
async def test_actual_context_free_start_reaches_ready_without_disclosing_chat_content(runtime):
    chat_id = str(uuid.uuid4())
    wire = {"type": "start", "speech_output_transport": route.SPEECH_OUTPUT_TRANSPORT, "chat_id": chat_id, "startup_audio_allowance_ms": 1000}
    assert route._start(json.dumps(wire)) == (chat_id, "", [], 1000)
    # runtime.start omits context by default, exactly as the real clients do.
    socket, provider, _ = await runtime.start(startup_ms=1000)
    ready = await socket.event("ready")
    assert provider.opened and ready["provider"] == "mistral"
    assert ready["input_sample_rate"] == 16000


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.chat.launch-and-provider
@pytest.mark.parametrize("context", [None, [], "private context", 7, False])
def test_malformed_provided_context_remains_rejected(context):
    with pytest.raises(ValueError, match="Invalid call context"):
        route._start(json.dumps({"type": "start", "speech_output_transport": route.SPEECH_OUTPUT_TRANSPORT, "chat_id": str(uuid.uuid4()), "context": context}))


@pytest.fixture(autouse=True)
def _cleanup_authority_for_existing_flow_fixtures(monkeypatch):
    """Existing fixtures model a successful separate cleanup exclusion RPC.

    Atomic eligibility/failure behavior is exercised by cleanup admission and
    Directus transaction tests; these cases retain their original boundaries.
    """
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    execute = ChatRecoveryService.execute

    async def with_cleanup_authority(self, operation, data):
        if operation == "update_call_cleanup_candidate":
            assert data["mode"] in {"disqualify", "start", "finish"}
            return {"eligible": False, "disqualified": True}
        return await execute(self, operation, data)

    monkeypatch.setattr(ChatRecoveryService, "execute", with_cleanup_authority)


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
@pytest.mark.parametrize("failure", ["provider_open", "ready_transport"])
async def test_cleanup_finish_proves_no_ready_only_before_any_ready_send_attempt(runtime, monkeypatch, failure):
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    operations = []

    async def execute(_self, operation, data):
        assert operation == "update_call_cleanup_candidate"
        operations.append(dict(data))
        return {"eligible": True}

    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    if failure == "provider_open":
        async def failed_open(_self):
            raise RuntimeError("provider unavailable before Ready")
        monkeypatch.setattr(Provider, "open", failed_open)
    else:
        original_send = Socket.send_json
        async def failed_ready_send(self, event):
            if event["type"] == "ready":
                # The frame may have been exposed even though the await fails.
                self.sent.append(event)
                self.changed.set()
                raise WebSocketDisconnect()
            await original_send(self, event)
        monkeypatch.setattr(Socket, "send_json", failed_ready_send)

    socket, _provider, task = await runtime.start(wait_ready=False)
    await asyncio.wait_for(task, 2)
    assert [item["mode"] for item in operations] == ["start", "finish"]
    assert operations[-1]["ready_exposed"] is (failure == "ready_transport")
    assert any(event["type"] == "ready" for event in socket.sent) is (failure == "ready_transport")


# contract-test: direct surface=rest_api assertions=video-call.chat.pasted-text-not-read-aloud
@pytest.mark.asyncio
async def test_pasted_call_turn_marker_drives_the_no_read_aloud_instruction():
    from backend.shared.python_utils.voice_call_pasted import (
        PASTED_TEXT_INSTRUCTION, is_pasted, mark_pasted, pasted_text_context)

    members: dict[str, set[str]] = {}

    class FakeRedis:
        async def scard(self, key): return len(members.get(key, ()))
        async def sadd(self, key, value): members.setdefault(key, set()).add(value)
        async def expire(self, key, ttl): return True
        async def sismember(self, key, value): return value in members.get(key, ())

    class FakeCache:
        @property
        async def client(self): return FakeRedis()

    cache = FakeCache()
    await mark_pasted(cache, "call-1", "turn-pasted")
    assert await is_pasted(cache, "call-1", "turn-pasted")
    assert not await is_pasted(cache, "call-1", "turn-typed")
    assert not await is_pasted(cache, "call-2", "turn-pasted")
    assert not await is_pasted(cache, None, "turn-pasted")
    assert pasted_text_context(True) == PASTED_TEXT_INSTRUCTION
    assert "Do not read the pasted text aloud" in PASTED_TEXT_INSTRUCTION
    assert pasted_text_context(False) == ""


# contract-test: supporting surface=gui.web assertions=video-call.audio.pause-verdict
async def test_spoken_wait_intent_enters_waiting_and_starts_no_turn(runtime, monkeypatch):
    from backend.shared.python_utils.voice_pause_decision import PauseDecision

    async def complete(text, _socket):
        return PauseDecision("wait", "wait", None)

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "UNCERTAIN_SILENCE_FALLBACK_SECONDS", 0.1)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Hold on a second")
    provider.push("turn.end")
    waiting = await socket.event("waiting")
    assert waiting["active"] is True and waiting["line"] == "waiting_start"
    discarded = await socket.event("transcript.discarded")
    assert discarded["reason"] == "waiting"
    await asyncio.sleep(0.4)
    assert not socket.finals() and not runtime.issued


# contract-test: supporting surface=gui.web assertions=video-call.audio.pause-verdict
async def test_wait_verdict_without_intent_holds_the_turn_open(runtime, monkeypatch):
    from backend.shared.python_utils.voice_pause_decision import PauseDecision

    async def complete(text, _socket):
        return PauseDecision("wait", "none", None)

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "UNCERTAIN_SILENCE_FALLBACK_SECONDS", 0.1)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="How do I make")
    provider.push("turn.end")
    pending = await socket.event("transcript.pending")
    assert pending["reason"] == "incomplete"
    await asyncio.sleep(0.4)
    assert not socket.finals() and not runtime.issued
    assert not [event for event in socket.sent if event["type"] == "waiting"]


# contract-test: supporting surface=gui.web assertions=video-call.audio.pause-verdict
async def test_still_thinking_submits_after_its_short_silence_and_intent_none_sends_no_frame(runtime, monkeypatch):
    from backend.shared.python_utils.voice_pause_decision import PauseDecision

    async def complete(text, _socket):
        return PauseDecision("still_thinking", "none", 2.0)

    monkeypatch.setattr(route, "_complete", complete)
    monkeypatch.setattr(route, "STILL_THINKING_SILENCE_SECONDS", 0.2)
    socket, provider, _ = await runtime.start()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Let me think about")
    provider.push("turn.end")
    pending = await socket.event("transcript.pending")
    assert pending["reason"] == "incomplete"
    final = await socket.until(lambda _: socket.finals())
    assert [event["text"] for event in final] == ["Let me think about"]
    assert not [e for e in socket.sent if e["type"] == "turn.intent"]


def _intent_check(intents):
    async def complete(text, _socket):
        return PauseDecision("finished", intents.get(text, "none"), 0)
    return complete


async def _say(provider, text):
    provider.push("turn.start")
    provider.push("transcription.text.delta", text=text)
    provider.push("turn.end")


# contract-test: supporting surface=rest_api assertions=video-call.waiting.spoken-intent-and-merge
async def test_spoken_wait_holds_speech_resume_merges_one_turn_without_inference(runtime, monkeypatch):
    monkeypatch.setattr(route, "_complete", _intent_check({"Wait a second.": "wait", "I am back.": "resume"}))
    socket, provider, _ = await runtime.start()
    await _say(provider, "Plan a trip to my_city.")
    await socket.until(lambda _: socket.finals())
    runtime.issued.clear()
    socket.sent.clear()
    await _say(provider, "Wait a second.")
    waiting = await socket.event("waiting")
    assert waiting["active"] is True and waiting["line"] == "waiting_start"
    await _say(provider, "With two stops.")
    await socket.until(lambda events: sum(e["type"] == "transcript.discarded" for e in events) >= 2)
    await _say(provider, "I am back.")
    resumed = await socket.until(lambda events: next((e for e in events if e["type"] == "waiting" and not e["active"]), None))
    assert resumed["line"] == "waiting_resume"
    await _say(provider, "By train please.")
    final = await socket.until(lambda _: next(iter(socket.finals()), None))
    assert final["text"] == "Wait a second. With two stops. By train please."
    assert len(runtime.issued) <= 1


# contract-test: supporting surface=rest_api assertions=video-call.waiting.spoken-intent-and-merge
async def test_spoken_repeat_asks_client_replay_and_starts_no_inference(runtime, monkeypatch):
    monkeypatch.setattr(route, "_complete", _intent_check({"Repeat that.": "repeat"}))
    socket, provider, _ = await runtime.start()
    await _say(provider, "Repeat that.")
    replay = await socket.event("repeat_last_answer")
    assert replay["type"] == "repeat_last_answer"
    await socket.event("transcript.discarded")
    assert not socket.finals() and not runtime.issued


# contract-test: supporting surface=rest_api assertions=video-call.waiting.spoken-intent-and-merge
async def test_hold_event_wins_without_any_model_intent(runtime, monkeypatch):
    monkeypatch.setattr(route, "_complete", _intent_check({}))
    socket, provider, ready = await runtime.start()
    ready = await socket.event("ready")
    socket.push({"type": "hold", "call_id": ready["call_id"], "active": True})
    assert (await socket.event("waiting"))["active"] is True
    await _say(provider, "Still thinking about it.")
    await socket.until(lambda events: any(e["type"] == "transcript.discarded" for e in events))
    assert not socket.finals() and not runtime.issued
    socket.push({"type": "hold", "call_id": ready["call_id"], "active": False})
    await socket.until(lambda events: any(e["type"] == "waiting" and not e["active"] for e in events))
