"""Focused contracts for the authenticated realtime audio proxy."""

import asyncio
import base64
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from backend.apps.audio.pricing import (
    BATCH_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE,
    REALTIME_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE,
    REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER,
    REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE,
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


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
def test_message_input_realtime_pricing_is_separate_from_batch_skill() -> None:
    assert VOXTRAL_MODEL == "voxtral-mini-2602"
    assert audio_realtime.MISTRAL_REALTIME_MODEL == (
        "voxtral-mini-transcribe-realtime-2602"
    )
    assert VOXTRAL_MODEL != audio_realtime.MISTRAL_REALTIME_MODEL
    assert BATCH_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE == 3
    assert REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE == Decimal("0.006")
    assert REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER == Decimal("1.20")
    assert REALTIME_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE == 8


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
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
    assert (
        models["voxtral-mini-transcribe-realtime-2602"]["pricing"]["per_minute"]
        == 8
    )


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
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


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
@pytest.mark.asyncio
async def test_realtime_audio_admission_fails_closed_without_cache() -> None:
    cache = SimpleNamespace(client=asyncio.sleep(0, result=None))
    client, key, token = await audio_realtime._acquire_stream_lock(cache, "user-hash")

    assert client is False
    assert key == "audio:realtime:active:user-hash"
    assert token


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
@pytest.mark.asyncio
async def test_realtime_audio_billing_rounds_started_minutes_once(
    monkeypatch: pytest.MonkeyPatch,
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
    )

    assert captured["credits_to_deduct"] == 16
    assert captured["idempotency_key"] == "audio-realtime:provider-request-1"
    assert captured["usage_details"] == {
        "duration_seconds": 61.2,
        "billed_minutes": 2,
        "requests_transcribed": 1,
        "model": audio_realtime.MISTRAL_REALTIME_MODEL,
        "provider_cost_usd_per_minute": 0.006,
        "price_markup_percent": 20,
        "credits_per_started_minute": 8,
        "chat_id": "chat-1",
    }


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
@pytest.mark.asyncio
async def test_realtime_audio_relays_pcm_deltas_and_final_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_messages: list[dict[str, object]] = []
    browser_messages: list[dict[str, object]] = []
    billed: dict[str, object] = {}
    released: list[tuple[object, str, str]] = []

    class FakeProvider:
        def __init__(self) -> None:
            self.handshakes = [
                {"type": "session.created", "session": {"id": "provider-1"}},
                {"type": "session.updated"},
            ]
            self.events = [
                {"type": "transcription.text.delta", "text": "Hello "},
                {
                    "type": "transcription.done",
                    "text": "Hello world.",
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
            await self.ended.wait()
            return SimpleNamespace(
                type=audio_realtime.aiohttp.WSMsgType.TEXT,
                data=json.dumps(self.events.pop(0)),
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
            return self.inputs.pop(0)

        async def send_json(self, message: dict[str, object]) -> None:
            browser_messages.append(message)

    async def fake_correction(
        websocket: BrowserSocket, raw: str, language: str | None
    ) -> None:
        assert raw == "Hello world."
        assert language == "en"
        await websocket.send_json(
            {"type": "correction.done", "transcript": "Hello world."}
        )

    async def fake_billing(_websocket: BrowserSocket, **kwargs: object) -> None:
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
    monkeypatch.setattr(audio_realtime, "_correct_and_send", fake_correction)
    monkeypatch.setattr(audio_realtime, "_bill_realtime_usage", fake_billing)

    socket = BrowserSocket()
    await audio_realtime.realtime_transcription(
        socket,
        auth_data={"user_id": "user-1", "user_data": {"credits": 100}},
    )

    assert [message["type"] for message in provider_messages] == [
        "session.update",
        "input_audio.append",
        "input_audio.flush",
        "input_audio.end",
    ]
    assert [message["type"] for message in browser_messages] == [
        "session.ready",
        "transcription.text.delta",
        "transcription.done",
        "correction.done",
    ]
    assert billed["request_id"] == "provider-1"
    assert billed["audio_seconds"] == 1.25
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

    async def fake_billing(_websocket: BrowserSocket, **kwargs: object) -> None:
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
    monkeypatch.setattr(audio_realtime, "_bill_realtime_usage", fake_billing)

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
    assert billed_calls[0]["request_id"] == "provider-interrupted-1"
    assert billed_calls[0]["audio_seconds"] == (
        len(audio_bytes) / audio_realtime.PCM_BYTES_PER_SECOND
    )
    assert released == [(None, "lock", "token")]


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
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
