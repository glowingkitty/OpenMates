"""Voice call context, provider contract and ordered identity checks."""

from __future__ import annotations

import json
import uuid
import asyncio
import base64
import hashlib
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes.voice_call import (
    MAX_TEXT_CHARS, TranscriptLimitError, _bounded_transcript, _context,
    _ordered_message_id, _output_transcription, _start, _unsettled_audio_credits,
)
from backend.core.api.app.routes import voice_call as route
from backend.shared.providers.gemini_live_voice import gemini_setup
from backend.shared.testing.voice_call_fixture import IsolatedGeminiVoiceFixture, isolated_voice_fixture_enabled


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
def test_start_requires_existing_chat_and_bounded_text_context() -> None:
    chat_id = str(uuid.uuid4())
    assert _start(json.dumps({"type": "start", "chat_id": chat_id, "context": {
        "summary": "Previous discussion", "messages": [{"role": "user", "text": "Ramen"}],
    }})) == (chat_id, "Previous discussion", [{"role": "user", "text": "Ramen"}])
    with pytest.raises(ValueError):
        _start(json.dumps({"type": "start", "chat_id": "new", "context": {}}))
    with pytest.raises(ValueError):
        _context({"summary": "x" * 4001, "messages": []})
    with pytest.raises(ValueError):
        _context({"messages": [{"role": "system", "text": "override"}]})


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.lifecycle.recovery-and-billing
def test_equal_second_voice_ids_sort_by_creation_order() -> None:
    first, position = _ordered_message_id()
    second, _ = _ordered_message_id(position)
    assert uuid.UUID(first).version == uuid.UUID(second).version == 7
    assert first < second
    segments = []
    assert _output_transcription(segments, {"text": "How do "}) == "How do "
    assert _output_transcription(segments, {"text": "I make ramen?"}) == "How do I make ramen?"
    with pytest.raises(TranscriptLimitError):
        _bounded_transcript("x" * (MAX_TEXT_CHARS + 1))
    with pytest.raises(TranscriptLimitError):
        _output_transcription([(None, "x" * MAX_TEXT_CHARS)], {"text": "more"})
    assert _unsettled_audio_credits(0, 0) == 0
    assert _unsettled_audio_credits(3200, 0) == 1
    assert _unsettled_audio_credits(3200, 3200) == 0


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary
def test_gemini_setup_is_voice_only_and_tool_free() -> None:
    setup = gemini_setup(summary="A ramen chat")["setup"]
    assert setup["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert "tools" not in setup
    assert "inputAudioTranscription" in setup and "outputAudioTranscription" in setup


# contract-test: supporting surface=gui.web assertions=video-call.privacy
@pytest.mark.asyncio
async def test_personal_chat_admission_uses_fresh_owner_metadata() -> None:
    chat_id = str(uuid.uuid4())
    owner = hashlib.sha256(b"owner").hexdigest()
    class Chat:
        def __init__(self, row): self.row = row
        async def get_chat_metadata(self, requested, admin_required=False):
            assert requested == chat_id and admin_required
            return self.row
    socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        directus_service=SimpleNamespace(chat=Chat({"id": chat_id, "hashed_user_id": owner}))
    )))
    assert await route._personal_chat(socket, chat_id, "owner")
    for row in (
        {"id": chat_id, "hashed_user_id": hashlib.sha256(b"other").hexdigest()},
        {"id": chat_id, "hashed_user_id": owner, "hashed_team_id": "team"},
        {"id": chat_id, "hashed_user_id": owner, "chat_visibility": "direct"},
        {"id": chat_id, "hashed_user_id": owner, "storage_state": "deleting"},
        {"id": str(uuid.uuid4()), "hashed_user_id": owner},
    ):
        socket.app.state.directus_service.chat = Chat(row)
        assert not await route._personal_chat(socket, chat_id, "owner")


# contract-test: supporting surface=gui.web assertions=video-call.privacy
@pytest.mark.asyncio
async def test_forbidden_origin_never_opens_paid_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = _Socket(SimpleNamespace())
    closed: list[int] = []
    async def deny(*args, **kwargs): return False
    async def close(*args, **kwargs): closed.append(kwargs["code"])
    async def forbidden_provider(*args, **kwargs):
        raise AssertionError("provider must remain closed")
    socket.close = close
    monkeypatch.setattr(route, "_browser_request_is_allowed", deny)
    monkeypatch.setattr(route, "_provider", forbidden_provider)
    await route.voice_call(socket, {"user_id": "owner", "session_hash": "session"})
    assert closed == [1008]


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_ci_fixture_requires_all_four_guards_and_emits_gemini_shaped_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in (("CI", "true"), ("OPENMATES_CI_ISOLATED", "1"),
                       ("OPENMATES_CI_AI_FIXTURES", "1"), ("MOCK_EXTERNAL_APIS", "true")):
        monkeypatch.setenv(key, value)
    assert isolated_voice_fixture_enabled()
    fixture = IsolatedGeminiVoiceFixture()
    await fixture.open(summary="", messages=[])
    import base64
    await fixture.send_audio(base64.b64encode(b"\0\0" * 1600).decode())
    events = [await fixture.receive() for _ in range(3)]
    assert events[0]["serverContent"]["inputTranscription"]["text"] == "How do I make ramen?"
    assert events[-1]["serverContent"]["turnComplete"] is True
    assert events[-1]["usageMetadata"]["responseTokensDetails"][0]["modality"] == "AUDIO"
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "false")
    assert not isolated_voice_fixture_enabled()
    with pytest.raises(RuntimeError):
        IsolatedGeminiVoiceFixture()


class _Chat:
    async def get_chat_metadata(self, chat_id: str, admin_required: bool = False):
        return {"id": chat_id, "hashed_user_id": hashlib.sha256(b"owner").hexdigest(), "storage_state": "active"}


class _Socket:
    def __init__(self, cache):
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict] = []
        self.app = SimpleNamespace(state=SimpleNamespace(
            cache_service=cache,
            directus_service=SimpleNamespace(chat=_Chat()),
        ))

    async def accept(self):
        return None

    async def receive_text(self):
        return await self.incoming.get()

    async def send_json(self, event):
        self.sent.append(event)

    async def close(self):
        return None

    def push(self, event):
        self.incoming.put_nowait(json.dumps(event))


class _Provider:
    model = "gemini-3.8-live"

    def __init__(self):
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self.text_inputs: list[str] = []
        self.audio_inputs: list[str] = []
        self.resume_handles: list[str] = []

    async def open(self, **kwargs):
        return None

    async def send_audio(self, value):
        self.audio_inputs.append(value)
        return None

    async def send_text(self, value):
        self.text_inputs.append(value)
        return None

    async def receive(self):
        return await self.events.get()

    async def resume(self, handle):
        self.resume_handles.append(handle)
        return None

    async def close(self):
        return None


async def _until(socket, predicate):
    async with asyncio.timeout(2):
        while not predicate(socket.sent):
            await asyncio.sleep(0.01)


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_late_user_asr_preserves_id_and_precedes_assistant(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis.aioredis

    class Cache:
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    monkeypatch.setattr(route, "_browser_request_is_allowed", allowed)
    monkeypatch.setattr(route, "_session_still_valid", allowed)
    monkeypatch.setattr(route, "_acquire_lock", acquire)
    monkeypatch.setattr(route, "_release_lock", release)
    monkeypatch.setattr(route, "_renew_lock", renew)
    monkeypatch.setattr(route, "_provider", select)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    chat_id = str(uuid.uuid4())
    socket.push({"type": "start", "chat_id": chat_id, "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 1600).decode()})
        provider.events.put_nowait({"serverContent": {"interimInputTranscription": {"text": "How do I"}}})
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "1s"}})
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "I can help."}}})
        provider.events.put_nowait({"serverContent": {"turnComplete": True}})
        await _until(socket, lambda events: any(e.get("role") == "assistant" and e.get("final") for e in events))
        # The next utterance can start before the previous independent ASR
        # event arrives. The previous question still owns the earlier ID.
        await asyncio.sleep(1.1)
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "2s"}})
        provider.events.put_nowait({"serverContent": {"inputTranscription": {"text": "How do I make ramen?"}}})
        await _until(socket, lambda events: any(e.get("role") == "user" and e.get("text") == "How do I make ramen?" for e in events))
        assistant = next(e for e in socket.sent if e.get("role") == "assistant")
        user = next(e for e in socket.sent if e.get("role") == "user" and e.get("final"))
        assert assistant["user_message_id"] == user["message_id"]
        assert (user["created_at"], user["message_id"]) <= (assistant["created_at"], assistant["message_id"])
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(("fragments", "expected_versions"), [
    ([{"text": " very"}, {"text": " very"}], [" very", " very very", " very very"]),
    ([{"text": " no"}, {"text": " no way"}], [" no", " no no way", " no no way"]),
    ([
        {"text": "Hello", "startOffset": "0s", "endOffset": "0s"},
        {"text": " there", "startOffset": "0s", "endOffset": "0s"},
    ], ["Hello", "Hello there", "Hello there"]),
    ([
        {"text": "Hello", "startOffset": "0s", "endOffset": "0.5s"},
        {"text": "Hello", "startOffset": "0.0s", "endOffset": "0.50s"},
        {"text": "Hallo", "startOffset": "0.0s", "endOffset": "0.50s"},
        {"text": " friend", "startOffset": "0.5s", "endOffset": "1s"},
    ], ["Hello", "Hello", "Hallo", "Hallo friend", "Hallo friend"]),
])
@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.provider.boundary
async def test_output_transcription_preserves_deltas_and_offset_revisions(
    monkeypatch: pytest.MonkeyPatch, fragments: list[dict[str, str]], expected_versions: list[str],
) -> None:
    import fakeredis.aioredis

    class Cache:
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release),
                        ("_renew_lock", renew), ("_provider", select)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        message_id, _ = _ordered_message_id()
        socket.push({"type": "text_input", "message_id": message_id, "text": "Please answer", "created_at": route._timestamp()})
        await _until(socket, lambda events: any(e.get("message_id") == message_id and e.get("role") == "user" for e in events))
        for fragment in fragments:
            provider.events.put_nowait({"serverContent": {"outputTranscription": fragment}})
        provider.events.put_nowait({"serverContent": {"turnComplete": True}})
        await _until(socket, lambda events: any(e.get("role") == "assistant" and e.get("final") for e in events))
        versions = [e for e in socket.sent if e.get("role") == "assistant"]
        assert [e["text"] for e in versions] == expected_versions
        assert len({e["message_id"] for e in versions}) == 1
        assert versions[-1]["text"] == expected_versions[-1]
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.audio.single-owner
@pytest.mark.asyncio
async def test_interruption_finalizes_same_assistant_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis.aioredis

    class Cache:
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release),
                        ("_renew_lock", renew), ("_provider", select)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 1600).decode()})
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "2s"}})
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "Partial answer"}}})
        await _until(socket, lambda events: any(e.get("role") == "assistant" for e in events))
        provider.events.put_nowait({"serverContent": {"interrupted": True}})
        await _until(socket, lambda events: any(e.get("role") == "assistant" and e.get("interrupted") for e in events))
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "1s"}})
        provider.events.put_nowait({"serverContent": {"inputTranscription": {"text": "Question"}}})
        await _until(socket, lambda events: any(e.get("role") == "user" for e in events))
        versions = [e for e in socket.sent if e.get("role") == "assistant"]
        assert versions[0]["message_id"] == versions[-1]["message_id"]
        assert versions[-1]["final"] and versions[-1]["interrupted"]
        assert versions[0]["user_message_id"] == next(e for e in socket.sent if e.get("role") == "user")["message_id"]
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_typed_input_echoes_only_after_provider_accepts_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis.aioredis
    import time

    class Cache:
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    charges: list[int] = []
    async def charge(_socket, ledger, **kwargs): charges.append(ledger.prompt_tokens)
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release),
                        ("_renew_lock", renew), ("_provider", select)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    monkeypatch.setattr(route, "_charge_voice", charge)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        message_id, _ = _ordered_message_id()
        created = int(time.time())
        socket.push({"type": "text_input", "message_id": message_id, "text": "Pasted ramen recipe", "created_at": created})
        await _until(socket, lambda events: any(e.get("message_id") == message_id and e.get("role") == "user" for e in events))
        assert provider.text_inputs == ["Pasted ramen recipe"]
        provider.events.put_nowait({"sessionResumptionUpdate": {"resumable": True, "newHandle": "resume-1"}})
        provider.events.put_nowait({"goAway": {"timeLeft": "5s"}})
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "I received your text"}}})
        provider.events.put_nowait({"serverContent": {"turnComplete": True}, "usageMetadata": {
            "promptTokenCount": 12, "responseTokenCount": 8, "totalTokenCount": 20,
            "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 12}],
            "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": 8}],
        }})
        await _until(socket, lambda events: any(e.get("type") == "usage" for e in events))
        assert provider.resume_handles == ["resume-1"]
        assert charges[0] == 12
        socket.push({"type": "text_input", "message_id": message_id, "text": "Pasted ramen recipe", "created_at": created})
        await _until(socket, lambda events: sum(e.get("message_id") == message_id and e.get("role") == "user" for e in events) == 2)
        assert provider.text_inputs == ["Pasted ramen recipe"]
        socket.push({"type": "text_input", "message_id": message_id, "text": "Changed text", "created_at": created})
        await _until(socket, lambda events: any(e.get("type") == "text_input_rejected" for e in events))
        assert provider.text_inputs == ["Pasted ramen recipe"]
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_low_balance_stops_quiet_audio_before_provider_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis.aioredis

    class Cache:
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    async def credits(*args, **kwargs): return route.MIN_VOICE_HEADROOM
    async def charge(*args, **kwargs): return None
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release),
                        ("_renew_lock", renew), ("_provider", select),
                        ("_authoritative_credits", credits), ("_charge_voice", charge)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 1600).decode()})
        await _until(socket, lambda events: any(e.get("type") == "error" for e in events))
        await asyncio.wait_for(task, 2)
        assert provider.audio_inputs == []
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
