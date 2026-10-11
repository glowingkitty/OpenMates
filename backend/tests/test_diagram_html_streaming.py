"""Real stream-consumer coverage for HTML diagram fence chunk boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import stream_consumer
from backend.tests.test_diagram_html_fences import SOURCE


@pytest.mark.parametrize("variant", ["single", "multi", "bare"])
# contract-test: direct surface=rest_api assertions=chats.rendering.assistant-document-convergence,chats.streaming.ordered-final
def test_diagram_fence_streams_reference_then_exact_validated_source(monkeypatch, variant: str) -> None:
    if variant == "single":
        chunks = [f"```openmates_diagram\n{SOURCE}\n```\n\n"]
    elif variant == "multi":
        chunks = ["```openmates_diagram\n", SOURCE[:125], SOURCE[125:] + "\n```\n\n"]
    else:
        chunks = ["```", "openmates_diagram\n", SOURCE[:125], SOURCE[125:] + "\n```\n\n"]

    async def main_stream(**_kwargs):
        for chunk in chunks:
            yield chunk

    class FakeEmbedService:
        create_diagram_html_embed_placeholder = AsyncMock(return_value={
            "embed_id": "diagram-1",
            "embed_reference": '{"type":"diagram_html","embed_id":"diagram-1"}',
        })
        update_diagram_html_embed_content = AsyncMock(return_value=True)
        create_code_embed_placeholder = AsyncMock()

        def __init__(self, *_args):
            pass

    FakeEmbedService.create_diagram_html_embed_placeholder.reset_mock()
    FakeEmbedService.update_diagram_html_embed_content.reset_mock()
    FakeEmbedService.create_code_embed_placeholder.reset_mock()
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
    assert '{"type":"diagram_html","embed_id":"diagram-1"}' in response
    FakeEmbedService.create_diagram_html_embed_placeholder.assert_awaited_once()
    FakeEmbedService.create_code_embed_placeholder.assert_not_awaited()
    finished = [call.kwargs for call in FakeEmbedService.update_diagram_html_embed_content.await_args_list
                if call.kwargs.get("status") == "finished"]
    assert len(finished) == 1
    # The incremental parser retains the line break immediately before the
    # closing fence; the complete-block parser strips that fence separator.
    assert finished[0]["html_source"] == (SOURCE if variant == "single" else SOURCE + "\n")
    assert finished[0]["diagram_kind"] == "flowchart"


# contract-test: direct surface=rest_api assertions=chats.rendering.assistant-document-convergence,chats.streaming.ordered-final
def test_unsafe_diagram_stream_publishes_error_without_source(monkeypatch) -> None:
    invalid = SOURCE.replace("</body>", "<script>alert(1)</script></body>")

    async def main_stream(**_kwargs):
        yield f"```openmates_diagram\n{invalid}\n```\n\n"

    class FakeEmbedService:
        create_diagram_html_embed_placeholder = AsyncMock(return_value={
            "embed_id": "diagram-unsafe", "embed_reference": '{"type":"diagram_html","embed_id":"diagram-unsafe"}',
        })
        update_diagram_html_embed_content = AsyncMock(return_value=True)
        def __init__(self, *_args): pass

    monkeypatch.setattr(stream_consumer, "handle_main_processing", main_stream)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult",
                        lambda _: SimpleNamespace(state="STARTED"))
    monkeypatch.setattr("backend.core.api.app.services.embed_service.EmbedService", FakeEmbedService)
    request = AskSkillRequest(chat_id="chat-1", message_id="message-1", user_id="user-1",
                              user_id_hash="hash-1", message_history=[], is_incognito=True)
    asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request,
        preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(), user_vault_key_id="vault-1",
        all_mates_configs=[], discovered_apps_metadata={}, cache_service=None,
    ))
    calls = [call.kwargs for call in FakeEmbedService.update_diagram_html_embed_content.await_args_list]
    assert calls and calls[-1]["status"] == "error"
    assert calls[-1]["html_source"] == ""
    assert not any(call["html_source"] == invalid for call in calls)
