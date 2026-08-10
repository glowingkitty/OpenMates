# backend/tests/test_stream_paragraph_contract.py
#
# Defines the existing paragraph-buffered assistant streaming contract.
# Complete paragraphs and closed code fences are yielded in source order.
# The frontend still validates semantic commit safety for every cumulative delta.

import asyncio

from backend.apps.ai.utils.stream_utils import aggregate_paragraphs


async def _collect(parts: list[str]) -> list[str]:
    async def _stream():
        for part in parts:
            yield part

    return [chunk async for chunk in aggregate_paragraphs(_stream())]


def test_aggregates_complete_paragraphs_and_final_remainder_in_order() -> None:
    chunks = asyncio.run(_collect(["First", " paragraph.\n\nSecond", " paragraph."]))

    assert chunks == ["First paragraph.\n\n", "Second paragraph."]
    assert "".join(chunks) == "First paragraph.\n\nSecond paragraph."


def test_yields_closed_code_fence_as_one_stream_block() -> None:
    chunks = asyncio.run(_collect(["Before\n\n```json\n", '{"type":"example"}', "```\n\nAfter"]))

    assert chunks[0] == "Before\n\n"
    assert chunks[1] == '```json\n{"type":"example"}```'
    assert "".join(chunks) == 'Before\n\n```json\n{"type":"example"}```\n\nAfter'
