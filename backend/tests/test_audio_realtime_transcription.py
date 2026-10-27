"""Focused contracts for the authenticated realtime audio proxy."""

import asyncio
import base64
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.apps.audio.pricing import (
    BATCH_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE,
    REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE,
    REALTIME_TRANSCRIPTION_MINIMUM_CREDITS,
    REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER,
    REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE,
    calculate_realtime_transcription_credits,
)
from backend.apps.audio.skills.transcribe_skill import VOXTRAL_MODEL
from backend.core.api.app.routes import audio_realtime


class _FakeWebSocket:
    def __init__(
        self,
        *,
        origin: str = "https://app.dev.openmates.org",
        query_params: dict[str, str] | None = None,
        cache_service: object | None = None,
    ) -> None:
        self.headers = {"origin": origin}
        self.query_params = query_params or {}
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                allowed_origins=["https://app.dev.openmates.org"],
                cache_service=cache_service or object(),
                directus_service=object(),
                encryption_service=object(),
                server_stats_service=object(),
            )
        )


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,message-input.audio.realtime-voxtral3
def test_message_input_realtime_pricing_is_separate_from_batch_skill() -> None:
    assert VOXTRAL_MODEL == "voxtral-mini-2602"
    assert audio_realtime.MISTRAL_REALTIME_MODEL == (
        "voxtral-mini-transcribe-realtime-3-0"
    )
    assert VOXTRAL_MODEL != audio_realtime.MISTRAL_REALTIME_MODEL
    assert BATCH_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE == 3
    assert REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE == Decimal("0.008")
    assert REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER == Decimal("1.20")
    assert REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE == 10
    assert REALTIME_TRANSCRIPTION_MINIMUM_CREDITS == 1


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,message-input.audio.realtime-voxtral3
def test_batch_skill_and_realtime_model_metadata_keep_separate_prices() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    app_config = yaml.safe_load(
        (backend_root / "apps/audio/app.yml").read_text(encoding="utf-8")
    )
    transcribe_skill = next(
        skill for skill in app_config["skills"] if skill["id"] == "transcribe"
    )
    assert transcribe_skill["full_model_reference"] == "mistral/voxtral-mini-2602"
    assert transcribe_skill["pricing"]["per_minute"] == 3

    provider_config = yaml.safe_load(
        (backend_root / "providers/mistral.yml").read_text(encoding="utf-8")
    )
    models = {model["id"]: model for model in provider_config["models"]}
    assert models["voxtral-mini-2602"]["pricing"]["per_minute"] == 3
    assert models["voxtral-mini-transcribe-realtime-3-0"]["pricing"]["per_minute"] == 10


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,message-input.audio.realtime-voxtral3
def test_realtime_audio_proxy_only_accepts_the_first_party_origin() -> None:
    assert audio_realtime._origin_is_allowed(_FakeWebSocket()) is True
    assert (
        audio_realtime._origin_is_allowed(_FakeWebSocket(origin="https://evil.example"))
        is False
    )


# contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
@pytest.mark.asyncio
async def test_realtime_audio_accepts_user_bound_short_lived_token_when_safari_origin_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCache:
        SESSION_KEY_PREFIX = "session:"

        async def get(self, key: str) -> dict[str, str] | None:
            return {"user_id": "user-1"} if key == "session:token-hash" else None

    monkeypatch.setattr(audio_realtime, "verify_ws_token", lambda token: "token-hash")
    websocket = _FakeWebSocket(
        origin="https://safari-origin.example",
        query_params={"token": "signed-token"},
        cache_service=FakeCache(),
    )

    assert await audio_realtime._browser_request_is_allowed(
        websocket, {"user_id": "user-1"}
    )


# contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
@pytest.mark.asyncio
async def test_realtime_audio_rejects_token_bound_to_another_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCache:
        SESSION_KEY_PREFIX = "session:"

        async def get(self, _key: str) -> dict[str, str]:
            return {"user_id": "different-user"}

    monkeypatch.setattr(audio_realtime, "verify_ws_token", lambda token: "token-hash")
    websocket = _FakeWebSocket(
        origin="https://evil.example",
        query_params={"token": "signed-token"},
        cache_service=FakeCache(),
    )

    assert not await audio_realtime._browser_request_is_allowed(
        websocket, {"user_id": "user-1"}
    )


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,message-input.audio.realtime-voxtral3
@pytest.mark.asyncio
async def test_realtime_audio_admission_fails_closed_without_cache() -> None:
    cache = SimpleNamespace(client=asyncio.sleep(0, result=None))
    client, key, token = await audio_realtime._acquire_stream_lock(cache, "user-hash")

    assert client is False
    assert key == "audio:realtime:active:user-hash"
    assert token


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,message-input.audio.realtime-voxtral3
@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_realtime_audio_billing_prorates_seconds_and_rounds_credits_once(
    monkeypatch: pytest.MonkeyPatch,
    interrupted: bool,
) -> None:
    captured: dict[str, object] = {}

    class FakeBillingService:
        async def charge_user_credits(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        audio_realtime,
        "_create_billing_service",
        lambda _websocket: FakeBillingService(),
    )
    await audio_realtime._bill_realtime_usage(
        _FakeWebSocket(),
        user_id="user-1",
        user_id_hash="hashed-user",
        request_id="provider-request-1",
        audio_seconds=61.2,
        chat_id="chat-1",
        interrupted=interrupted,
    )

    assert captured["credits_to_deduct"] == 11
    assert captured["idempotency_key"] == "audio-realtime:provider-request-1"
    assert captured["usage_details"] == {
        "duration_seconds": 61.2,
        "billing_unit": "second",
        "requests_transcribed": 1,
        "model": audio_realtime.MISTRAL_REALTIME_MODEL,
        "provider_cost_usd_per_minute": 0.008,
        "price_markup_percent": 20,
        "credits_per_minute": 10,
        "minimum_credits": 1,
        "usage_type": (
            audio_realtime.INTERRUPTED_REALTIME_USAGE_TYPE
            if interrupted else audio_realtime.REALTIME_USAGE_TYPE
        ),
        "chat_id": "chat-1",
    }


# contract-test: supporting surface=gui.web assertions=message-input.audio.realtime-voxtral3
@pytest.mark.parametrize(
    ("duration", "expected"),
    [(0, 0), (-1, 0), (0.01, 1), (1, 1), (6, 1), (6.0001, 2),
     (10, 2), (59, 10), (60, 10), (60.01, 11), (61.2, 11), (120, 20)],
)
def test_realtime_transcription_prices_measured_seconds(duration: float, expected: int) -> None:
    assert calculate_realtime_transcription_credits(duration_seconds=duration) == expected


# contract-test: supporting surface=gui.web assertions=message-input.audio.realtime-voxtral3
@pytest.mark.parametrize("duration", [float("nan"), float("inf"), float("-inf")])
def test_realtime_transcription_rejects_nonfinite_duration(duration: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        calculate_realtime_transcription_credits(duration_seconds=duration)


# contract-test: supporting surface=gui.web assertions=message-input.audio.realtime-voxtral3
@pytest.mark.asyncio
async def test_realtime_audio_with_no_audio_has_no_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_billing(_websocket: object) -> None:
        pytest.fail("An empty recording must not create a billing service")

    monkeypatch.setattr(audio_realtime, "_create_billing_service", unexpected_billing)
    await audio_realtime._bill_realtime_usage(
        _FakeWebSocket(), user_id="user-1", user_id_hash="hashed-user",
        request_id="empty-request", audio_seconds=0, chat_id=None,
    )


# contract-test: supporting surface=gui.web assertions=message-input.audio.realtime-voxtral3,billing.credits.idempotent-charge
@pytest.mark.integration
def test_authenticated_websocket_settles_ten_seconds_for_two_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the ASGI WebSocket and settlement with a provider-free fixture."""
    charges: list[dict[str, object]] = []

    class Provider:
        def __init__(self) -> None:
            self.ended = asyncio.Event()
            self.handshakes = [
                {"type": "session.created", "session": {"id": "ten-second-request"}},
                {"type": "session.updated"},
            ]

        async def receive_json(self) -> dict[str, object]:
            return self.handshakes.pop(0)

        async def send_json(self, message: dict[str, object]) -> None:
            if message["type"] == "input_audio.end":
                self.ended.set()

        async def receive(self) -> SimpleNamespace:
            await self.ended.wait()
            return SimpleNamespace(
                type=audio_realtime.aiohttp.WSMsgType.TEXT,
                data=json.dumps({"type": "transcription.done", "text": "",
                                 "usage": {"prompt_audio_seconds": 10}}),
            )

    class ProviderContext:
        async def __aenter__(self) -> Provider:
            return Provider()

        async def __aexit__(self, *_args: object) -> None:
            pass

    class ProviderSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "ProviderSession":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        def ws_connect(self, *_args: object, **_kwargs: object) -> ProviderContext:
            return ProviderContext()

    class Billing:
        async def charge_user_credits(self, **kwargs: object) -> None:
            charges.append(kwargs)

    async def authenticate() -> dict[str, object]:
        return {"user_id": "user-1", "user_data": {"credits": 2}}

    async def secret(*_args: object) -> str:
        return "fixture-provider-key"

    app = FastAPI()
    app.include_router(audio_realtime.router)
    app.dependency_overrides[audio_realtime.get_current_user_ws] = authenticate
    app.state.allowed_origins = ["https://app.dev.openmates.org"]
    app.state.cache_service = object()
    app.state.secrets_manager = SimpleNamespace(get_secret=secret)
    monkeypatch.setattr(audio_realtime, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(audio_realtime.aiohttp, "ClientSession", ProviderSession)
    monkeypatch.setattr(audio_realtime, "_create_billing_service", lambda _ws: Billing())
    monkeypatch.setattr(audio_realtime, "_acquire_stream_lock",
                        lambda *_args: asyncio.sleep(0, result=(None, "lock", "token")))
    monkeypatch.setattr(audio_realtime, "_release_stream_lock",
                        lambda *_args: asyncio.sleep(0))
    with TestClient(app) as client:
        with client.websocket_connect(
            "/v1/apps/audio/realtime-transcription",
            headers={"origin": "https://app.dev.openmates.org"},
        ) as websocket:
            assert websocket.receive_json()["type"] == "session.ready"
            # Two five-second chunks stay within the per-chunk input limit.
            for _ in range(2):
                websocket.send_json({"type": "input_audio.append", "audio": base64.b64encode(
                    b"\x00\x01" * (audio_realtime.PCM_SAMPLE_RATE * 5)
                ).decode()})
            websocket.send_json({"type": "input_audio.end"})
            assert websocket.receive_json()["type"] == "transcription.done"
            assert websocket.receive_json()["type"] == "correction.failed"
    assert len(charges) == 1
    assert charges[0]["credits_to_deduct"] == 2
    assert charges[0]["idempotency_key"] == "audio-realtime:ten-second-request"
    assert charges[0]["usage_details"]["duration_seconds"] == 10


# contract-test: supporting surface=gui.web assertions=message-input.audio.realtime-voxtral3
@pytest.mark.asyncio
@pytest.mark.parametrize("credits", [0, 0.5])
async def test_realtime_audio_rejects_balance_below_one_credit(
    monkeypatch: pytest.MonkeyPatch, credits: float,
) -> None:
    closed: list[dict[str, object]] = []

    class BrowserSocket(_FakeWebSocket):
        async def close(self, **kwargs: object) -> None:
            closed.append(kwargs)

    monkeypatch.setattr(audio_realtime, "is_payment_enabled", lambda: True)
    await audio_realtime.realtime_transcription(
        BrowserSocket(), auth_data={"user_id": "user-1", "user_data": {"credits": credits}},
    )
    assert closed == [{"code": 1008, "reason": "Not enough credits"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deltas", "final_text", "expected_transcript"),
    [
        (["Hello ", "world."], "Hello world.", "Hello world."),
        (["Hello "], "Hello world.", "Hello world."),
        (
            ["First keep the budget. ", "Then invite the team. ", "Finally book the room."],
            "Finally book the room.",
            "First keep the budget. Then invite the team. Finally book the room.",
        ),
        (["Earlier speech. ", "Later speech."], "", "Earlier speech. Later speech."),
        (["Earlier speech. ", "Later speech."], None, "Earlier speech. Later speech."),
        (["Repeat this. ", "Repeat this."], "Repeat this.", "Repeat this. Repeat this."),
        ([], "Hello world.", "Hello world."),
        (
            ["Keep the budget below five hundred euros. " * 21, "Finally invite Marta."],
            "Finally invite Marta.",
            "Keep the budget below five hundred euros. " * 21 + "Finally invite Marta.",
        ),
        ([" \n"], "Hello world.", "Hello world."),
    ],
    ids=["full-final", "extended-final", "suffix-final", "empty-final", "missing-final", "repeated-speech", "no-deltas", "incremental-long", "blank-deltas"],
)
# contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript,message-input.embeds.gated-send
@pytest.mark.parametrize("credits", [1, 9, 100])
async def test_realtime_audio_relays_pcm_deltas_and_final_text(
    monkeypatch: pytest.MonkeyPatch,
    deltas: list[str],
    final_text: str | None,
    expected_transcript: str,
    credits: int,
) -> None:
    provider_messages: list[dict[str, object]] = []
    browser_messages: list[dict[str, object]] = []
    billed: dict[str, object] = {}
    released: list[tuple[object, str, str]] = []
    corrected_batches: list[str] = []
    background_corrected = asyncio.Event()
    long_stream = len("".join(deltas)) >= 800

    class FakeProvider:
        def __init__(self) -> None:
            self.handshakes = [
                {"type": "session.created", "session": {"id": "provider-1"}},
                {"type": "session.updated"},
            ]
            self.events = [
                *[{"type": "transcription.text.delta", "text": delta} for delta in deltas],
                {
                    "type": "transcription.done",
                    **({"text": final_text} if final_text is not None else {}),
                    "language": "en",
                    "usage": {"prompt_audio_seconds": 1.25},
                },
            ]
            self.ended = asyncio.Event()

        async def receive_json(self) -> dict[str, object]:
            return self.handshakes.pop(0)

        async def send_json(self, message: dict[str, object]) -> None:
            provider_messages.append(message)
            if message.get("type") == "input_audio.end":
                self.ended.set()

        async def receive(self) -> SimpleNamespace:
            if not long_stream:
                await self.ended.wait()
            elif self.events[0]["type"] == "transcription.done":
                await self.ended.wait()
            event = self.events.pop(0)
            return SimpleNamespace(
                type=audio_realtime.aiohttp.WSMsgType.TEXT,
                data=json.dumps(event),
            )

    provider = FakeProvider()

    class ProviderContext:
        async def __aenter__(self) -> FakeProvider:
            return provider

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def ws_connect(self, *_args: object, **_kwargs: object) -> ProviderContext:
            return ProviderContext()

    class BrowserSocket(_FakeWebSocket):
        def __init__(self) -> None:
            super().__init__()
            self.query_params: dict[str, str] = {}
            self.inputs = [
                json.dumps(
                    {
                        "type": "input_audio.append",
                        "audio": base64.b64encode(b"\x00\x01" * 800).decode(),
                    }
                ),
                json.dumps({"type": "input_audio.end"}),
            ]
            self.app.state.secrets_manager = SimpleNamespace(
                get_secret=self._get_secret
            )

        async def _get_secret(self, *_args: object) -> str:
            return "test-provider-key"

        async def accept(self) -> None:
            return None

        async def receive_text(self) -> str:
            await asyncio.sleep(0)
            if not self.inputs:
                await asyncio.Future()
            if long_stream and json.loads(self.inputs[0])["type"] == "input_audio.end":
                await asyncio.wait_for(background_corrected.wait(), 2)
            return self.inputs.pop(0)

        async def send_json(self, message: dict[str, object]) -> None:
            browser_messages.append(message)
            if message["type"] == "correction.progress" and not provider.ended.is_set():
                background_corrected.set()

    async def fake_correction(
        _websocket: BrowserSocket,
        raw: str,
        language: str | None,
        context: str | None = None,
    ) -> dict[str, str]:
        assert raw in expected_transcript
        assert language in (None, "en")
        assert context is None
        corrected_batches.append(raw)
        return {"title": "Plans", "transcript": raw, "correction_model": "test"}

    class FakeBillingService:
        async def charge_user_credits(self, **kwargs: object) -> None:
            assert not billed, "A completed recording must settle only once"
            billed.update(kwargs)

    async def fake_release(client: object, key: str, token: str) -> None:
        released.append((client, key, token))

    monkeypatch.setattr(audio_realtime.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(
        audio_realtime,
        "_acquire_stream_lock",
        lambda *_args: asyncio.sleep(0, result=(None, "lock", "token")),
    )
    monkeypatch.setattr(audio_realtime, "_release_stream_lock", fake_release)
    monkeypatch.setattr(audio_realtime, "_correct_segment", fake_correction)
    monkeypatch.setattr(audio_realtime, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(audio_realtime, "_create_billing_service", lambda _ws: FakeBillingService())

    socket = BrowserSocket()
    await audio_realtime.realtime_transcription(
        socket,
        auth_data={"user_id": "user-1", "user_data": {"credits": credits}},
    )

    assert [message["type"] for message in provider_messages] == [
        "session.update",
        "input_audio.append",
                "input_audio.end",
    ]
    terminal_events = [message for message in browser_messages if message["type"] != "correction.progress"]
    assert [message["type"] for message in terminal_events] == [
        "session.ready",
        *["transcription.text.delta"] * len(deltas),
        "transcription.done",
        "correction.started",
        "correction.done",
    ]
    assert terminal_events[-3]["transcript"] == expected_transcript
    assert terminal_events[-1]["transcript"] == expected_transcript
    if long_stream:
        assert background_corrected.is_set()
        assert " ".join(corrected_batches) == expected_transcript
        assert all(len(batch) <= 800 for batch in corrected_batches)
        assert len(corrected_batches) > 1
    else:
        assert corrected_batches == [expected_transcript]
    assert [message["text"] for message in browser_messages if message["type"] == "transcription.text.delta"] == deltas
    assert billed["idempotency_key"] == "audio-realtime:provider-1"
    assert billed["credits_to_deduct"] == 1
    assert billed["usage_details"]["duration_seconds"] == 1.25
    assert billed["usage_details"]["billing_unit"] == "second"
    assert released == [(None, "lock", "token")]


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,message-input.recording.lifecycle
@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["cancel", "disconnect"])
async def test_realtime_audio_bills_accepted_audio_when_recording_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    provider_messages: list[dict[str, object]] = []
    billed_calls: list[dict[str, object]] = []
    released: list[tuple[object, str, str]] = []
    audio_bytes = b"\x00\x01" * 800

    class FakeProvider:
        def __init__(self) -> None:
            self.handshakes = [
                {
                    "type": "session.created",
                    "session": {"request_id": "provider-interrupted-1"},
                },
                {"type": "session.updated"},
            ]

        async def receive_json(self) -> dict[str, object]:
            return self.handshakes.pop(0)

        async def send_json(self, message: dict[str, object]) -> None:
            provider_messages.append(message)

        async def receive(self) -> SimpleNamespace:
            await asyncio.Future()
            raise AssertionError("unreachable")

    provider = FakeProvider()

    class ProviderContext:
        async def __aenter__(self) -> FakeProvider:
            return provider

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def ws_connect(self, *_args: object, **_kwargs: object) -> ProviderContext:
            return ProviderContext()

    class BrowserSocket(_FakeWebSocket):
        def __init__(self) -> None:
            super().__init__()
            self.query_params: dict[str, str] = {}
            self.inputs = [
                json.dumps(
                    {
                        "type": "input_audio.append",
                        "audio": base64.b64encode(audio_bytes).decode(),
                    }
                )
            ]
            self.app.state.secrets_manager = SimpleNamespace(
                get_secret=self._get_secret
            )

        async def _get_secret(self, *_args: object) -> str:
            return "test-provider-key"

        async def accept(self) -> None:
            return None

        async def receive_text(self) -> str:
            await asyncio.sleep(0)
            if self.inputs:
                return self.inputs.pop(0)
            if interruption == "cancel":
                return json.dumps({"type": "session.cancel"})
            raise audio_realtime.WebSocketDisconnect()

        async def send_json(self, _message: dict[str, object]) -> None:
            return None

    class FakeBillingService:
        async def charge_user_credits(self, **kwargs: object) -> None:
            billed_calls.append(dict(kwargs))

    async def fake_release(client: object, key: str, token: str) -> None:
        released.append((client, key, token))

    monkeypatch.setattr(audio_realtime.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(
        audio_realtime,
        "_acquire_stream_lock",
        lambda *_args: asyncio.sleep(0, result=(None, "lock", "token")),
    )
    monkeypatch.setattr(audio_realtime, "_release_stream_lock", fake_release)
    monkeypatch.setattr(audio_realtime, "_create_billing_service", lambda _ws: FakeBillingService())

    socket = BrowserSocket()
    await audio_realtime.realtime_transcription(
        socket,
        auth_data={"user_id": "user-1", "user_data": {"credits": 100}},
    )

    assert [message["type"] for message in provider_messages] == [
        "session.update",
        "input_audio.append",
    ]
    assert len(billed_calls) == 1
    assert billed_calls[0]["idempotency_key"] == "audio-realtime:provider-interrupted-1"
    assert billed_calls[0]["credits_to_deduct"] == 1
    assert billed_calls[0]["usage_details"]["duration_seconds"] == (
        len(audio_bytes) / audio_realtime.PCM_BYTES_PER_SECOND
    )
    assert billed_calls[0]["usage_details"]["usage_type"] == audio_realtime.INTERRUPTED_REALTIME_USAGE_TYPE
    assert released == [(None, "lock", "token")]


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,message-input.audio.realtime-voxtral3
@pytest.mark.asyncio
async def test_realtime_correction_failure_keeps_raw_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, object]] = []

    class Socket(_FakeWebSocket):
        async def send_json(self, message: dict[str, object]) -> None:
            sent.append(message)

    socket = Socket()
    socket.app.state.secrets_manager = SimpleNamespace(
        get_secret=lambda *_args: asyncio.sleep(0, result=None)
    )
    await audio_realtime._correct_and_send(socket, "Keep this raw text.", "en")

    assert [message["type"] for message in sent] == [
        "correction.started",
        "correction.failed",
    ]


# contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript
@pytest.mark.asyncio
async def test_realtime_mercury_correction_reports_model_and_sanitizes_text(monkeypatch) -> None:
    sent: list[dict[str, object]] = []

    class Socket(_FakeWebSocket):
        async def send_json(self, message):
            sent.append(message)

    async def corrected(raw, manager, language):
        assert raw == "um grüne boxen unter 50 euro"
        assert language == "de"
        return {"title": "Grüne Boxen", "corrected_transcript": "Grüne Boxen unter 50 Euro.", "model": "mercury-3"}

    monkeypatch.setenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "true")
    monkeypatch.setattr(audio_realtime, "correct_transcript", corrected)
    socket = Socket()
    socket.app.state.secrets_manager = SimpleNamespace()
    await audio_realtime._correct_and_send(socket, "um grüne boxen unter 50 euro", "de")
    assert sent == [
        {"type": "correction.started", "model": "mercury-3"},
        {"type": "correction.done", "title": "Grüne Boxen", "transcript": "Grüne Boxen unter 50 Euro.", "correction_model": "mercury-3"},
    ]


# contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring
@pytest.mark.asyncio
async def test_workflow_voice_uses_raw_transcript_without_correction_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKFLOW_TRANSCRIPT_CORRECTION_ENABLED", raising=False)
    sent: list[dict[str, object]] = []

    class Socket(_FakeWebSocket):
        async def send_json(self, message: dict[str, object]) -> None:
            sent.append(message)

    async def unexpected_secret(*_args: object) -> str:
        raise AssertionError("Workflow raw transcript must not fetch correction secrets")

    socket = Socket()
    socket.app.state.secrets_manager = SimpleNamespace(get_secret=unexpected_secret)
    raw = "Move this to 8, actually no, 8:30 Berlin time."
    await audio_realtime._correct_and_send(socket, raw, "en", "workflow")

    assert sent == [{"type": "correction.skipped", "transcript": raw}]


# contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring
@pytest.mark.asyncio
async def test_workflow_voice_correction_routes_by_language_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKFLOW_TRANSCRIPT_CORRECTION_ENABLED", "true")
    sent: list[dict[str, object]] = []
    requested_secrets: list[str] = []

    class Socket(_FakeWebSocket):
        async def send_json(self, message: dict[str, object]) -> None:
            sent.append(message)

    async def get_secret(path: str, _key: str) -> str:
        requested_secrets.append(path)
        return "test-key"

    async def groq_correct(raw: str, _key: str, language: str | None) -> dict[str, str]:
        assert language == "en"
        assert "actually no" in raw
        return {"corrected_transcript": "Move this workflow to 8:30 Berlin time."}

    async def gemini_correct(
        raw: str, _key: str, language: str | None
    ) -> dict[str, str]:
        assert language == "de"
        return {
            "title": "Move workflow",
            "corrected_transcript": "Move this workflow to 8:30 Berlin time.",
        }

    async def cerebras_correct(
        raw: str, _key: str, language: str | None
    ) -> dict[str, str]:
        assert "actually no" in raw
        return {"corrected_transcript": "Move this workflow to 8:30 Berlin time."}

    socket = Socket()
    socket.app.state.secrets_manager = SimpleNamespace(get_secret=get_secret)
    monkeypatch.setattr(
        audio_realtime, "correct_workflow_transcript_with_groq", groq_correct
    )
    monkeypatch.setattr(
        audio_realtime, "correct_workflow_transcript_with_cerebras", cerebras_correct
    )
    monkeypatch.setattr(
        audio_realtime, "correct_transcript_with_gemini", gemini_correct
    )
    await audio_realtime._correct_and_send(
        socket, "Move this to 8, actually no, 8:30 Berlin time.", "en", "workflow"
    )
    assert sent[-1]["correction_model"] == audio_realtime.GROQ_WORKFLOW_CORRECTION_MODEL
    assert sent[-1]["transcript"] == "Move this workflow to 8:30 Berlin time."
    assert requested_secrets == ["kv/data/providers/groq"]

    sent.clear()
    requested_secrets.clear()
    await audio_realtime._correct_and_send(
        socket, "Move this to 8, actually no, 8:30 Berlin time.", "de", "workflow"
    )
    assert (
        sent[-1]["correction_model"]
        == audio_realtime.CEREBRAS_WORKFLOW_CORRECTION_MODEL
    )
    assert requested_secrets == ["kv/data/providers/cerebras"]

    async def unavailable_groq(*_args: object) -> dict[str, str]:
        raise RuntimeError("Provider unavailable")

    sent.clear()
    requested_secrets.clear()
    monkeypatch.setattr(
        audio_realtime, "correct_workflow_transcript_with_groq", unavailable_groq
    )
    await audio_realtime._correct_and_send(
        socket, "Move this to 8, actually no, 8:30 Berlin time.", "en", "workflow"
    )
    assert (
        sent[-1]["correction_model"]
        == audio_realtime.CEREBRAS_WORKFLOW_CORRECTION_MODEL
    )
    assert requested_secrets == [
        "kv/data/providers/groq",
        "kv/data/providers/cerebras",
    ]

    async def unavailable_cerebras(*_args: object) -> dict[str, str]:
        raise RuntimeError("Provider unavailable")

    sent.clear()
    requested_secrets.clear()
    monkeypatch.setattr(
        audio_realtime,
        "correct_workflow_transcript_with_cerebras",
        unavailable_cerebras,
    )
    await audio_realtime._correct_and_send(
        socket, "Move this to 8, actually no, 8:30 Berlin time.", "de", "workflow"
    )
    assert sent[-1]["correction_model"] == audio_realtime.GEMINI_CORRECTION_MODEL
    assert requested_secrets == [
        "kv/data/providers/cerebras",
        "kv/data/providers/google_ai_studio",
    ]
