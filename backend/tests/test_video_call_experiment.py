"""Provider and metering contracts for the ephemeral call experiment."""

import asyncio
import base64
import json
import time

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes import video_call_experiment as call
from backend.shared.providers.fal import h3_turbo


class _RouteSocket:
    def __init__(self, app, *, origin="https://openmates.test"):
        self.app = app
        self.headers = {"origin": origin}
        self.query_params = {}
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.outgoing: asyncio.Queue[dict] = asyncio.Queue()
        self.sent: list[dict] = []
        self.accepted = False
        self.closed = False
        self.close_reason = None

    async def accept(self):
        self.accepted = True

    async def close(self, *, code=None, reason=None):
        self.closed = True
        self.close_reason = reason

    async def send_json(self, event):
        self.sent.append(event)
        self.outgoing.put_nowait(event)

    async def receive_text(self):
        return await self.incoming.get()

    def send(self, event):
        self.incoming.put_nowait(json.dumps(event))

    async def expect(self, event_type, *, reason=None):
        while True:
            event = await asyncio.wait_for(self.outgoing.get(), timeout=2)
            if event.get("type") == event_type and (reason is None or event.get("reason") == reason):
                return event


class _RouteProvider:
    def __init__(self):
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()
        self.incoming.put_nowait({"setupComplete": {}})
        self.sent: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def send_json(self, event):
        self.sent.append(event)

    async def receive(self):
        event = await self.incoming.get()
        return SimpleNamespace(type=call.aiohttp.WSMsgType.BINARY, data=json.dumps(event).encode("utf-8"))

    def send(self, event):
        self.incoming.put_nowait(event)


@pytest.fixture
def route_harness(monkeypatch):
    """Exercise the actual route loop without provider or billing I/O."""
    redis = SimpleNamespace(values={})

    async def redis_set(key, value, *, nx, ex):
        if nx and key in redis.values:
            return False
        redis.values[key] = value
        return True

    async def redis_get(key):
        return redis.values.get(key)

    async def redis_delete(key):
        redis.values.pop(key, None)

    redis.set, redis.get, redis.delete = redis_set, redis_get, redis_delete
    class FakeCache:
        SESSION_KEY_PREFIX = "session:"

        @property
        def client(self):
            async def current_client():
                return redis

            return current_client()

    cache = FakeCache()

    async def get_secret(path, field):
        return "fixture-key"

    app = SimpleNamespace(state=SimpleNamespace(
        allowed_origins=["https://openmates.test"],
        cache_service=cache,
        secrets_manager=SimpleNamespace(get_secret=get_secret),
    ))
    providers = []

    class FakeHttpClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def put(self, *args, **kwargs):
            return SimpleNamespace(is_success=True)

    class FakeSession:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def ws_connect(self, *args, **kwargs):
            provider = _RouteProvider()
            providers.append(provider)
            return provider

    async def valid_session(*args):
        return True

    async def no_charge(*args, **kwargs):
        return None

    monkeypatch.setattr(call.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(call.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(call, "is_payment_enabled", lambda: False)
    monkeypatch.setattr(call, "_session_still_valid", valid_session)
    monkeypatch.setattr(call, "_charge", no_charge)
    return SimpleNamespace(app=app, redis=redis, providers=providers, socket=lambda **kwargs: _RouteSocket(app, **kwargs))


def _visual_instruction(call_id="visual-1"):
    return {"toolCall": {"functionCalls": [{"id": call_id, "name": "generate_visual_clip", "args": {"prompt": "A forest at dusk"}}]}}


async def _expect_tool_result(provider, call_id, expected):
    while True:
        for event in provider.sent:
            responses = (event.get("toolResponse") or {}).get("functionResponses") or []
            if responses and responses[0].get("id") == call_id:
                assert expected in responses[0].get("response", {}).get("result", "")
                return
        await asyncio.sleep(0.001)


# contract-test: supporting surface=gui.web assertions=video-call.experiment.privacy
@pytest.mark.asyncio
async def test_route_rejects_missing_auth_and_foreign_origin_before_provider(route_harness) -> None:
    unauthenticated = route_harness.socket()
    await call.video_call(unauthenticated, auth_data=None)
    assert not unauthenticated.accepted
    assert not route_harness.providers

    foreign_origin = route_harness.socket(origin="https://foreign.test")
    await call.video_call(foreign_origin, auth_data={"user_id": "user-1"})
    assert foreign_origin.closed and not foreign_origin.accepted
    assert foreign_origin.close_reason == "Origin not allowed"
    assert not route_harness.providers
    assert not route_harness.redis.values


# contract-test: supporting surface=gui.web assertions=video-call.experiment.live-voice
@pytest.mark.asyncio
async def test_route_rejects_concurrent_call_for_same_user_then_releases_lock(route_harness) -> None:
    auth = {"user_id": "user-1"}
    first = route_harness.socket()
    first_task = asyncio.create_task(call.video_call(first, auth_data=auth))
    await first.expect("ready")

    second = route_harness.socket()
    await call.video_call(second, auth_data=auth)
    assert second.closed and not second.accepted
    assert second.close_reason == "Call admission unavailable"
    assert len(route_harness.providers) == 1

    first.send({"type": "hangup"})
    await first.expect("ended", reason="user")
    await asyncio.wait_for(first_task, timeout=2)
    assert not route_harness.redis.values

    third = route_harness.socket()
    third_task = asyncio.create_task(call.video_call(third, auth_data=auth))
    await third.expect("ready")
    third.send({"type": "hangup"})
    await asyncio.wait_for(third_task, timeout=2)
    assert len(route_harness.providers) == 2


# contract-test: supporting surface=gui.web assertions=video-call.experiment.live-voice
@pytest.mark.asyncio
async def test_binary_gemini_setup_and_speech_reach_the_caller(route_harness) -> None:
    socket = route_harness.socket()
    task = asyncio.create_task(call.video_call(socket, auth_data={"user_id": "user-1"}))
    await socket.expect("ready")
    audio = base64.b64encode(b"\x00\x01\x00\x02").decode("ascii")
    route_harness.providers[0].send({"serverContent": {
        "outputTranscription": {"text": "Hello."},
        "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": audio}}]},
    }})
    assert (await socket.expect("transcript"))["text"] == "Hello."
    assert (await socket.expect("audio_chunk"))["data"] == audio
    socket.send({"type": "hangup"})
    await asyncio.wait_for(task, timeout=2)
    assert not route_harness.redis.values


# contract-test: supporting surface=gui.web assertions=video-call.experiment.generated-visuals
@pytest.mark.asyncio
async def test_video_feedback_does_not_extend_instruction_idle_window(route_harness, monkeypatch) -> None:
    offset = [0.0]
    monkeypatch.setattr(call, "time", SimpleNamespace(
        monotonic=lambda: time.monotonic() + offset[0], time=time.time,
    ))
    submitted = []

    async def submit(*args, **kwargs):
        submitted.append(kwargs["prompt"])
        return h3_turbo.FalJob("clip-1", "status", "result", "cancel")

    async def completed(*args, **kwargs):
        return h3_turbo.FalClip(b"mp4", 1.5, 1.5, "clip-1", b"\xff\xd8x\xff\xd9")

    monkeypatch.setattr(call, "submit_clip", submit)
    monkeypatch.setattr(call, "await_clip", completed)
    websocket = route_harness.socket()
    route_task = asyncio.create_task(call.video_call(websocket, auth_data={"user_id": "user-1"}))
    await websocket.expect("ready")
    provider = route_harness.providers[0]
    provider.send(_visual_instruction())
    await websocket.expect("video.ready")

    offset[0] = 9
    frame = base64.b64encode(b"\xff\xd8x\xff\xd9").decode()
    websocket.send({"type": "video_frame", "data": frame})
    async def feedback_sent():
        while not any("video" in event.get("realtimeInput", {}) for event in provider.sent):
            await asyncio.sleep(0.001)
    await asyncio.wait_for(feedback_sent(), timeout=2)
    assert not route_task.done(), websocket.sent

    offset[0] = 11
    provider.send({})  # Wake the route to enter idle without consuming a frame.
    try:
        stopped = await websocket.expect("video.stopped", reason="idle")
    except TimeoutError:
        pytest.fail(f"idle stop absent: {websocket.sent}")
    assert stopped["finish_playback"] is True
    assert stopped["pending_clip"] is True
    await websocket.expect("video.drain_complete")
    websocket.send({"type": "video_frame", "data": frame})
    async def two_frames_forwarded():
        while sum("video" in event.get("realtimeInput", {}) for event in provider.sent) < 2:
            await asyncio.sleep(0.001)
    await asyncio.wait_for(two_frames_forwarded(), timeout=2)
    websocket.send({"type": "stop_visuals"})
    await websocket.expect("video.stopped", reason="user")
    websocket.send({"type": "video_frame", "data": frame})
    websocket.send({"type": "mic_audio", "data": base64.b64encode(b"\x00\x01").decode()})
    async def mic_forwarded():
        while not any("audio" in event.get("realtimeInput", {}) for event in provider.sent):
            await asyncio.sleep(0.001)
    await asyncio.wait_for(mic_forwarded(), timeout=2)
    assert sum("video" in event.get("realtimeInput", {}) for event in provider.sent) == 2
    provider.send(_visual_instruction("visual-2"))
    await asyncio.wait_for(_expect_tool_result(provider, "visual-2", "visuals are stopped"), timeout=2)
    websocket.send({"type": "hangup"})
    await asyncio.wait_for(route_task, timeout=2)
    assert len(submitted) == 1
    assert not any(event.get("type") == "video.ready" and event.get("clip_id") != "1" for event in websocket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.experiment.generated-visuals,video-call.experiment.live-voice
@pytest.mark.asyncio
async def test_idle_drains_slow_accepted_clip_without_starting_another(route_harness, monkeypatch) -> None:
    offset = [0.0]
    monkeypatch.setattr(call, "time", SimpleNamespace(
        monotonic=lambda: time.monotonic() + offset[0], time=time.time,
    ))
    released = asyncio.Event()
    submitted = []
    cancelled = []

    async def submit(*args, **kwargs):
        submitted.append(kwargs["prompt"])
        return h3_turbo.FalJob("clip-1", "status", "result", "cancel")

    async def complete_later(*args, **kwargs):
        await released.wait()
        return h3_turbo.FalClip(b"mp4", 5.0, 5.0, "clip-1", None)

    async def cancel(*args, **kwargs):
        cancelled.append(True)
        return True

    monkeypatch.setattr(call, "submit_clip", submit)
    monkeypatch.setattr(call, "await_clip", complete_later)
    monkeypatch.setattr(call, "cancel_clip", cancel)
    websocket = route_harness.socket()
    route_task = asyncio.create_task(call.video_call(websocket, auth_data={"user_id": "user-1"}))
    await websocket.expect("ready")
    provider = route_harness.providers[0]
    provider.send(_visual_instruction())
    await websocket.expect("video.queued")

    offset[0] = 11
    provider.send({})  # Wake the route while fal is still generating.
    stopped = await websocket.expect("video.stopped", reason="idle")
    assert stopped["finish_playback"] is True
    assert stopped["pending_clip"] is True
    assert not cancelled
    released.set()
    ready = await websocket.expect("video.ready")
    assert ready["duration_seconds"] == 5.0
    await websocket.expect("video.drain_complete")
    provider.send(_visual_instruction("visual-2"))
    await asyncio.wait_for(_expect_tool_result(provider, "visual-2", "visuals are stopped"), timeout=2)
    websocket.send({"type": "hangup"})
    await asyncio.wait_for(route_task, timeout=2)
    assert len(submitted) == 1
    assert not cancelled


# contract-test: supporting surface=gui.web assertions=video-call.experiment.user-stop,video-call.experiment.billing
@pytest.mark.asyncio
@pytest.mark.parametrize("next_event", ["stop_visuals", "allow_visuals"])
async def test_pending_idle_drain_is_retired_when_visual_epoch_changes(route_harness, monkeypatch, next_event) -> None:
    offset = [0.0]
    monkeypatch.setattr(call, "time", SimpleNamespace(
        monotonic=lambda: time.monotonic() + offset[0], time=time.time,
    ))
    released = asyncio.Event()
    cancelled = []

    async def submit(*args, **kwargs):
        return h3_turbo.FalJob("clip-1", "status", "result", "cancel")

    async def complete_later(*args, **kwargs):
        await released.wait()
        return h3_turbo.FalClip(b"mp4", 5.0, 5.0, "clip-1", None)

    async def cancel(*args, **kwargs):
        cancelled.append(True)
        return True

    monkeypatch.setattr(call, "submit_clip", submit)
    monkeypatch.setattr(call, "await_clip", complete_later)
    monkeypatch.setattr(call, "cancel_clip", cancel)
    websocket = route_harness.socket()
    route_task = asyncio.create_task(call.video_call(websocket, auth_data={"user_id": "user-1"}))
    await websocket.expect("ready")
    provider = route_harness.providers[0]
    provider.send(_visual_instruction())
    await websocket.expect("video.queued")
    offset[0] = 11
    provider.send({})
    assert (await websocket.expect("video.stopped", reason="idle"))["pending_clip"] is True
    websocket.send({"type": next_event})
    if next_event == "stop_visuals":
        await websocket.expect("video.stopped", reason="user")
        assert cancelled
    else:
        websocket.send({"type": "mic_audio", "data": base64.b64encode(b"\x00\x01").decode()})
        async def mic_forwarded():
            while not any("audio" in event.get("realtimeInput", {}) for event in provider.sent):
                await asyncio.sleep(0.001)
        await asyncio.wait_for(mic_forwarded(), timeout=2)
    released.set()
    usage = await websocket.expect("usage")
    assert usage["h3_generated_seconds"] == 5.0
    websocket.send({"type": "hangup"})
    await asyncio.wait_for(route_task, timeout=2)
    assert not any(event.get("type") in ("video.ready", "video.drain_complete") for event in websocket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.experiment.generated-visuals,video-call.experiment.live-voice
@pytest.mark.asyncio
async def test_acknowledged_tool_cancellation_and_audio_interruption_preserve_clip(route_harness, monkeypatch) -> None:
    released = asyncio.Event()
    cancelled = []

    async def submit(*args, **kwargs):
        return h3_turbo.FalJob("clip-1", "status", "result", "cancel")

    async def complete_later(*args, **kwargs):
        await released.wait()
        return h3_turbo.FalClip(b"mp4", 5.0, 5.0, "clip-1", None)

    async def cancel(*args, **kwargs):
        cancelled.append(True)
        return True

    monkeypatch.setattr(call, "submit_clip", submit)
    monkeypatch.setattr(call, "await_clip", complete_later)
    monkeypatch.setattr(call, "cancel_clip", cancel)
    websocket = route_harness.socket()
    route_task = asyncio.create_task(call.video_call(websocket, auth_data={"user_id": "user-1"}))
    await websocket.expect("ready")
    provider = route_harness.providers[0]
    provider.send(_visual_instruction())
    await websocket.expect("video.queued")
    await asyncio.wait_for(_expect_tool_result(provider, "visual-1", "accepted"), timeout=2)
    audio = base64.b64encode(b"\x00\x01\x00\x02").decode("ascii")
    provider.send({
        "toolCallCancellation": {"ids": ["visual-1"]},
        "serverContent": {
            "interrupted": True,
            "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": audio}}]},
        },
    })
    await websocket.expect("audio.interrupted")
    assert (await websocket.expect("audio_chunk"))["data"] == audio
    assert not cancelled
    released.set()
    await websocket.expect("video.ready")
    assert not any(event.get("type") == "video.stopped" for event in websocket.sent)
    websocket.send({"type": "hangup"})
    await asyncio.wait_for(route_task, timeout=2)


# contract-test: supporting surface=gui.web assertions=video-call.experiment.user-stop,video-call.experiment.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("exit_kind", ["stop_visuals", "hangup", "expiry"])
async def test_late_completed_clip_is_fenced_after_stop_hangup_or_expiry(route_harness, monkeypatch, exit_kind) -> None:
    offset = [0.0]
    monkeypatch.setattr(call, "time", SimpleNamespace(
        monotonic=lambda: time.monotonic() + offset[0], time=time.time,
    ))
    released = asyncio.Event()
    submitted = []
    cancelled = []

    async def submit(*args, **kwargs):
        submitted.append(kwargs["prompt"])
        return h3_turbo.FalJob("clip-1", "status", "result", "cancel")

    async def complete_later(*args, **kwargs):
        await released.wait()
        return h3_turbo.FalClip(b"mp4", 5.0, 5.0, "clip-1", None)

    async def cancel(*args, **kwargs):
        cancelled.append(True)
        return True

    async def session_valid(*args):
        return offset[0] < 6

    monkeypatch.setattr(call, "submit_clip", submit)
    monkeypatch.setattr(call, "await_clip", complete_later)
    monkeypatch.setattr(call, "cancel_clip", cancel)
    monkeypatch.setattr(call, "_session_still_valid", session_valid)
    websocket = route_harness.socket()
    route_task = asyncio.create_task(call.video_call(websocket, auth_data={"user_id": "user-1"}))
    await websocket.expect("ready")
    provider = route_harness.providers[0]
    provider.send(_visual_instruction())
    await websocket.expect("video.queued")

    if exit_kind == "expiry":
        offset[0] = 6
        provider.send({})  # Wake the receive loop to recheck the session.
    else:
        websocket.send({"type": exit_kind})
        if exit_kind == "stop_visuals":
            await websocket.expect("video.stopped", reason="user")
            provider.send(_visual_instruction("visual-2"))
            await asyncio.wait_for(_expect_tool_result(provider, "visual-2", "visuals are stopped"), timeout=2)
        else:
            async def cancellation_observed():
                while not cancelled:
                    await asyncio.sleep(0.001)
            await asyncio.wait_for(cancellation_observed(), timeout=2)
    if exit_kind == "expiry":
        async def expiry_observed():
            while not cancelled:
                await asyncio.sleep(0.001)
        await asyncio.wait_for(expiry_observed(), timeout=2)
    released.set()
    if exit_kind == "stop_visuals":
        websocket.send({"type": "hangup"})
    await asyncio.wait_for(route_task, timeout=2)
    assert len(submitted) == 1
    assert cancelled
    assert not any(event.get("type") == "video.ready" for event in websocket.sent)
    assert not route_harness.redis.values
    if exit_kind == "expiry":
        assert any(event.get("type") == "error" and event.get("code") == "call_unavailable" for event in websocket.sent), websocket.sent


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
def test_zero_output_tool_usage_can_omit_response_modalities() -> None:
    ledger = call.UsageLedger()
    ledger.stage_gemini({
        "totalTokenCount": 100, "promptTokenCount": 100, "responseTokenCount": 0,
        "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 100}],
    })
    assert ledger.commit_gemini_turn()
    assert ledger.gemini_cost == Decimal("0.000075")
    assert ledger.response_tokens == 0


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
@pytest.mark.parametrize("details", [None, []])
def test_positive_output_usage_still_requires_modalities(details) -> None:
    ledger = call.UsageLedger()
    ledger.stage_gemini({
        "totalTokenCount": 10, "responseTokenCount": 10,
        "responseTokensDetails": details,
    })
    with pytest.raises(ValueError, match="modality-level usage"):
        ledger.commit_gemini_turn()
    assert ledger.gemini_cost == 0


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
@pytest.mark.parametrize("details", [None, []])
def test_live_tool_only_output_without_modality_details_is_billed_as_text(details) -> None:
    ledger = call.UsageLedger()
    ledger.observe_gemini_output(_visual_instruction())
    # Sanitized shape from a real Gemini-only spoken tool probe.
    ledger.stage_gemini({
        "totalTokenCount": 857, "promptTokenCount": 793, "responseTokenCount": 64,
        "promptTokensDetails": [
            {"modality": "TEXT", "tokenCount": 455},
            {"modality": "AUDIO", "tokenCount": 283},
        ],
        "responseTokensDetails": details,
    })
    assert ledger.commit_gemini_turn()
    assert ledger.gemini_cost == Decimal("0.00147825")
    assert ledger.response_tokens == 64
    # A previous tool call cannot classify the following unknown turn.
    ledger.stage_gemini({"responseTokenCount": 10})
    with pytest.raises(ValueError, match="modality-level usage"):
        ledger.commit_gemini_turn()


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
def test_mixed_tool_and_audio_output_still_requires_modality_details() -> None:
    ledger = call.UsageLedger()
    ledger.observe_gemini_output(_visual_instruction())
    ledger.observe_gemini_output({"serverContent": {"modelTurn": {"parts": [
        {"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": "AAAA"}},
    ]}}})
    ledger.stage_gemini({"responseTokenCount": 10})
    with pytest.raises(ValueError, match="modality-level usage"):
        ledger.commit_gemini_turn()
    assert ledger.gemini_cost == 0


# contract-test: supporting surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.generated-visuals,video-call.experiment.billing
@pytest.mark.asyncio
@pytest.mark.parametrize("response_tokens", [0, 64])
async def test_tool_only_usage_does_not_cancel_an_accepted_video(route_harness, monkeypatch, response_tokens) -> None:
    accepted = asyncio.Event()
    released = asyncio.Event()
    cancellations = []

    async def submit(*args, **kwargs):
        accepted.set()
        return h3_turbo.FalJob("clip-1", "status", "result", "cancel")

    async def complete(*args, **kwargs):
        await released.wait()
        return h3_turbo.FalClip(b"mp4", 1.5, 1.5, "clip-1", b"\xff\xd8x\xff\xd9")

    async def cancel(*args, **kwargs):
        cancellations.append(True)
        return True

    monkeypatch.setattr(call, "submit_clip", submit)
    monkeypatch.setattr(call, "await_clip", complete)
    monkeypatch.setattr(call, "cancel_clip", cancel)
    socket = route_harness.socket()
    task = asyncio.create_task(call.video_call(socket, auth_data={"user_id": "user-1"}))
    try:
        await socket.expect("ready")
        provider = route_harness.providers[0]
        provider.send(_visual_instruction())
        await asyncio.wait_for(accepted.wait(), timeout=2)
        provider.send({"serverContent": {"turnComplete": True}, "usageMetadata": {
            "totalTokenCount": 100 + response_tokens, "promptTokenCount": 100, "responseTokenCount": response_tokens,
            "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 100}],
        }})
        await socket.expect("usage")
        released.set()
        await socket.expect("video.ready")
        assert not cancellations
        assert not any(event.get("type") == "error" for event in socket.sent)
        reply = next(event["toolResponse"]["functionResponses"][0] for event in provider.sent if "toolResponse" in event)
        assert reply["scheduling"] == "SILENT"
        assert "scheduling" not in reply["response"]
    finally:
        released.set()
        socket.send({"type": "hangup"})
        await asyncio.wait_for(task, timeout=2)
    assert not route_harness.redis.values


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
def test_gemini_modality_usage_bills_rebilled_context_and_text_output() -> None:
    ledger = call.UsageLedger()
    usage = {
        "totalTokenCount": 710,
        "promptTokenCount": 600,
        "responseTokenCount": 110,
        "promptTokensDetails": [
            {"modality": "AUDIO", "tokenCount": 400},
            {"modality": "TEXT", "tokenCount": 100},
            {"modality": "VIDEO", "tokenCount": 100},
        ],
        "responseTokensDetails": [
            {"modality": "AUDIO", "tokenCount": 100},
            {"modality": "TEXT", "tokenCount": 10},
        ],
    }
    ledger.stage_gemini(usage)
    assert ledger.commit_gemini_turn()
    ledger.stage_gemini(usage)  # same context is billed again on the next turn
    assert ledger.commit_gemini_turn()
    expected_turn_cost = Decimal("400") * Decimal("3") / 1_000_000
    expected_turn_cost += Decimal("100") * Decimal("0.75") / 1_000_000
    expected_turn_cost += Decimal("100") * Decimal("1") / 1_000_000
    expected_turn_cost += Decimal("100") * Decimal("12") / 1_000_000
    expected_turn_cost += Decimal("10") * Decimal("4.5") / 1_000_000
    assert ledger.gemini_cost == expected_turn_cost * 2
    assert ledger.context_tokens == 1200
    assert ledger.response_tokens == 220


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
def test_invalid_gemini_usage_does_not_partially_change_ledger() -> None:
    ledger = call.UsageLedger()
    ledger.stage_gemini({
        "totalTokenCount": 2,
        "promptTokenCount": 2,
        "responseTokenCount": 0,
        "promptTokensDetails": [
            {"modality": "TEXT", "tokenCount": 1},
            {"modality": "UNKNOWN", "tokenCount": 1},
        ],
        "responseTokensDetails": [],
    })
    with pytest.raises(ValueError, match="unknown modality"):
        ledger.commit_gemini_turn()
    assert ledger.gemini_cost == 0
    assert ledger.prompt_tokens == 0
    assert ledger.context_tokens == 0


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
def test_fractional_cost_aggregates_before_one_credit_rounding() -> None:
    ledger = call.UsageLedger()
    ledger.gemini_cost = Decimal("0.0003")
    assert call._credits_for(ledger.cost) == 1
    ledger.gemini_cost += Decimal("0.0003")
    # Each packet would round to one credit, but cumulative spend is 0.72.
    assert call._credits_for(ledger.cost) == 1
    ledger.video_cost = Decimal("0.0003")
    assert call._credits_for(ledger.cost) == 2


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
def test_video_rate_switches_at_promo_boundary() -> None:
    assert call._video_rate(datetime(2026, 10, 15, 23, 59, tzinfo=timezone.utc)) == Decimal("0.015")
    assert call._video_rate(datetime(2026, 10, 16, tzinfo=timezone.utc)) == Decimal("0.025")
    assert call._credits_for(call.VIDEO_RESERVE_SECONDS * Decimal("0.015")) == 103


# contract-test: supporting surface=gui.web assertions=video-call.experiment.generated-visuals
def test_gemini_setup_has_only_nonblocking_visual_tool_and_context_limit() -> None:
    setup = call._gemini_setup()["setup"]
    instruction = setup["systemInstruction"]["parts"][0]["text"]
    tools = setup["tools"][0]["functionDeclarations"]
    assert "show me how black holes work" in instruction
    assert "need not say 'video'" in instruction
    assert [tool["name"] for tool in tools] == ["generate_visual_clip"]
    assert tools[0]["behavior"] == "NON_BLOCKING"
    assert setup["contextWindowCompression"] == {"triggerTokens": 8000, "slidingWindow": {"targetTokens": 4000}}
    assert setup["generationConfig"]["responseModalities"] == ["AUDIO"]


# contract-test: supporting surface=gui.web assertions=video-call.experiment.privacy
def test_fal_result_urls_are_restricted_to_its_cdn() -> None:
    assert h3_turbo._validated_media_url("https://v3b.fal.media/files/x/clip.mp4")
    for url in (
        "http://v3b.fal.media/files/x/clip.mp4",
        "https://v3b.fal.media.evil.test/files/x/clip.mp4",
        "https://127.0.0.1/clip.mp4",
        "https://user@v3b.fal.media/clip.mp4",
    ):
        with pytest.raises(ValueError):
            h3_turbo._validated_media_url(url)


# contract-test: supporting surface=gui.web assertions=video-call.experiment.privacy
def test_fal_queue_urls_allow_stripped_endpoint_but_not_another_job() -> None:
    assert h3_turbo._validated_queue_url(
        "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1/status",
        request_id="clip-1", suffix="/status",
    )
    for url in (
        "https://evil.test/minimax/h3-max-turbo/requests/clip-1/status",
        "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-2/status",
    ):
        with pytest.raises(ValueError):
            h3_turbo._validated_queue_url(url, request_id="clip-1", suffix="/status")


# contract-test: supporting surface=gui.web assertions=video-call.experiment.generated-visuals
@pytest.mark.asyncio
async def test_fal_submission_omits_optional_first_frame_and_fixes_model_settings() -> None:
    class FakeClient:
        async def post(self, url, *, json, headers):
            assert url == h3_turbo.QUEUE_URL
            assert json == {
                "prompt": "A forest at dusk",
                "duration": 5,
                "resolution": "480P",
                "prompt_expansion_mode": "disabled",
                "enable_safety_checker": True,
            }
            assert headers["Authorization"].startswith("Key ")
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "request_id": "clip-1",
                    "status_url": f"{h3_turbo.QUEUE_URL}/requests/clip-1/status",
                    "response_url": f"{h3_turbo.QUEUE_URL}/requests/clip-1",
                    "cancel_url": f"{h3_turbo.QUEUE_URL}/requests/clip-1/cancel",
                },
            )

    job = await h3_turbo.submit_clip(FakeClient(), key="test-key", prompt="A forest at dusk", image_jpeg=None)
    assert job.request_id == "clip-1"


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
@pytest.mark.asyncio
async def test_completed_fal_job_is_billable_when_cdn_download_fails() -> None:
    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self.data

    class FakeClient:
        async def get(self, url, *, headers):
            if url.endswith("/status"):
                return FakeResponse({"status": "COMPLETED"})
            return FakeResponse({"video": {"url": "https://v3b.fal.media/files/clip.mp4", "duration": 5.4}})

        def stream(self, *args, **kwargs):
            raise RuntimeError("CDN unavailable")

    job = h3_turbo.FalJob(
        "clip-1",
        "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1/status",
        "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1",
        "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1/cancel",
    )
    with pytest.raises(h3_turbo.FalCompletedMediaError) as error:
        await h3_turbo.await_clip(FakeClient(), key="test-key", job=job)
    assert error.value.reported_duration == 5.4
    assert error.value.request_id == "clip-1"


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
@pytest.mark.asyncio
async def test_completed_fal_job_deadline_bills_known_work_even_if_cdn_trickles(monkeypatch) -> None:
    monkeypatch.setattr(h3_turbo, "JOB_LIMIT_SECONDS", 0.02)

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self.data

    class TricklingDownload:
        headers = {"content-type": "video/mp4"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            while True:
                await asyncio.sleep(0.01)
                yield b"x"

    class FakeClient:
        async def get(self, url, *, headers):
            if url.endswith("/status"):
                return FakeResponse({"status": "COMPLETED"})
            return FakeResponse({"video": {"url": "https://v3b.fal.media/files/clip.mp4", "duration": 5.4}})

        def stream(self, *args, **kwargs):
            return TricklingDownload()

    job = h3_turbo.FalJob("clip-1", "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1/status", "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1", "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1/cancel")
    with pytest.raises(h3_turbo.FalCompletedMediaError) as error:
        await h3_turbo.await_clip(FakeClient(), key="test-key", job=job)
    assert error.value.reported_duration == 5.4


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
@pytest.mark.asyncio
async def test_fal_result_provider_error_is_not_billed_as_completed_media() -> None:
    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self.data

    class FakeClient:
        async def get(self, url, *, headers):
            if url.endswith("/status"):
                return FakeResponse({"status": "COMPLETED"})
            return FakeResponse({"error": "generation failed", "error_type": "provider_error"})

    job = h3_turbo.FalJob("clip-1", "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1/status", "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1", "https://queue.fal.run/minimax/h3-max-turbo/requests/clip-1/cancel")
    with pytest.raises(h3_turbo.FalProviderFailed):
        await h3_turbo.await_clip(FakeClient(), key="test-key", job=job)


# contract-test: supporting surface=gui.web assertions=video-call.experiment.user-stop
@pytest.mark.asyncio
async def test_request_cancellation_waits_for_accepted_job_settlement() -> None:
    settled = asyncio.Event()

    async def accepted_job() -> None:
        await asyncio.sleep(0.02)
        settled.set()

    job = asyncio.create_task(accepted_job())
    parent = asyncio.create_task(call._finish_accepted_job(job))
    await asyncio.sleep(0)
    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent
    assert settled.is_set()


# contract-test: supporting surface=gui.web assertions=video-call.experiment.billing
@pytest.mark.asyncio
async def test_malformed_last_usage_does_not_drop_earlier_valid_charge(monkeypatch) -> None:
    ledger = call.UsageLedger()
    ledger.gemini_cost = Decimal("0.01")
    ledger.stage_gemini({"totalTokenCount": 1, "promptTokenCount": 1})
    charged = []

    async def fake_charge(websocket, ledger, **kwargs):
        charged.append(ledger.cost)

    monkeypatch.setattr(call, "_charge", fake_charge)
    await call._settle_final_usage(object(), ledger, user_id="user-1", user_hash="hash", call_id="call")
    assert charged == [Decimal("0.01")]


# contract-test: supporting surface=gui.web assertions=video-call.experiment.privacy
@pytest.mark.asyncio
async def test_credit_admission_fails_closed_when_projection_and_fallback_are_missing() -> None:
    class Cache:
        async def get_billing_projection(self, user_id):
            return None

    class Directus:
        async def get_items(self, *args, **kwargs):
            return []

    websocket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        cache_service=Cache(), directus_service=Directus(), encryption_service=object(),
    )))
    with pytest.raises(RuntimeError, match="Billing balance unavailable"):
        await call._authoritative_credits(websocket, "user-1")
