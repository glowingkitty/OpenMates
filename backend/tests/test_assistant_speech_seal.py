"""Live speech final membership remains authoritative across detached handoffs."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.assistant_speech.streaming import ImmutableSpeechBoundaryTracker
from backend.apps.audio.assistant_speech import persistence


CHAT = "11111111-1111-4111-8111-111111111111"
MESSAGE = "d" * 64
CALL = "a" * 32


@pytest.mark.parametrize("sealed,live,failed", [(True, True, False), (False, True, False), (True, False, False), (False, True, True), (True, True, True), (None, True, True), (None, True, False)])
# contract-test: direct surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.execution.text-stream-independent
async def test_live_membership_is_published_only_after_durable_seal_or_as_explicit_failure(monkeypatch, caplog, sealed, live, failed):
    source = Path(__file__).parents[1] / "apps/ai/tasks/stream_consumer.py"
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_seal_automatic_assistant_speech_manifest")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function], type_ignores=[])
    publish = AsyncMock()
    bill = Mock()
    seal = AsyncMock(return_value=sealed, side_effect=RuntimeError("PRIVATE-SEAL-FAILURE") if sealed is None else None)
    monkeypatch.setattr(persistence, "seal_speech_manifest", seal)
    namespace = {"_publish_to_redis": publish, "celery_config": SimpleNamespace(app=SimpleNamespace(send_task=bill)),
                 "logger": logging.getLogger("speech-seal-producer-test")}
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    segments = [{"segment_id": "b" * 64, "sequence": 0, "kind": "voice_prose_clause", "source_version": 1}]
    metadata = {"chat_id": CHAT, "assistant_message_id": MESSAGE, "source_version": 1,
                "voice_call_id": CALL if live else None, "segments": segments, "handoff_failed": failed}
    cache, directus = object(), object()
    await namespace[function.name](metadata=metadata, directus_service=directus,
                                   voice_profile={"key": "hiro", "version": 1}, cache_service=cache,
                                   redis_channel_name=f"chat_stream::{CHAT}", user_id_hash="e" * 64)
    seal.assert_awaited_once()
    assert bill.called is (sealed is True)
    assert "PRIVATE-SEAL-FAILURE" not in caplog.text
    if live:
        publish.assert_awaited_once()
        envelope = publish.await_args.args[2]
        assert envelope == {"type": "assistant_speech_status", "chat_id": CHAT, "message_id": MESSAGE,
                            "user_id_hash": "e" * 64, "payload": {"status": "sealed", "voice_call_id": CALL,
                            "source_version": 1, "segments": segments,
                            **({"error": "Speech is temporarily unavailable."} if failed or not sealed else {})}}
    else:
        publish.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.execution.text-stream-independent
async def test_seal_membership_waits_for_handoffs_and_contains_no_transient_text():
    handoff = asyncio.Event()
    finalized = []
    dispatched = []

    async def dispatch(segment):
        await handoff.wait()
        dispatched.append(segment)

    async def finalize(metadata):
        assert len(dispatched) == 2
        finalized.append(metadata)

    tracker = ImmutableSpeechBoundaryTracker(
        metadata={"chat_id": CHAT, "assistant_message_id": MESSAGE, "source_version": 1,
                  "voice_call_id": CALL, "voice_mode": True},
        dispatch_speech=dispatch, finalize_speech=finalize,
    )
    tracker.observe("First public sentence. Second public sentence.", is_final=True)
    await asyncio.sleep(0)
    assert not finalized
    handoff.set()
    await tracker.wait_for_handoff()
    assert len(finalized) == 1
    assert finalized[0]["segments"] == [
        {field: segment[field] for field in ("segment_id", "sequence", "kind", "source_version")}
        for segment in dispatched
    ]
    assert len(finalized[0]["segments"]) == 2
    assert "public sentence" not in str(finalized)


# contract-test: direct surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.failure.nonblocking-visible-resumable
async def test_failed_handoff_before_persistence_cannot_be_announced_as_healthy_membership():
    finalized = []

    async def dispatch(_segment):
        raise RuntimeError("PRIVATE-HANDOFF-FAILURE")

    async def finalize(metadata):
        finalized.append(metadata)

    tracker = ImmutableSpeechBoundaryTracker(
        metadata={"chat_id": CHAT, "assistant_message_id": MESSAGE, "source_version": 1,
                  "voice_call_id": CALL, "voice_mode": True},
        dispatch_speech=dispatch, finalize_speech=finalize,
    )
    tracker.observe("A public response whose handoff fails.", is_final=True)
    await tracker.wait_for_handoff()
    assert len(finalized) == 1 and finalized[0]["handoff_failed"] is True
    assert finalized[0]["segments"]
    assert "PRIVATE-HANDOFF-FAILURE" not in str(finalized)
