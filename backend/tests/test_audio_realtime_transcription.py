"""Focused contracts for the authenticated realtime audio proxy."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes import audio_realtime


class _FakeWebSocket:
    def __init__(self, *, origin: str = "https://app.dev.openmates.org") -> None:
        self.headers = {"origin": origin}
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                allowed_origins=["https://app.dev.openmates.org"],
                cache_service=object(),
                directus_service=object(),
                encryption_service=object(),
                server_stats_service=object(),
            )
        )


# contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
def test_realtime_audio_proxy_only_accepts_the_first_party_origin() -> None:
    assert audio_realtime._origin_is_allowed(_FakeWebSocket()) is True
    assert (
        audio_realtime._origin_is_allowed(_FakeWebSocket(origin="https://evil.example"))
        is False
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

    assert captured["credits_to_deduct"] == 12
    assert captured["idempotency_key"] == "audio-realtime:provider-request-1"
    assert captured["usage_details"] == {
        "duration_seconds": 61.2,
        "billed_minutes": 2,
        "requests_transcribed": 1,
        "model": audio_realtime.MISTRAL_REALTIME_MODEL,
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
