"""Report Issue dictation is free for signed-in users but bounded per recording and per day."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.routes import audio_realtime
from backend.core.api.app.services import report_issue_dictation_quota as quota_module
from backend.core.api.app.services.report_issue_dictation_quota import (
    REPORT_DICTATION_DAILY_SECONDS,
    REPORT_DICTATION_MAX_RECORDING_SECONDS,
    ReportDictationDenied,
    ReportDictationQuota,
)

FIVE_SECONDS_PCM = base64.b64encode(b"\x00\x01" * (audio_realtime.PCM_SAMPLE_RATE * 5)).decode()


class Redis:
    def __init__(self) -> None:
        self.rows: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def get(self, key: str):
        value = self.rows.get(key)
        return None if value is None else str(value).encode()

    async def incrby(self, key: str, amount: int) -> int:
        self.rows[key] = self.rows.get(key, 0) + amount
        return self.rows[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds


class Cache:
    def __init__(self, redis: Redis | None) -> None:
        self.redis = redis

    @property
    async def client(self):
        return self.redis


# contract-test: supporting surface=gui.web assertions=issue-reporting.form.free-limited-dictation
@pytest.mark.asyncio
async def test_quota_reserves_whole_seconds_once_per_stream() -> None:
    redis = Redis()
    quota = ReportDictationQuota(Cache(redis), "user-hash")
    await quota.admit()
    await quota.reserve(4.2)
    await quota.reserve(4.9)  # still within the 5 reserved seconds
    await quota.reserve(10.0)
    assert redis.rows[quota.key] == 10
    assert redis.expiries[quota.key] > 24 * 60 * 60
    status = await quota.status()
    assert status["remaining_seconds"] == REPORT_DICTATION_DAILY_SECONDS - 10
    assert status["max_recording_seconds"] == REPORT_DICTATION_MAX_RECORDING_SECONDS


# contract-test: supporting surface=gui.web assertions=issue-reporting.form.free-limited-dictation
@pytest.mark.asyncio
async def test_quota_refuses_recordings_longer_than_two_minutes() -> None:
    quota = ReportDictationQuota(Cache(Redis()), "user-hash")
    with pytest.raises(ReportDictationDenied) as denied:
        await quota.reserve(REPORT_DICTATION_MAX_RECORDING_SECONDS + 0.5)
    assert denied.value.code == "recording_limit"


# contract-test: supporting surface=gui.web assertions=issue-reporting.form.free-limited-dictation
@pytest.mark.asyncio
async def test_quota_refuses_once_the_daily_budget_is_spent() -> None:
    redis = Redis()
    quota = ReportDictationQuota(Cache(redis), "user-hash")
    redis.rows[quota.key] = REPORT_DICTATION_DAILY_SECONDS - 3
    with pytest.raises(ReportDictationDenied) as denied:
        await quota.reserve(5)
    assert denied.value.code == "daily_limit"
    with pytest.raises(ReportDictationDenied):
        await ReportDictationQuota(Cache(redis), "user-hash").admit()
    assert (await quota.status())["remaining_seconds"] == 0


# contract-test: supporting surface=gui.web assertions=issue-reporting.form.free-limited-dictation
@pytest.mark.asyncio
async def test_quota_fails_closed_without_redis() -> None:
    with pytest.raises(ReportDictationDenied) as denied:
        await ReportDictationQuota(Cache(None), "user-hash").admit()
    assert denied.value.code == "quota_unavailable"


def _app(monkeypatch: pytest.MonkeyPatch, redis: Redis, charges: list) -> FastAPI:
    class Provider:
        def __init__(self) -> None:
            self.ended = asyncio.Event()
            self.handshakes = [
                {"type": "session.created", "session": {"id": "report-request"}},
                {"type": "session.updated"},
            ]

        async def receive_json(self):
            return self.handshakes.pop(0)

        async def send_json(self, message):
            if message["type"] == "input_audio.end":
                self.ended.set()

        async def receive(self):
            await self.ended.wait()
            return SimpleNamespace(
                type=audio_realtime.aiohttp.WSMsgType.TEXT,
                data=json.dumps({"type": "transcription.done", "text": "",
                                 "usage": {"prompt_audio_seconds": 10}}),
            )

    class ProviderContext:
        async def __aenter__(self):
            return Provider()

        async def __aexit__(self, *_args):
            pass

    class ProviderSession:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        def ws_connect(self, *_args, **_kwargs):
            return ProviderContext()

    class Billing:
        async def charge_user_credits(self, **kwargs):
            charges.append(kwargs)

    async def authenticate():
        # Zero credits: report dictation must not depend on the account balance.
        return {"user_id": "user-1", "user_data": {"credits": 0}}

    async def secret(*_args):
        return "fixture-provider-key"

    app = FastAPI()
    app.include_router(audio_realtime.router)
    app.dependency_overrides[audio_realtime._optional_transcription_actor] = authenticate
    app.state.allowed_origins = ["https://app.dev.openmates.org"]
    app.state.cache_service = Cache(redis)
    app.state.secrets_manager = SimpleNamespace(get_secret=secret)
    monkeypatch.setattr(audio_realtime, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(audio_realtime.aiohttp, "ClientSession", ProviderSession)
    monkeypatch.setattr(audio_realtime, "_create_billing_service", lambda _ws: Billing())
    monkeypatch.setattr(audio_realtime, "_acquire_stream_lock",
                        lambda *_args: asyncio.sleep(0, result=(None, "lock", "token")))
    monkeypatch.setattr(audio_realtime, "_release_stream_lock", lambda *_args: asyncio.sleep(0))
    return app


URL = "/v1/apps/audio/realtime-transcription?purpose=report_issue"
ORIGIN = {"origin": "https://app.dev.openmates.org"}


# contract-test: direct surface=gui.web assertions=issue-reporting.form.free-limited-dictation
def test_report_dictation_is_free_and_counts_against_the_daily_budget(monkeypatch) -> None:
    redis, charges = Redis(), []
    with TestClient(_app(monkeypatch, redis, charges)) as client:
        with client.websocket_connect(URL, headers=ORIGIN) as websocket:
            assert websocket.receive_json()["type"] == "session.ready"
            for _ in range(2):
                websocket.send_json({"type": "input_audio.append", "audio": FIVE_SECONDS_PCM})
            websocket.send_json({"type": "input_audio.end"})
            assert websocket.receive_json()["type"] == "transcription.done"
    assert charges == []
    assert list(redis.rows.values()) == [10]


# contract-test: direct surface=gui.web assertions=issue-reporting.form.free-limited-dictation
def test_report_dictation_refuses_when_the_daily_budget_is_spent(monkeypatch) -> None:
    redis, charges = Redis(), []
    key = ReportDictationQuota(Cache(redis), audio_realtime.hashlib.sha256(b"user-1").hexdigest()).key
    redis.rows[key] = REPORT_DICTATION_DAILY_SECONDS
    with TestClient(_app(monkeypatch, redis, charges)) as client:
        with client.websocket_connect(URL, headers=ORIGIN) as websocket:
            error = websocket.receive_json()
    assert error == {"type": "session.error", "code": "daily_limit",
                     "message": "Daily report dictation limit reached. Try again tomorrow."}
    assert charges == []


# contract-test: direct surface=gui.web assertions=issue-reporting.form.free-limited-dictation
def test_report_dictation_stops_audio_beyond_two_minutes(monkeypatch) -> None:
    redis, charges = Redis(), []
    with TestClient(_app(monkeypatch, redis, charges)) as client:
        with client.websocket_connect(URL, headers=ORIGIN) as websocket:
            assert websocket.receive_json()["type"] == "session.ready"
            for _ in range(REPORT_DICTATION_MAX_RECORDING_SECONDS // 5 + 1):
                websocket.send_json({"type": "input_audio.append", "audio": FIVE_SECONDS_PCM})
            error = websocket.receive_json()
    assert error["type"] == "session.error"
    assert error["code"] == "recording_limit"
    assert charges == []
    assert list(redis.rows.values()) == [REPORT_DICTATION_MAX_RECORDING_SECONDS]


# contract-test: supporting surface=gui.web assertions=issue-reporting.form.free-limited-dictation
def test_quota_day_key_rolls_over_at_utc_midnight() -> None:
    import datetime

    late = datetime.datetime(2026, 11, 3, 23, 59, 30, tzinfo=datetime.timezone.utc)
    assert quota_module._utc_day(late) == "2026-11-03"
    assert quota_module._seconds_until_next_utc_day(late) == 30
