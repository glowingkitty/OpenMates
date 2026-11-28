"""Guest voice call socket and guest spoken reply: admission, metering, lock release."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import anonymous_speech, voice_call_guest
from backend.core.api.app.services import guest_transcription_meter as guest_module
from backend.tests.test_guest_audio_transcription import Service, Socket


class CallSocket(Socket):
    def __init__(self, start=None):
        super().__init__()
        self.query_params = {"anonymous_id": "stable-guest"}
        self.inputs = [start if start is not None else {"type": "start", "privacy_ack_version": 3}]

    async def receive_text(self):
        # Poll so frames appended later (a hangup after the turn) are delivered.
        while not self.inputs:
            await asyncio.sleep(0.01)
        return json.dumps(self.inputs.pop(0))


class FakeProvider:
    instances = []
    model = "fake-stt"

    def __init__(self, _key=None):
        self.audio = []
        self.closed = False
        self.events = asyncio.Queue()
        FakeProvider.instances.append(self)

    async def open(self):
        return None

    async def send_audio(self, data):
        self.audio.append(data)

    async def end_audio(self):
        return None

    async def receive(self):
        return await self.events.get()

    async def close(self):
        self.closed = True


@pytest.fixture
def call_setup(monkeypatch):
    FakeProvider.instances = []
    services = []

    def factory(**kwargs):
        services.append(Service(**kwargs))
        return services[-1]

    monkeypatch.setattr(guest_module, "AnonymousFreeUsageService", factory)
    monkeypatch.setattr(
        "backend.core.api.app.utils.server_mode.validate_request_domain",
        lambda _ws: ("app.dev.openmates.org", False, "development"),
    )
    monkeypatch.setattr(voice_call_guest, "VoxtralVoiceSession", FakeProvider)
    monkeypatch.setattr(voice_call_guest, "isolated_voice_fixture_enabled", lambda: False)
    async def no_control_intent(*_args):
        return voice_call_guest.PauseDecision("finished", "none", 0.5)

    monkeypatch.setattr(voice_call_guest, "_guest_pause_decision", no_control_intent)
    return services


def pcm(seconds=0.1):
    return base64.b64encode(bytes(int(32000 * seconds))).decode()


def kinds(socket):
    return [m.get("type") for m in socket.messages]


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize("supplied", ["cookie", "token", "authorization"])
async def test_credentialed_connection_is_refused_before_anything(call_setup, supplied):
    socket = CallSocket()
    if supplied == "cookie":
        socket.cookies["auth_refresh_token"] = "x"
    elif supplied == "token":
        socket.query_params["token"] = "x"
    else:
        socket.headers["authorization"] = "Bearer x"
    await voice_call_guest.guest_voice_call(socket)
    assert socket.messages[0]["type"] == "closed"
    assert "accepted" not in kinds(socket) and not call_setup and not FakeProvider.instances


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_wrong_origin_is_refused(call_setup):
    socket = CallSocket()
    socket.headers["origin"] = "https://evil.example.org"
    await voice_call_guest.guest_voice_call(socket)
    assert socket.messages[0]["type"] == "closed" and not FakeProvider.instances


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize("start", [{"type": "start"}, {"type": "start", "privacy_ack_version": 2},
                                   {"type": "start", "privacy_ack_version": True}])
async def test_missing_ack_closes_before_provider_work(call_setup, start):
    socket = CallSocket(start)
    await voice_call_guest.guest_voice_call(socket)
    assert socket.messages[1]["code"] == "voice_ack_required"
    assert socket.messages[-1]["reason"] == "voice_ack_required"
    assert not call_setup and not FakeProvider.instances


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_denied_allowance_opens_no_provider_and_releases_locks(call_setup, monkeypatch):
    original = guest_module.AnonymousFreeUsageService

    def denying(**kwargs):
        service = original(**kwargs)
        service.allowed = False
        return service

    monkeypatch.setattr(guest_module, "AnonymousFreeUsageService", denying)
    socket = CallSocket()
    await voice_call_guest.guest_voice_call(socket)
    error = next(m for m in socket.messages if m.get("type") == "error")
    assert error["code"] == "budget_exhausted" and error["signup_required"] is True
    assert not FakeProvider.instances
    assert not socket.app.state.cache_service.rows


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_reserves_before_forwarding_settles_and_releases_on_hangup(call_setup):
    socket = CallSocket()
    socket.inputs += [{"type": "mic_audio", "data": pcm(4.0625)}, {"type": "hangup"}]
    await voice_call_guest.guest_voice_call(socket)
    service = call_setup[0]
    assert kinds(socket)[:2] == ["accepted", "ready"]
    assert kinds(socket).count("ended") == 1
    provider = FakeProvider.instances[0]
    assert len(provider.audio) == 1 and provider.closed
    names = [e[0] for e in service.events]
    assert names.index("open") < names.index("reserve")
    assert names.index("reserve", names.index("reserve") + 1) < len(names)
    reserves = [e for e in service.events if e[0] == "reserve"]
    assert len(reserves) == 2 and reserves[-1][1]["quoted_credits"] >= 1
    assert service.events[-1][0] == "settle"
    assert not socket.app.state.cache_service.rows


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_allowance_exhausted_mid_call_sends_limit_error_without_forwarding(call_setup, monkeypatch):
    original = guest_module.AnonymousFreeUsageService

    def limited(**kwargs):
        service = original(**kwargs)
        service.reject_after = 1  # Admission covers one credit, but the frame requires two.
        return service

    monkeypatch.setattr(guest_module, "AnonymousFreeUsageService", limited)
    socket = CallSocket()
    socket.inputs += [{"type": "mic_audio", "data": pcm(4.0625)}]
    await voice_call_guest.guest_voice_call(socket)
    error = next(m for m in socket.messages if m.get("type") == "error")
    assert error["code"] == "per_identity_exhausted" and error["signup_required"] is True
    assert FakeProvider.instances[0].audio == [] and FakeProvider.instances[0].closed
    assert not socket.app.state.cache_service.rows


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_finished_turn_is_returned_as_final_transcript(call_setup, monkeypatch):
    monkeypatch.setattr(voice_call_guest, "GUEST_TURN_SILENCE_SECONDS", 0.01)
    socket = CallSocket()
    socket.inputs += [{"type": "mic_audio", "data": pcm()}]
    task = asyncio.create_task(voice_call_guest.guest_voice_call(socket))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if FakeProvider.instances:
            break
    events = FakeProvider.instances[0].events
    for event in ({"type": "turn.start"}, {"type": "transcription.text.delta", "text": "Hello there"},
                  {"type": "turn.end"}):
        await events.put(event)
    for _ in range(100):
        await asyncio.sleep(0.01)
        if any(m.get("final") for m in socket.messages):
            break
    socket.inputs.append({"type": "hangup"})
    await asyncio.wait_for(task, 5)
    transcripts = [m for m in socket.messages if m.get("type") == "transcript"]
    assert [m["final"] for m in transcripts] == [False, True]
    assert transcripts[-1]["text"] == "Hello there"
    assert not socket.app.state.cache_service.rows


# contract-test: supporting surface=rest_api assertions=video-call.guest-calls
@pytest.mark.parametrize("end_with_local_gate", [False, True])
async def test_guest_keeps_trailing_words_through_the_endpoint(call_setup, monkeypatch, end_with_local_gate):
    monkeypatch.setattr(voice_call_guest, "GUEST_LOCAL_ENDPOINT_GRACE_SECONDS", 0.15)
    monkeypatch.setattr(voice_call_guest, "GUEST_TURN_SILENCE_SECONDS", 0.15)
    socket = CallSocket({"type": "start", "privacy_ack_version": 3})
    socket.inputs.append({"type": "mic_audio", "data": pcm()})
    task = asyncio.create_task(voice_call_guest.guest_voice_call(socket))
    async with asyncio.timeout(3):
        while not FakeProvider.instances or not FakeProvider.instances[0].audio:
            await asyncio.sleep(0.01)
        events = FakeProvider.instances[0].events
        await events.put({"type": "turn.start"})
        await events.put({"type": "transcription.text.delta", "text": "Book for two"})
        while "transcript" not in kinds(socket):
            await asyncio.sleep(0.01)
        if end_with_local_gate:
            socket.inputs.append({"type": "audio_stream_end", "verified_silence": True})
        await events.put({"type": "transcription.text.delta", "text": " on Tuesday"})
        if not end_with_local_gate:
            await events.put({"type": "turn.end"})
        while not any(msg.get("final") for msg in socket.messages):
            await asyncio.sleep(0.01)
    socket.inputs.append({"type": "hangup"})
    await asyncio.wait_for(task, 3)
    assert [msg["text"] for msg in socket.messages if msg.get("final")] == ["Book for two on Tuesday"]
    assert not socket.app.state.cache_service.rows


# contract-test: supporting surface=rest_api assertions=video-call.guest-calls,video-call.lifecycle.recovery-and-billing
async def test_guest_quiet_remains_free_until_the_existing_hard_cap(call_setup, monkeypatch):
    monkeypatch.setattr(voice_call_guest, "MAX_CALL_SECONDS", 0.25)
    socket = CallSocket()
    task = asyncio.create_task(voice_call_guest.guest_voice_call(socket))
    async with asyncio.timeout(3):
        while "ready" not in kinds(socket):
            await asyncio.sleep(0.01)
        socket.inputs.extend([{"type": "ping"}, {"type": "audio_stream_end", "verified_silence": True}])
        while socket.inputs:
            await asyncio.sleep(0.01)
        assert not task.done()
        await task
    assert not FakeProvider.instances[0].audio
    assert [event.get("reason") for event in socket.messages if event["type"] == "ended"] == ["time_limit"]
    assert "speech_idle_warning" not in kinds(socket)
    assert call_setup[0].events[-1][2] == 0


# contract-test: supporting surface=rest_api assertions=video-call.guest-calls,video-call.waiting.spoken-intent-and-merge
async def test_guest_spoken_hold_does_not_admit_an_answer_turn(call_setup, monkeypatch):
    heard = []

    async def intent(words, _socket, _meter):
        heard.append(words)
        selected = "wait" if words == "Give me a second." else "resume" if words == "I'm back." else "none"
        return voice_call_guest.PauseDecision("finished", selected, 0.5)

    monkeypatch.setattr(voice_call_guest, "_guest_pause_decision", intent)
    monkeypatch.setattr(voice_call_guest, "GUEST_TURN_SILENCE_SECONDS", 0.01)
    socket = CallSocket()
    task = asyncio.create_task(voice_call_guest.guest_voice_call(socket))
    async with asyncio.timeout(3):
        while "ready" not in kinds(socket):
            await asyncio.sleep(0.01)
        events = FakeProvider.instances[0].events
        for words, line in [("Give me a second.", "waiting_start"), ("I'm back.", "waiting_resume")]:
            await events.put({"type": "turn.start"})
            await events.put({"type": "transcription.text.delta", "text": words})
            await events.put({"type": "turn.end"})
            while not any(event.get("line") == line for event in socket.messages):
                await asyncio.sleep(0.01)
            assert not any(event.get("final") for event in socket.messages)
        await events.put({"type": "turn.start"})
        await events.put({"type": "transcription.text.delta", "text": "Find a train."})
        await events.put({"type": "turn.end"})
        while not any(event.get("final") for event in socket.messages):
            await asyncio.sleep(0.01)
        socket.inputs.append({"type": "hangup"})
        await task
    assert heard == ["Give me a second.", "I'm back.", "Find a train."]
    assert [event["text"] for event in socket.messages if event.get("final")] == ["Give me a second. Find a train."]


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_locks_released_when_provider_fails(call_setup, monkeypatch):
    class Broken(FakeProvider):
        async def open(self):
            raise RuntimeError("provider down")

    monkeypatch.setattr(voice_call_guest, "VoxtralVoiceSession", Broken)
    socket = CallSocket()
    await voice_call_guest.guest_voice_call(socket)
    assert next(m for m in socket.messages if m.get("type") == "error")["code"] == "call_unavailable"
    assert not socket.app.state.cache_service.rows


def speech_request(origin="https://app.dev.openmates.org"):
    return SimpleNamespace(
        headers={"origin": origin} if origin else {}, cookies={}, client=SimpleNamespace(host="8.8.8.8"),
        app=SimpleNamespace(state=SimpleNamespace(
            allowed_origins=["https://app.dev.openmates.org"], secrets_manager=object())),
    )


@pytest.fixture
def speech_setup(monkeypatch):
    service = Service()
    monkeypatch.setattr(anonymous_speech, "_require_official_cloud", lambda _r: None)
    monkeypatch.setattr(anonymous_speech, "_anonymous_usage_service", lambda *_a: service)

    class Client:
        calls = []

        def __init__(self, **_kw):
            pass

        async def text_to_speech(self, **kwargs):
            Client.calls.append(kwargs)
            return SimpleNamespace(audio_bytes=b"mp3", mime_type="audio/mpeg")

    monkeypatch.setattr(anonymous_speech, "ElevenLabsClient", Client)
    return service, Client


async def call_speech(request, text="Hello", anonymous_id="guest"):
    body = anonymous_speech.AnonymousSpeechRequest(anonymous_id=anonymous_id, text=text)
    return await anonymous_speech.anonymous_speech(request, body, object(), object())


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_speech_reserves_then_settles_and_returns_mpeg(speech_setup):
    service, client = speech_setup
    response = await call_speech(speech_request(), "Hello world")
    assert response.media_type == "audio/mpeg" and response.body == b"mp3"
    names = [e[0] for e in service.events]
    assert names.index("reserve") < names.index("settle") and client.calls
    assert client.calls[0]["model"] == "eleven_v4_turbo"
    assert service.events[-1][2] >= 1


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_speech_refused_when_allowance_exhausted_before_provider(speech_setup):
    service, client = speech_setup
    service.allowed = False
    with pytest.raises(HTTPException) as exc:
        await call_speech(speech_request())
    assert exc.value.status_code == 429
    assert exc.value.detail["signup_required"] is True and not client.calls


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_speech_refuses_wrong_origin_and_long_text(speech_setup):
    _service, client = speech_setup
    with pytest.raises(HTTPException) as exc:
        await call_speech(speech_request("https://evil.example.org"))
    assert exc.value.status_code == 403 and not client.calls
    with pytest.raises(ValueError):
        anonymous_speech.AnonymousSpeechRequest(anonymous_id="g", text="x" * 4001)
    with pytest.raises(ValueError):
        anonymous_speech.AnonymousSpeechRequest(anonymous_id="g", text="   ")


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.asyncio
async def test_speech_provider_failure_finalizes_at_quote(speech_setup):
    service, client = speech_setup

    async def failing(self, **kwargs):
        raise RuntimeError("boom")

    client.text_to_speech = failing
    with pytest.raises(HTTPException) as exc:
        await call_speech(speech_request())
    assert exc.value.status_code == 502
    assert service.events[-1][0] == "settle" and service.events[-1][2] >= 1


# contract-test: supporting surface=gui.web assertions=video-call.waiting.spoken-intent-and-merge,video-call.audio.localized-waiting
async def test_guest_categorized_clip_echo_never_reaches_transcript_or_jev(call_setup, monkeypatch):
    from backend.apps.audio.assistant_speech.acknowledgements import prerecorded_clip_text

    heard = []

    async def decide(words, _socket, _meter, *, with_feedback=False):
        assert with_feedback
        heard.append(words)
        return voice_call_guest.PauseDecision("finished", "none", 0.5, "answering", "en")

    monkeypatch.setattr(voice_call_guest, "_guest_pause_decision", decide)
    monkeypatch.setattr(voice_call_guest, "GUEST_TURN_SILENCE_SECONDS", 0.01)
    socket = CallSocket(start={"type": "start", "privacy_ack_version": 3, "instant_feedback": True})
    task = asyncio.create_task(voice_call_guest.guest_voice_call(socket))
    async with asyncio.timeout(3):
        while "ready" not in kinds(socket):
            await asyncio.sleep(0.01)
        provider = FakeProvider.instances[0]

        def heard_words(text):
            provider.events.put_nowait({"type": "turn.start"})
            provider.events.put_nowait({"type": "transcription.text.delta", "text": text})
            provider.events.put_nowait({"type": "turn.end"})

        question = "What is the capital of France?"
        heard_words(question)
        while not any(event.get("final") for event in socket.messages):
            await asyncio.sleep(0.01)
        [clip] = [event["clip"] for event in socket.messages if event["type"] == "voice_feedback"]
        assert "/ace/en-US/reasoning-" in clip["asset_url"]
        before = list(socket.messages)
        heard_words(prerecorded_clip_text(clip["asset_url"]))
        # Allow the normal provider endpoint to settle the echo.
        await asyncio.sleep(0.05)
        assert socket.messages == before
        assert heard == [question]
        socket.inputs.append({"type": "hangup"})
        await task
