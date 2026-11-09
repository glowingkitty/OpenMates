"""Aggregator and real stream-consumer coverage for SVG code blocks released line by line."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import stream_consumer
from backend.apps.ai.utils.stream_utils import PROGRESSIVE_CODE_LANGUAGES, aggregate_paragraphs
from backend.core.api.app.services.embed_service import EmbedService

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">\n<rect width="10" height="10"/>\n<circle r="3"/>\n</svg>\n'


# contract-test: direct surface=rest_api assertions=interactive-html.render.vector-image-and-progressive-streaming
def test_svg_block_updates_its_embed_while_streaming_and_finishes_once(monkeypatch) -> None:
    tokens = ["Here it is:\n\n```svg:logo.svg\n", *[SVG[i:i + 9] for i in range(0, len(SVG), 9)], "``", "`\n\nDone."]

    async def main_stream(**_kwargs):
        async def raw():
            for token in tokens:
                yield token

        async for chunk in aggregate_paragraphs(
            raw(), progressive_code_languages=PROGRESSIVE_CODE_LANGUAGES, progressive_code_interval=0,
        ):
            yield chunk

    class FakeEmbedService(EmbedService):
        create_code_embed_placeholder = AsyncMock(return_value={
            "embed_id": "svg-1", "embed_reference": '{"type":"code","embed_id":"svg-1"}',
        })
        update_code_embed_content = AsyncMock(return_value=True)

        def __init__(self, *_args):
            pass

    monkeypatch.setattr(stream_consumer, "handle_main_processing", main_stream)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult",
                        lambda _: SimpleNamespace(state="STARTED"))
    monkeypatch.setattr("backend.core.api.app.services.embed_service.EmbedService", FakeEmbedService)
    request = AskSkillRequest(
        chat_id="chat-1", message_id="message-1", user_id="user-1",
        user_id_hash="hash-1", message_history=[], is_incognito=True,
    )
    response, *_ = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request,
        preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(), user_vault_key_id="vault-1",
        all_mates_configs=[], discovered_apps_metadata={}, cache_service=None,
    ))

    assert '{"type":"code","embed_id":"svg-1"}' in response
    assert "<svg" not in response and "Done." in response
    FakeEmbedService.create_code_embed_placeholder.assert_awaited_once()
    calls = [call.kwargs for call in FakeEmbedService.update_code_embed_content.await_args_list]
    partial = [call["code_content"] for call in calls if call["status"] == "processing"]
    finished = [call["code_content"] for call in calls if call["status"] == "finished"]
    assert len(partial) >= 2
    assert all(SVG.startswith(code) and code.endswith("\n") for code in partial)
    assert [len(code) for code in partial] == sorted({len(code) for code in partial})
    assert [code.strip() for code in finished] == [SVG.strip()]


async def _collect_progressive(parts: list[str]) -> list[str]:
    async def _stream():
        for part in parts:
            yield part

    return [
        chunk async for chunk in aggregate_paragraphs(
            _stream(), progressive_code_languages=frozenset({"svg"}), progressive_code_interval=0,
        )
    ]


# contract-test: supporting surface=rest_api assertions=interactive-html.render.vector-image-and-progressive-streaming
def test_progressive_code_block_is_released_in_complete_lines() -> None:
    parts = ["Here:\n\n```svg:logo.svg\n<svg>\n<rect", "/>\n<circle/>\n</svg>\n``", "`\n\nDone."]
    chunks = asyncio.run(_collect_progressive(parts))

    assert chunks == [
        "Here:\n\n",
        "```svg:logo.svg\n<svg>\n",
        "<rect/>\n<circle/>\n</svg>\n",
        "```",
        "\n\n",
        "Done.",
    ]
    assert "".join(chunks) == "".join(parts)
    assert all(chunk.endswith("\n") for chunk in chunks[1:3])


# contract-test: supporting surface=rest_api assertions=interactive-html.render.vector-image-and-progressive-streaming
def test_other_code_languages_stay_one_closed_block() -> None:
    chunks = asyncio.run(_collect_progressive(["```python:a.py\nprint(1)\n", "print(2)\n```"]))

    assert chunks == ["```python:a.py\nprint(1)\nprint(2)\n```"]


# contract-test: supporting surface=rest_api assertions=interactive-html.render.vector-image-and-progressive-streaming
def test_progressive_releases_are_rate_limited() -> None:
    async def _run() -> list[str]:
        async def _stream():
            for part in ["```svg\n<svg>\n", "<a/>\n", "<b/>\n", "</svg>\n```"]:
                yield part

        return [
            chunk async for chunk in aggregate_paragraphs(
                _stream(), progressive_code_languages=frozenset({"svg"}), progressive_code_interval=60,
            )
        ]

    assert asyncio.run(_run()) == ["```svg\n<svg>\n", "<a/>\n<b/>\n</svg>\n```"]
