# backend/tests/test_assistant_speech_streaming.py
#
# Contract coverage for scheduling immutable speech alongside authoritative text.
# Speech work may run concurrently, but it cannot delay, mutate, or truncate
# cumulative assistant text events or final text persistence.
#

import asyncio
import hashlib
import inspect

from backend.apps.ai.assistant_speech.streaming import (
    MAX_AUTOMATIC_PARAGRAPH_LENGTH,
    ImmutableSpeechBoundaryTracker,
    stream_text_with_speech_dispatch,
)
from backend.apps.ai.tasks import stream_consumer


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.text-stream-independent,assistant-speech.execution.first-segment-progressive
def test_dispatches_an_immutable_segment_without_waiting_for_later_text() -> None:
    dispatched: list[dict[str, object]] = []

    async def text_events():
        yield {"type": "text", "content": "First paragraph.\n\n"}
        yield {"type": "text", "content": "First paragraph.\n\nSecond paragraph."}
        yield {"type": "final", "content": "First paragraph.\n\nSecond paragraph."}

    async def dispatch(segment: dict[str, object]) -> None:
        dispatched.append(segment)

    async def exercise() -> list[dict[str, object]]:
        return [
            event
            async for event in stream_text_with_speech_dispatch(text_events(), dispatch_speech=dispatch)
        ]

    events = asyncio.run(exercise())

    assert [event["content"] for event in events if "content" in event] == [
        "First paragraph.\n\n",
        "First paragraph.\n\nSecond paragraph.",
        "First paragraph.\n\nSecond paragraph.",
    ]
    assert dispatched == [
        {"sequence": 0, "kind": "prose_paragraph", "speakable_text": "First paragraph."}
    ]


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.text-stream-independent,assistant-speech.failure.nonblocking-visible-resumable
def test_speech_dispatch_failure_is_published_without_failing_text_stream() -> None:
    async def text_events():
        yield {"type": "text", "content": "Only paragraph."}
        yield {"type": "final", "content": "Only paragraph."}

    async def failed_dispatch(_segment: dict[str, object]) -> None:
        raise RuntimeError("provider unavailable")

    async def exercise() -> list[dict[str, object]]:
        return [
            event
            async for event in stream_text_with_speech_dispatch(text_events(), dispatch_speech=failed_dispatch)
        ]

    events = asyncio.run(exercise())

    assert events[-1] == {"type": "final", "content": "Only paragraph."}
    assert {
        "type": "assistant_speech_status",
        "status": "error",
        "sequence": 0,
        "error": "Speech is temporarily unavailable.",
    } in events


# contract-test: direct surface=rest_api assertions=assistant-speech.segmentation.immutable-source,assistant-speech.execution.text-stream-independent
def test_tracker_dispatches_each_cumulative_boundary_once_and_flushes_final_remainder() -> None:
    dispatched: list[dict[str, object]] = []

    async def dispatch(segment: dict[str, object]) -> None:
        dispatched.append(segment)

    async def exercise() -> None:
        tracker = ImmutableSpeechBoundaryTracker(
            metadata={
                "chat_id": "chat-1",
                "assistant_message_id": "assistant-1",
                "source_version": 4,
                "selected_mate_id": "george",
                "language": "en",
            },
            dispatch_speech=dispatch,
        )
        assert tracker.has_new_boundary("First paragraph.\n\n") is True
        tracker.observe("First paragraph.\n\n")
        assert tracker.has_new_boundary("First paragraph.\n\n") is False
        tracker.observe("First paragraph.\n\n")
        tracker.observe("First paragraph.\n\nSecond paragraph.")
        tracker.observe("First paragraph.\n\nSecond paragraph.", is_final=True)
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert [(segment["sequence"], segment["speakable_text"]) for segment in dispatched] == [
        (0, "First paragraph."),
        (1, "Second paragraph."),
    ]
    assert all(segment["source_version"] == 4 for segment in dispatched)
    assert all(segment["selected_mate_id"] == "george" for segment in dispatched)


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.app-skill-progressive,assistant-speech.execution.first-segment-progressive
def test_tracker_dispatches_passive_app_use_before_offset_response_paragraphs() -> None:
    dispatched: list[dict[str, object]] = []

    async def dispatch(segment: dict[str, object]) -> None:
        dispatched.append(segment)

    async def exercise() -> None:
        tracker = ImmutableSpeechBoundaryTracker(
            metadata={"chat_id": "chat-1", "assistant_message_id": "assistant-1", "source_version": 1},
            dispatch_speech=dispatch,
            sequence_offset=1,
        )
        tracker.dispatch_projected_segment(
            sequence=0,
            kind="app_use_announcement",
            speakable_text="I will use the Weather app to fulfill your request. One second.",
        )
        tracker.observe("Forecast paragraph.", is_final=True)
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert [(segment["sequence"], segment["kind"]) for segment in dispatched] == [
        (0, "app_use_announcement"),
        (1, "prose_paragraph"),
    ]


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.text-stream-independent
def test_stream_consumer_publishes_visible_text_before_speech_observation() -> None:
    source = inspect.getsource(stream_consumer._consume_main_processing_stream)
    publish_index = source.index("await content_publisher.publish(payload, log_message)")
    boundary_index = source.index("speech_tracker.has_new_boundary(speech_snapshot)", publish_index)
    first_flush_index = source.index("await content_publisher.flush()", boundary_index)
    observe_index = source.index("speech_tracker.observe(speech_snapshot)", first_flush_index)

    assert publish_index < boundary_index < first_flush_index < observe_index


# contract-test: direct surface=rest_api assertions=assistant-speech.segmentation.immutable-source,assistant-speech.execution.text-stream-independent
def test_tracker_invalidates_rewritten_frozen_source_before_dispatching_replacement() -> None:
    dispatched: list[dict[str, object]] = []
    invalidated: list[dict[str, object]] = []

    async def dispatch(segment: dict[str, object]) -> None:
        dispatched.append(segment)

    async def invalidate(segment: dict[str, object]) -> None:
        invalidated.append(segment)

    async def exercise() -> None:
        tracker = ImmutableSpeechBoundaryTracker(
            metadata={"chat_id": "chat-1", "assistant_message_id": "assistant-1", "source_version": 4},
            dispatch_speech=dispatch,
            invalidate_speech=invalidate,
        )
        tracker.observe("Original paragraph.\n\n")
        tracker.observe("Rewritten paragraph.\n\n", is_final=True)
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert [segment["speakable_text"] for segment in invalidated] == ["Original paragraph."]
    assert [segment["speakable_text"] for segment in dispatched] == [
        "Original paragraph.",
        "Rewritten paragraph.",
    ]


# contract-test: direct surface=rest_api assertions=assistant-speech.preference.chat-scoped-default-off,assistant-speech.execution.text-stream-independent
def test_disabled_tracker_does_not_schedule_speech_work() -> None:
    dispatched: list[dict[str, object]] = []

    async def dispatch(segment: dict[str, object]) -> None:
        dispatched.append(segment)

    async def exercise() -> None:
        tracker = ImmutableSpeechBoundaryTracker(
            metadata={"chat_id": "chat-1", "assistant_message_id": "assistant-1", "source_version": 1},
            dispatch_speech=dispatch,
            enabled=False,
        )
        tracker.observe("No speech.\n\n", is_final=True)
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert dispatched == []


# contract-test: direct surface=rest_api assertions=assistant-speech.segmentation.immutable-source
def test_tracker_deterministically_splits_automatic_paragraphs_at_the_safe_bound() -> None:
    dispatched: list[dict[str, object]] = []
    paragraph = ("word " * 500).strip()

    async def dispatch(segment: dict[str, object]) -> None:
        dispatched.append(segment)

    async def exercise() -> None:
        tracker = ImmutableSpeechBoundaryTracker(
            metadata={"chat_id": "chat-1", "assistant_message_id": "assistant-1", "source_version": 1},
            dispatch_speech=dispatch,
        )
        tracker.observe(paragraph, is_final=True)
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert len(dispatched) > 1
    assert all(len(str(segment["speakable_text"])) <= MAX_AUTOMATIC_PARAGRAPH_LENGTH for segment in dispatched)
    assert " ".join(str(segment["speakable_text"]) for segment in dispatched) == paragraph


# contract-test: direct surface=rest_api assertions=assistant-speech.segmentation.immutable-source
def test_tracker_uses_server_secret_hmac_for_source_identity(monkeypatch) -> None:
    from backend.apps.ai.assistant_speech import streaming

    monkeypatch.setattr(streaming, "_speech_source_identity", lambda text: f"hmac:{text}")
    dispatched: list[dict[str, object]] = []

    async def dispatch(segment: dict[str, object]) -> None:
        dispatched.append(segment)

    async def exercise() -> None:
        tracker = ImmutableSpeechBoundaryTracker(
            metadata={"chat_id": "chat-1", "assistant_message_id": "assistant-1", "source_version": 1},
            dispatch_speech=dispatch,
        )
        tracker.observe("Secret paragraph.", is_final=True)
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert dispatched[0]["source_hash"] == "hmac:Secret paragraph."
    assert dispatched[0]["source_hash"] != hashlib.sha256(b"Secret paragraph.").hexdigest()


# contract-test: direct surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
def test_detached_automatic_dispatch_reports_a_content_free_recoverable_status() -> None:
    statuses: list[dict[str, object]] = []

    async def failed_dispatch(_segment: dict[str, object]) -> None:
        raise RuntimeError("private paragraph must not be emitted")

    async def report_status(status: dict[str, object]) -> None:
        statuses.append(status)

    async def exercise() -> None:
        tracker = ImmutableSpeechBoundaryTracker(
            metadata={"chat_id": "chat-1", "assistant_message_id": "assistant-1", "source_version": 1},
            dispatch_speech=failed_dispatch,
            report_status=report_status,
        )
        tracker.observe("Private paragraph.", is_final=True)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert statuses == [{"type": "assistant_speech_status", "status": "error", "sequence": 0, "error": "Speech is temporarily unavailable."}]
