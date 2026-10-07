"""A completed Project read keeps original file text out of generated embeds."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

try:
    from backend.apps.ai.processing.preprocessor import PreprocessingResult
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.apps.ai.tasks import stream_consumer
except ImportError as exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {exc}")


# contract-test: supporting surface=rest_api assertions=projects.files.search-scoped
@pytest.mark.parametrize("project_reference_output,split_fence", [
    (True, False), (True, True), (False, False),
])
def test_project_reference_stream_does_not_publish_file_body_as_code_embed(
    monkeypatch, project_reference_output: bool, split_fence: bool,
) -> None:
    file_body = "name: original-project-file\nconfiguration: preserve-source-location\n"
    reference = '```json\n{"type":"projects","embed_id":"original-reference-id"}\n```\n\n'
    fenced_file_body = f"```yaml\n{file_body}```\n\n"

    async def main_stream(**_kwargs):
        if project_reference_output:
            yield {"__project_file_reference_output__": True}
            yield reference
        if split_fence:
            yield "```yaml\n"
            yield file_body
            yield "```\n\n"
        else:
            yield fenced_file_body

    class FakeEmbedService:
        create_code_embed_placeholder = AsyncMock(return_value={
            "embed_id": "new-generated-code-id",
            "embed_reference": '{"type":"code","embed_id":"new-generated-code-id"}',
        })
        update_code_embed_content = AsyncMock(return_value=True)

        def __init__(self, *_args):
            pass

    monkeypatch.setattr(stream_consumer, "handle_main_processing", main_stream)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult",
                        lambda _: SimpleNamespace(state="STARTED"))
    monkeypatch.setattr(
        "backend.core.api.app.services.embed_service.EmbedService", FakeEmbedService,
    )
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

    if project_reference_output:
        assert response == reference + fenced_file_body
        FakeEmbedService.create_code_embed_placeholder.assert_not_awaited()
        FakeEmbedService.update_code_embed_content.assert_not_awaited()
    else:
        assert "new-generated-code-id" in response
        FakeEmbedService.create_code_embed_placeholder.assert_awaited_once()
        assert any(call.kwargs.get("code_content") == file_body.rstrip("\n")
                   for call in FakeEmbedService.update_code_embed_content.await_args_list)
