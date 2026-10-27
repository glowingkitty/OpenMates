"""Audio-bearing exception messages must never reach Redis/WebSocket logs."""

import asyncio
import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from starlette.websockets import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager

PRIVATE_AUDIO = "cHJpdmF0ZS1hdWRpby1jYW5hcnktNzkxMw=="
PRIVATE_CREDENTIAL = "credential-canary-password-7913"
SECRET_EXCEPTION = f"redis/websocket raw body {PRIVATE_AUDIO} {PRIVATE_CREDENTIAL}"
AUDIO_EVENT = {"type": "assistant_speech_audio", "payload": {"audio_data": PRIVATE_AUDIO}}


@pytest.fixture
def capture_transport_logs(caplog, monkeypatch):
    """Capture at the actual loggers even after Celery disables propagation."""
    attached = []

    def attach(logger):
        if logger in attached:
            return
        logger.addHandler(caplog.handler)
        # Avoid capturing the same record again through a root handler when
        # these tests run without the application's Celery logging setup.
        monkeypatch.setattr(logger, "propagate", False)
        attached.append(logger)

    attach(importlib.import_module(ConnectionManager.__module__).logger)
    try:
        yield attach
    finally:
        for logger in attached:
            logger.removeHandler(caplog.handler)


@pytest.fixture
def cache_module(monkeypatch, capture_transport_logs):
    """Load real cache code with only the optional Redis import boundary stubbed.

    No Redis dependency or server is installed for these isolated engineering
    tests. Every publish/subscription implementation under test is unmodified.
    """
    try:
        importlib.import_module("redis.asyncio")
    except ImportError:
        class RedisConnectionError(Exception):
            pass

        redis = ModuleType("redis")
        redis.__path__ = []
        redis.exceptions = SimpleNamespace(ConnectionError=RedisConnectionError)
        redis_asyncio = ModuleType("redis.asyncio")
        redis_asyncio.Redis = object
        redis.asyncio = redis_asyncio
        monkeypatch.setitem(sys.modules, "redis", redis)
        monkeypatch.setitem(sys.modules, "redis.asyncio", redis_asyncio)
    name = "backend.core.api.app.services._speech_audio_redaction_test_cache"
    source = Path(__file__).parents[1] / "core/api/app/services/cache_base.py"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    capture_transport_logs(module.logger)
    return module


def assert_private_exception_absent(caplog, *, exception_type, category):
    assert PRIVATE_AUDIO not in caplog.text
    assert PRIVATE_CREDENTIAL not in caplog.text
    for record in caplog.records:
        raw = repr(vars(record))
        assert PRIVATE_AUDIO not in raw
        assert PRIVATE_CREDENTIAL not in raw
    records = [record for record in caplog.records if category in record.getMessage()]
    assert records, "Fixed failure category must remain diagnosable"
    assert any(exception_type in record.getMessage() for record in records)
    assert all(record.exc_info is None and record.exc_text is None for record in records)


def cache_with_client(module, client):
    class TestCache(module.CacheServiceBase):
        def __init__(self):
            self._client = client
            self._connection_error = False

        @property
        async def client(self):
            return client

    return TestCache()


# contract-test: supporting surface=rest_api assertions=video-call.privacy
async def test_audio_publish_exception_is_redacted_and_still_returns_false(cache_module, caplog):
    class Redis:
        async def publish(self, *_args):
            raise ValueError(SECRET_EXCEPTION)

    caplog.set_level(logging.DEBUG, logger=cache_module.logger.name)
    cache = cache_with_client(cache_module, Redis())
    assert await cache.publish_event("chat_stream::owned-chat", AUDIO_EVENT) is False
    assert_private_exception_absent(caplog, exception_type="ValueError", category="transient_speech_audio")


@pytest.mark.parametrize("failure", ["json", "connection", "listener", "close"])
# contract-test: supporting surface=rest_api assertions=video-call.privacy,video-call.lifecycle.recovery-and-billing
async def test_chat_stream_subscription_redacts_every_exception_path(cache_module, caplog, monkeypatch, failure):
    class StopListening(Exception):
        pass

    async def stop_reconnect(_delay):
        raise StopListening()

    # Replace only this isolated module's asyncio reference; never mutate the
    # process-wide event loop/sleep used by pytest or connection cleanup.
    monkeypatch.setattr(cache_module, "asyncio", SimpleNamespace(
        sleep=stop_reconnect, CancelledError=asyncio.CancelledError,
    ))

    class PubSub:
        unsubscribed = False
        closed = False

        async def psubscribe(self, _pattern):
            pass

        async def get_message(self, **_kwargs):
            if failure == "connection":
                raise cache_module.redis_exceptions.ConnectionError(SECRET_EXCEPTION)
            if failure == "listener":
                raise ValueError(SECRET_EXCEPTION)
            return {"type": "pmessage", "channel": b"chat_stream::owned-chat",
                    "data": json.dumps(AUDIO_EVENT).encode()}

        async def punsubscribe(self, _pattern):
            self.unsubscribed = True

        async def close(self):
            self.closed = True
            if failure == "close":
                raise ValueError(SECRET_EXCEPTION)

    if failure == "json":
        def malicious_parse(_data):
            raise json.JSONDecodeError(SECRET_EXCEPTION, "private body", 0)

        monkeypatch.setattr(cache_module, "json", SimpleNamespace(
            loads=malicious_parse, dumps=json.dumps, JSONDecodeError=json.JSONDecodeError,
        ))
    pubsub = PubSub()
    cache = cache_with_client(cache_module, SimpleNamespace(pubsub=lambda: pubsub))
    caplog.set_level(logging.DEBUG, logger=cache_module.logger.name)
    messages = cache.subscribe_to_channel("chat_stream::*")
    try:
        if failure in ("connection", "listener"):
            with pytest.raises(StopListening):
                await anext(messages)
        else:
            result = await anext(messages)
            assert result.get("error") == ("json_decode_error" if failure == "json" else None)
    finally:
        await messages.aclose()
    assert pubsub.unsubscribed and pubsub.closed
    if failure == "connection":
        assert cache._client is None and cache._connection_error is True
    error_type = "JSONDecodeError" if failure == "json" else (
        cache_module.redis_exceptions.ConnectionError.__name__ if failure == "connection" else "ValueError"
    )
    assert_private_exception_absent(caplog, exception_type=error_type, category=f"chat_stream_{failure}")


@pytest.mark.parametrize("closed_race", [False, True])
# contract-test: supporting surface=rest_api assertions=video-call.privacy,auth.session.lifecycle
async def test_audio_send_failure_redacts_body_and_preserves_disconnect_cleanup(caplog, closed_race, capture_transport_logs):
    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        if message["type"] == "websocket.send":
            if closed_race:
                raise RuntimeError(f"Unexpected ASGI message {SECRET_EXCEPTION}")
            raise ValueError(SECRET_EXCEPTION)

    manager = ConnectionManager()
    websocket = WebSocket({"type": "websocket"}, receive, send)
    await manager.connect(websocket, "owner", "device")
    caplog.set_level(logging.DEBUG, logger="backend.core.api.app.routes.connection_manager")
    caplog.clear()
    try:
        assert await manager.send_personal_message(AUDIO_EVENT, "owner", "device") is False
        assert ("owner", "device") in manager.grace_period_tasks
        assert id(websocket) not in manager.volatile_session_nonce_by_ws
        assert_private_exception_absent(caplog, exception_type="RuntimeError" if closed_race else "ValueError",
                                        category="transient_speech_audio")
        records = [record for record in caplog.records if "transient_speech_audio" in record.getMessage()]
        assert records[0].levelno == (logging.DEBUG if closed_race else logging.ERROR)
    finally:
        tasks = list(manager.grace_period_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# contract-test: supporting surface=rest_api assertions=assistant-speech.privacy.transient-plaintext-encrypted-audio
async def test_non_audio_publish_keeps_existing_exception_diagnostics(cache_module, caplog):
    class Redis:
        async def publish(self, *_args):
            raise ValueError("ordinary diagnostic")

    caplog.set_level(logging.DEBUG, logger=cache_module.logger.name)
    cache = cache_with_client(cache_module, Redis())
    assert await cache.publish_event("ordinary-channel", {"type": "ordinary"}) is False
    assert "ordinary diagnostic" in caplog.text
    assert "transient_speech_audio" not in caplog.text
