# contract-test-file: infrastructure
"""Regression tests for bounded cumulative AI stream publishing.

Ordinary content snapshots may be coalesced, but force-flush callers retain
their exact sequence and payload order before structural or final events.
"""

from __future__ import annotations

import asyncio

from backend.shared.python_utils.stream_content_coalescer import (
    CumulativeContentPublisher,
    STREAM_CONTENT_COALESCE_SECONDS,
)


def test_cumulative_content_updates_coalesce_to_the_latest_snapshot() -> None:
    published: list[dict[str, object]] = []

    async def publish(payload: dict[str, object], _action: str) -> None:
        published.append(payload)

    async def exercise() -> None:
        publisher = CumulativeContentPublisher(publish)
        await publisher.publish({"sequence_number": 1, "content": "one"}, "first")
        await publisher.publish({"sequence_number": 2, "content": "one two"}, "second")

        assert published == []
        await publisher.flush()

    asyncio.run(exercise())

    assert published == [{"sequence_number": 2, "content": "one two"}]


def test_cumulative_content_updates_flush_within_the_coalescing_window() -> None:
    published: list[dict[str, object]] = []

    async def publish(payload: dict[str, object], _action: str) -> None:
        published.append(payload)

    async def exercise() -> None:
        publisher = CumulativeContentPublisher(publish)
        await publisher.publish({"sequence_number": 1, "content": "one"}, "content")
        await asyncio.sleep(STREAM_CONTENT_COALESCE_SECONDS * 1.5)

    asyncio.run(exercise())

    assert published == [{"sequence_number": 1, "content": "one"}]


def test_force_flush_preserves_content_before_final_recovery_payload() -> None:
    published: list[dict[str, object]] = []

    async def publish(payload: dict[str, object], _action: str) -> None:
        published.append(payload)

    async def exercise() -> None:
        publisher = CumulativeContentPublisher(publish)
        await publisher.publish({"sequence_number": 4, "content": "exact content"}, "content")
        await publisher.flush()
        await publish(
            {
                "sequence_number": 5,
                "content": "exact content",
                "is_final_chunk": True,
                "recovery_job_id": "recovery-job",
                "recovery_protocol_version": 1,
            },
            "final",
        )

    asyncio.run(exercise())

    assert published == [
        {"sequence_number": 4, "content": "exact content"},
        {
            "sequence_number": 5,
            "content": "exact content",
            "is_final_chunk": True,
            "recovery_job_id": "recovery-job",
            "recovery_protocol_version": 1,
        },
    ]


def test_publish_callback_marks_only_actual_publishes() -> None:
    publish_count = 0

    async def publish(_payload: dict[str, object], _action: str) -> None:
        return None

    def on_published() -> None:
        nonlocal publish_count
        publish_count += 1

    async def exercise() -> None:
        publisher = CumulativeContentPublisher(publish, on_published)
        await publisher.publish({"content": "one"}, "first")
        await publisher.publish({"content": "two"}, "second")
        await publisher.flush()

    asyncio.run(exercise())

    assert publish_count == 1


def test_second_window_auto_flushes_after_the_first_window_completed() -> None:
    published: list[str] = []

    async def publish(payload: dict[str, object], _action: str) -> None:
        published.append(str(payload["content"]))

    async def exercise() -> None:
        publisher = CumulativeContentPublisher(
            publish,
            coalesce_seconds=0.01,
        )
        await publisher.publish({"content": "first"}, "first")
        await asyncio.sleep(0.02)
        await publisher.publish({"content": "second"}, "second")
        await asyncio.sleep(0.02)

    asyncio.run(exercise())

    assert published == ["first", "second"]


def test_structural_flush_does_not_cancel_an_in_flight_publish() -> None:
    published: list[str] = []
    publish_started = asyncio.Event()
    release_publish = asyncio.Event()

    async def publish(payload: dict[str, object], _action: str) -> None:
        publish_started.set()
        await release_publish.wait()
        published.append(str(payload["content"]))

    async def exercise() -> None:
        publisher = CumulativeContentPublisher(
            publish,
            coalesce_seconds=0.01,
        )
        await publisher.publish({"content": "before-structure"}, "content")
        await publish_started.wait()
        structural_flush = asyncio.create_task(publisher.flush())
        release_publish.set()
        await structural_flush

    asyncio.run(exercise())

    assert published == ["before-structure"]
