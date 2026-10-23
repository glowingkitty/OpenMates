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


class Cache:
    def __init__(self):
        self.values = {}

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

    def push(self, kind, **kwargs):
        self.events.put_nowait({"type": kind, **kwargs})


@pytest.fixture
async def runtime(monkeypatch):
    sockets, tasks, providers, issued, finalized = [], [], [], [], []

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

    async def start(*, context=None, startup_ms=0, auth=None, wait_ready=True, transport=route.SPEECH_OUTPUT_TRANSPORT):
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
        socket.push(start_event)
        task = asyncio.create_task(route.voice_call(socket, auth or {"user_id": "owner", "session_hash": "session"}))
        tasks.append(task)
        if wait_ready:
            await socket.event("ready")
        return socket, provider, task

    yield SimpleNamespace(start=start, issued=issued, finalized=finalized)
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
@pytest.mark.parametrize("transport", [None, "full_file_v0", False])
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
    assert not provider.opened and (await socket.event("error"))["stage"] == "credits"
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
async def test_resume_cancels_endpoint_and_next_turn_start_closes_prior_complete_turn(runtime):
    socket, provider, _ = await runtime.start()
    for kind, kwargs in [("turn.start", {}), ("transcription.text.delta", {"text": "First"}),
                         ("turn.end", {}), ("turn.resume", {}), ("transcription.text.delta", {"text": " request"})]:
        provider.push(kind, **kwargs)
    await socket.until(lambda events: any(event.get("text") == "First request" for event in events))
    assert not socket.finals()
    provider.push("turn.start")
    provider.push("transcription.text.delta", text="Second request")
    provider.push("turn.end")
    await socket.until(lambda _: len(socket.finals()) == 2)
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
async def test_consent_v2_ignores_google_approval_and_requires_durable_confirmation(monkeypatch):
    monkeypatch.setattr(route, "isolated_voice_fixture_enabled", lambda: False)
    profile, cache, user = Profile(), Cache(), SimpleNamespace(id="owner")
    profile.fields = {"voice_google_processing_ack_v1_at": 1_800_000_000}
    assert (await route.get_processing_ack(request(), user, profile, cache))["acknowledged"] is False
    for body in [{"version": 1}, {"version": True}]:
        with pytest.raises(HTTPException) as error:
            await route.record_processing_ack(request(), body, user, profile, cache)
        assert error.value.status_code == 422
    accepted = await route.record_processing_ack(request(), {"version": 2}, user, profile, cache)
    assert accepted["version"] == 2 and accepted["acknowledged"]
    assert await route.get_processing_ack(request(), user, profile, cache) == accepted
    assert await route.record_processing_ack(request(), {"version": 2}, user, profile, cache) == accepted
    assert len(profile.writes) == 1 and "voice_google_processing_ack_v1_at" in profile.fields
    with pytest.raises(HTTPException) as error:
        await route.record_processing_ack(request("https://foreign.example"), {"version": 2}, user, profile, cache)
    assert error.value.status_code == 403
    profile.fields.pop(route.PROCESSING_ACK_FIELD)
    profile.write_success = False
    with pytest.raises(HTTPException) as error:
        await route.record_processing_ack(request(), {"version": 2}, user, profile, cache)
    assert error.value.status_code == 503


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
    assert [(await fixture.receive())["type"] for _ in range(3)] == ["turn.start", "transcription.text.delta", "turn.end"]
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
    assert not any(event["type"] == "audio.interrupted" for event in socket.sent)


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
    assert not any(event["type"] == "audio.interrupted" for event in socket.sent)


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
