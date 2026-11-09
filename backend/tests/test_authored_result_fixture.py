"""Validate deterministic inference input and replay dispatch, without services.

The integration spec supplies this document to the real encrypted finalizer.
These unit checks establish fixture validity and dispatch, not persistence proof.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.utils.authored_result_fences import (
    get_authoring_definitions,
    normalize_authored_results_source,
)


def fixture():
    return json.loads((Path(__file__).resolve().parents[1]
                       / "apps/ai/testing/fixtures/authored_results.json").read_text())


# contract-test: supporting surface=cli assertions=authored-results.eligibility.all-suitable-results,authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts,tv-titles.authoring.relevant-and-flexible,tv-titles.series.supplied-seasons
def test_authored_fixture_is_a_complete_valid_source_document():
    data = fixture()
    assert data["skill_executions"] == []
    assert data["preprocessing"]["relevant_app_skills"] == []
    assert len(data["embeds"]) == 1
    carrier = next(iter(data["embeds"].values()))
    assert set(carrier) == {"type", "document"}
    assert carrier["type"] == "authored_results"
    document = carrier["document"]
    result = normalize_authored_results_source(json.dumps(document))
    assert result.status == "valid", result.warnings
    assert len(result.items) == len(document["items"]) == 25
    definitions = get_authoring_definitions()
    assert {item.kind for item in result.items} == set(definitions)
    assert result.view["items"] == [item["id"] for item in document["items"]]
    for source, normalized in zip(document["items"], result.items):
        assert normalized.content["title"] == source["title"]
        assert normalized.content["type"] == definitions[source["kind"]]["backend_type"]
        assert normalized.content["authoring"]["origin"] == source["origin"]
        for field, value in source["details"].items():
            if field != "title":
                assert normalized.content[field] == value
        if source["origin"] == "draft":
            assert source["title"].startswith("Draft: ")
            assert "observed_at" not in normalized.content["authoring"]
            assert normalized.content["authoring"]["sources"] == []
        else:
            assert normalized.content["authoring"]["sources"] == source["sources"]
    shopping = next(item.content for item in result.items if item.kind == "shopping.product")
    assert shopping["price_cents"] == 2499
    assert "currency" not in shopping and "rating" not in shopping and "reviews" not in shopping
    appointment = next(item.content for item in result.items if item.kind == "health.appointment")
    assert "insurance" not in appointment and "availability" not in appointment
    movie = next(item.content for item in result.items if item.kind == "tv.movie")
    assert movie["type"] == "tv_movie"
    assert movie["score"]["scale"] == 10
    assert movie["score"]["source_label"] == "Supplied score"
    series = next(item.content for item in result.items if item.kind == "tv.series")
    assert series["type"] == "tv_series"
    assert series["seasons"][0]["season_number"] == 0
    assert series["seasons"][0]["title"] == "Specials"
    assert len(series["seasons"]) < series["season_count"]
    assert sum(season["episode_count"] for season in series["seasons"]) < series["episode_count"]
    assert "score" not in series and "streaming_availability" not in series


# contract-test: supporting surface=cli assertions=authored-results.creation.relevant-and-independent,authored-results.lifecycle.encrypted-and-stable
def test_replay_passes_authored_document_to_real_lifecycle_interface(monkeypatch):
    # Loading this module requires the backend environment, as does mock replay.
    from backend.apps.ai.testing import mock_replay

    data = fixture()
    old_id, metadata = next(iter(data["embeds"].items()))
    new_id = "44444444-4444-4444-8444-444444444444"
    calls = []
    services = (object(), object(), object())

    class EmbedService:
        def __init__(self, *args):
            assert args == services

        async def create_json_content_embed_placeholder(self, **kwargs):
            calls.append(("create", kwargs))
            return {"embed_id": new_id, "embed_reference": json.dumps({
                "type": "authored_results", "embed_id": new_id,
            })}

        async def update_json_content_embed_content(self, **kwargs):
            calls.append(("finish", kwargs))
            return True

    module = ModuleType("backend.core.api.app.services.embed_service")
    module.EmbedService = EmbedService
    monkeypatch.setitem(sys.modules, module.__name__, module)
    request = SimpleNamespace(chat_id="owner-chat", message_id="source-message",
                              user_id="owner-user", user_id_hash="owner-hash")
    rewritten = asyncio.run(mock_replay._recreate_fixture_embeds(
        data["response"], data, "owner-task", request, *services, "owner-vault-key",
    ))
    assert [name for name, _ in calls] == ["create", "finish"]
    for _, kwargs in calls:
        assert kwargs["source_language"] == "openmates_embeds"
        assert kwargs["chat_id"] == request.chat_id
        assert kwargs["user_id"] == request.user_id
        assert kwargs["user_id_hash"] == request.user_id_hash
        assert kwargs["user_vault_key_id"] == "owner-vault-key"
    assert calls[0][1]["task_id"] == "owner-task"
    assert calls[0][1]["message_id"] == request.message_id
    assert calls[1][1]["embed_id"] == new_id
    assert calls[1][1]["status"] == "finished"
    assert json.loads(calls[1][1]["source_json"]) == metadata["document"]
    assert old_id not in rewritten
    assert new_id in rewritten
    assert rewritten.startswith("Here are your supplied records")
    assert rewritten.endswith("The draft recipe and social post remain proposals.")


# contract-test: supporting surface=cli assertions=authored-results.creation.relevant-and-independent,authored-results.lifecycle.encrypted-and-stable
def test_authored_replay_returns_validated_committed_postprocessing(monkeypatch):
    from backend.apps.ai.testing import mock_replay
    from backend.apps.ai.processing import postprocessor
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.core.api.app.schemas.chat import AIHistoryMessage

    data = fixture()
    data["initial_delay_ms"] = 0
    monkeypatch.setattr(mock_replay, "load_fixture", lambda _fixture_id: data)
    monkeypatch.setattr(mock_replay, "_recreate_fixture_embeds", AsyncMock(return_value=data["response"]))
    provider_postprocess = AsyncMock(side_effect=AssertionError("No provider inference in a committed fixture"))
    monkeypatch.setattr(postprocessor, "handle_postprocessing", provider_postprocess)
    request = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="55555555-5555-4555-8555-555555555555",
        user_id="11111111-1111-4111-8111-111111111111",
        user_id_hash="owner-hash",
        message_history=[AIHistoryMessage(role="user", content="Supplied records", created_at=1)],
    )
    result = asyncio.run(mock_replay.replay_fixture(
        "authored_results", "66666666-6666-4666-8666-666666666666",
        request, SimpleNamespace(publish_event=AsyncMock()),
    ))
    metadata = result["postprocessing_result"]
    assert isinstance(metadata, postprocessor.PostProcessingResult)
    assert metadata.model_dump() == data["postprocessing"]
    provider_postprocess.assert_not_awaited()
    assert mock_replay.build_fixture_postprocessing_result({}) is None


@pytest.mark.parametrize("metadata", [
    None, {"unknown_field": []}, {"follow_up_request_suggestions": "not a list"},
])
# contract-test: supporting surface=cli assertions=authored-results.creation.relevant-and-independent
def test_fixture_postprocessing_rejects_invalid_metadata(metadata):
    from backend.apps.ai.testing import mock_replay

    with pytest.raises(ValueError):
        mock_replay.build_fixture_postprocessing_result({"postprocessing": metadata})


@pytest.mark.parametrize("isolated", [None, "0", "true", "01", "1"])
@pytest.mark.parametrize("published", [True, False])
# contract-test: tooling
def test_final_publication_logs_are_literal_ci_only_and_preserve_replay(monkeypatch, caplog, isolated, published):
    from backend.apps.ai.testing import mock_replay
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.core.api.app.schemas.chat import AIHistoryMessage

    if isolated is None:
        monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
    else:
        monkeypatch.setenv("OPENMATES_CI_ISOLATED", isolated)
    canary = "PRIVATE-FIXTURE-CONTENT-AND-KEY-CANARY"
    response = f"Supplied private material {canary}. Final source https://example.org/private."
    prefix = f"Supplied private material {canary}."
    data = {
        "response": response, "initial_delay_ms": 0,
        "preprocessing": {"category": "general_knowledge"},
        "stream_chunks": [{"full_content_so_far": prefix}, {"full_content_so_far": response}],
    }
    monkeypatch.setattr(mock_replay, "load_fixture", lambda _fixture_id: data)
    request = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="55555555-5555-4555-8555-555555555555",
        user_id="11111111-1111-4111-8111-111111111111", user_id_hash="private-owner-hash",
        message_history=[AIHistoryMessage(role="user", content=canary, created_at=1)],
    )
    task_id = "66666666-6666-4666-8666-666666666666"
    # Backend imports can reconfigure registered logger handlers. Capture through
    # an isolated real logger so the test does not depend on that global setup.
    capture_logger = logging.Logger(mock_replay.__name__, level=logging.INFO)
    capture_logger.addHandler(caplog.handler)
    monkeypatch.setattr(mock_replay, "logger", capture_logger)
    prefix_marker = "Fixture final publication stage="

    def publication_logs():
        return [record for record in caplog.records
                if record.name == mock_replay.__name__ and record.getMessage().startswith(prefix_marker)]

    chunks = []

    async def publish(channel, payload):
        if payload.get("type") != "ai_message_chunk":
            return
        assert channel == f"chat_stream::{request.chat_id}"
        # The complete marker cannot exist until the final await returns.
        expected_logs = ["Fixture final publication stage=begin success=none"] if isolated == "1" and payload["is_final_chunk"] else []
        assert [record.getMessage() for record in publication_logs()] == expected_logs
        chunks.append(payload.copy())
        return published

    result = asyncio.run(mock_replay.replay_fixture(
        "authored_results_publication_unit", task_id, request,
        SimpleNamespace(publish_event=publish),
    ))
    expected_logs = [
        "Fixture final publication stage=begin success=none",
        "Fixture final publication stage=complete success=true" if published else "Fixture final publication stage=complete success=false",
    ] if isolated == "1" else []
    records = publication_logs()
    assert [record.getMessage() for record in records] == expected_logs
    assert all(record.levelno == logging.INFO and not record.args for record in records)
    assert all(canary not in record.getMessage() and request.chat_id not in record.getMessage() for record in records)
    assert result["aggregated_final_response"] == response
    base = {
        "type": "ai_message_chunk", "task_id": task_id, "chat_id": request.chat_id,
        "user_id_uuid": request.user_id, "user_id_hash": request.user_id_hash,
        "message_id": task_id, "user_message_id": request.message_id,
        "created_at": chunks[0]["created_at"], "external_request": False,
        "category": "general_knowledge",
    }
    assert chunks == [
        {**base, "full_content_so_far": prefix, "sequence": 1, "is_final_chunk": False},
        {**base, "full_content_so_far": response, "sequence": 2, "is_final_chunk": True,
         "interrupted_by_soft_limit": False, "interrupted_by_revocation": False},
    ]
