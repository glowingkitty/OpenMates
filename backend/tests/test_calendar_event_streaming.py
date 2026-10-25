"""Exercise the real stream parser at complete, split, and bare fence boundaries."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import stream_consumer

SOURCE = json.dumps({
    "openmatesType": "calendar_event", "schemaVersion": 1,
    "primary_event": {"title": "FOSDEM 2027", "start": "2027-01-30", "end": "2027-02-01"},
    "context_events": [{"title": "Travel", "start": "2027-01-29"}],
})


@pytest.mark.parametrize("variant", ["single", "multi", "bare"])
# contract-test: direct surface=rest_api assertions=calendar-event.streaming.saved-lifecycle
def test_calendar_fence_streams_one_event_reference(monkeypatch, variant):
    chunks = {
        "single": [f"```openmates_calendar_event\n{SOURCE}\n```\n\n"],
        "multi": ["```openmates_calendar_event\n", SOURCE[:65], SOURCE[65:] + "\n```\n\n"],
        "bare": ["```", "openmates_calendar_event\n", SOURCE[:65], SOURCE[65:] + "\n```\n\n"],
    }[variant]

    async def main_stream(**_kwargs):
        for chunk in chunks:
            yield chunk

    class FakeEmbedService:
        create_json_content_embed_placeholder = AsyncMock(return_value={
            "embed_id": "event-1",
            "embed_reference": '{"type":"calendar_event","embed_id":"event-1"}',
        })
        update_json_content_embed_content = AsyncMock(return_value=True)
        create_code_embed_placeholder = AsyncMock()

        def __init__(self, *_args):
            pass

    monkeypatch.setattr(stream_consumer, "handle_main_processing", main_stream)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    monkeypatch.setattr("backend.core.api.app.services.embed_service.EmbedService", FakeEmbedService)
    request = AskSkillRequest(chat_id="chat-1", message_id="message-1", user_id="user-1",
                              user_id_hash="hash-1", message_history=[], is_incognito=True)
    response, *_ = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request,
        preprocessing_result=PreprocessingResult(can_proceed=True), base_instructions={},
        directus_service=SimpleNamespace(), encryption_service=SimpleNamespace(),
        user_vault_key_id="vault-1", all_mates_configs=[], discovered_apps_metadata={}, cache_service=None,
    ))
    assert response.count('{"type":"calendar_event","embed_id":"event-1"}') == 1
    assert "primary_event" not in response
    FakeEmbedService.create_json_content_embed_placeholder.assert_awaited_once()
    assert FakeEmbedService.create_json_content_embed_placeholder.await_args.kwargs["source_language"] == "openmates_calendar_event"
    FakeEmbedService.create_code_embed_placeholder.assert_not_awaited()
    finished = [call.kwargs for call in FakeEmbedService.update_json_content_embed_content.await_args_list
                if call.kwargs.get("status") == "finished"]
    assert len(finished) == 1
    assert json.loads(finished[0]["source_json"]) == json.loads(SOURCE)
    assert finished[0]["source_language"] == "openmates_calendar_event"
