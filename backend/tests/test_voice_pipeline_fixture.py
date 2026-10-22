"""Guard and ordinary routing coverage for provider-free voice CI turns."""

# contract-test-file: infrastructure

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.testing import voice_pipeline_fixture as fixture


GUARDS = {"CI": "true", "OPENMATES_CI_ISOLATED": "1",
          "OPENMATES_CI_AI_FIXTURES": "1", "MOCK_EXTERNAL_APIS": "true"}


@pytest.fixture
def isolated(monkeypatch):
    for key, value in GUARDS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")


def request(text, voice_mode=True):
    return SimpleNamespace(voice_mode=voice_mode, current_user_content=text,
                           message_history=[{"role": "user", "content": text}])


@pytest.mark.parametrize("missing", list(GUARDS) + ["voice_mode"])
def test_every_fixture_phase_requires_all_guards_and_admitted_voice_mode(isolated, monkeypatch, missing):
    admitted = request(fixture.RAMEN_REQUEST, missing != "voice_mode")
    if missing != "voice_mode":
        monkeypatch.delenv(missing)
    assert fixture.active(admitted) is False
    assert fixture.main_stream(admitted, message_history=[], tools=[], model_id="automatic/model",
                               max_tokens=100, pre_dispatch_admission=None) is None
    assert fixture.speech_fixture_context(admitted) == {}
    assert fixture.postprocessing_fixture(voice_mode=admitted.voice_mode,
        user_message=admitted.current_user_content, current_chat_title=None, user_system_language="en") is None


@pytest.mark.asyncio
async def test_scoped_decisions_run_the_real_router_and_restore_context(isolated):
    from backend.apps.ai.processing.jev_preprocessing import decide_preprocessing_with_jev

    @fixture.voice_preprocessing_scope
    async def route(request_data):
        return await decide_preprocessing_with_jev(
            model_id="configured-decision-model", secrets_manager=None,
            message_history=request_data.message_history, topic_areas=["general_misc: General"],
            available_apps=["images", "web"], available_skills=["images-search", "web-search"],
            available_focus_modes=[], available_settings_and_memories={}, recent_skill_activity=[],
            conversation_summary=None, previous_category=None, is_first_message=True,
        )

    rich, german = await asyncio.gather(route(request(fixture.RICH_REQUEST)),
                                      route(request(fixture.GERMAN_REQUEST)))
    assert rich["relevant_app_skills"] == ["images-search"]
    assert rich["selected_app_ids"] == ["images"]
    assert german["relevant_app_skills"] == []
    assert german["output_language"] == "de"
    assert rich["complexity"] == german["complexity"] == "low"
    assert fixture.jev_response(questions={"safe": {"type": "noul"}}, model="configured") is None


@pytest.mark.asyncio
async def test_preprocessor_scope_restores_after_failure_and_early_task_inherits_scope(isolated):
    from backend.apps.ai.processing.early_chat_metadata import generate_early_chat_metadata

    spawned = []

    @fixture.voice_preprocessing_scope
    async def fail(request_data):
        spawned.append(asyncio.create_task(generate_early_chat_metadata(task_id="voice-fixture",
            message_history=request_data.message_history, user_system_language="en", secrets_manager=None)))
        raise RuntimeError("routing failed")

    with pytest.raises(RuntimeError, match="routing failed"):
        await fail(request(fixture.RAMEN_REQUEST))
    metadata = await spawned[0]
    assert metadata.title == "Making vegetarian ramen"
    assert metadata.summary == "The user asks how to prepare ramen at home."
    assert fixture.early_metadata_fixture("en") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("text,answer", [(fixture.RAMEN_REQUEST, fixture.RAMEN_RESPONSE),
    (fixture.GERMAN_REQUEST, fixture.GERMAN_RESPONSE), ("A typed request", "I received your text: A typed request")])
async def test_main_provider_substitute_keeps_admission_and_localized_wait(isolated, monkeypatch, text, answer):
    delay = AsyncMock()
    monkeypatch.setattr(fixture.asyncio, "sleep", delay)
    admission = AsyncMock()
    admitted = request(text)
    chunks = [chunk async for chunk in fixture.main_stream(admitted,
        message_history=admitted.message_history, tools=[], model_id="automatic/model",
        max_tokens=123, pre_dispatch_admission=admission)]
    assert chunks == [answer]
    admission.assert_awaited_once_with("automatic/model", 123, tariff_snapshot=None, region=None)
    if text == fixture.GERMAN_REQUEST:
        delay.assert_awaited_once_with(fixture.GERMAN_RESPONSE_DELAY_SECONDS)
    else:
        delay.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["flat_toon", "grouped_json"])
async def test_rich_turn_requires_real_image_search_output_before_prose(isolated, encoding, monkeypatch):
    import json
    from toon_format import encode
    from backend.apps.images.skills.search_skill import SearchRequest, SearchSkill
    from backend.core.api.app.services.embed_service import EmbedService
    from backend.shared.python_utils.markdown_links import iter_markdown_links
    from backend.apps.ai.assistant_speech.projection import project_final_voice_clauses
    from backend.shared.python_utils import url_normalizer
    from backend.shared.providers.groq.safeguard import GroqSafeguardClient
    from backend.apps.ai.processing.url_validator import check_url_status

    admitted = request(fixture.RICH_REQUEST)
    tools = [{"type": "function", "function": {"name": "images-search"}}]
    kwargs = {"tools": tools, "model_id": "automatic/model", "max_tokens": 123,
              "pre_dispatch_admission": None}
    chunks = [chunk async for chunk in fixture.main_stream(admitted,
        message_history=admitted.message_history, **kwargs)]
    assert len(chunks) == 1 and chunks[0].function_name == "images-search"
    skill = SearchSkill(app=None, app_id="images", skill_id="search", skill_name="Search images",
                        skill_description="Find images.")
    result = await skill.execute(SearchRequest(**chunks[0].function_arguments_parsed), secrets_manager=object())
    assert result.error is None
    # MainProcessor authors one child ref before exposing the result to the
    # model. Mirror that real formatting, including its separate parent ref.
    image_result = result.results[0]["results"][0]
    image_ref = EmbedService._generate_embed_ref_slug("image_result", image_result)
    image_result = {**image_result, "embed_ref": image_ref}
    payload = (encode({"source_ref": "real-registered-parent"}) + "\n" + encode(image_result)
               if encoding == "flat_toon" else json.dumps({"results": [{"id": 1, "results": [image_result]}]}))
    tool_turn = admitted.message_history + [{"role": "tool", "name": "images-search", "content": payload}]
    response = "".join([chunk async for chunk in fixture.main_stream(admitted,
        message_history=tool_turn, **kwargs)])
    assert response == fixture.RICH_RESPONSE + f"[!](embed:{image_ref})\n\n"
    assert [(link.label, link.href) for link in iter_markdown_links(response)
            if link.href.startswith("embed:")] == [("!", "embed:" + image_ref)]
    assert "real-registered-parent" not in response
    source_url = image_result["source_page_url"]
    assert "# Results" in response and f"[the source]({source_url})" in response
    # Finalization uses the full persisted tool_calls_info source corpus, not
    # the model's answer or its private fixture constants, to authorize URLs.
    tool_calls_info = [{"app_id": "images", "skill_id": "search", "preview_data": {
        "results_toon": encode({key: value for key, value in image_result.items() if key != "embed_ref"})}}]
    sources = url_normalizer.extract_urls_from_content({"message_history": [], "tool_calls_info": tool_calls_info})
    assert source_url in sources
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", GroqSafeguardClient)
    assert await url_normalizer.sanitize_text_urls_with_safeguard(response, allowed_source_urls=sources) == response
    assert (await check_url_status(source_url))["is_valid"] is True
    without_source = await url_normalizer.sanitize_text_urls_with_safeguard(response, allowed_source_urls=set())
    assert f"[the source]({source_url})" not in without_source
    spoken = project_final_voice_clauses(response)
    assert any("Here are the images I found" in clause for clause in spoken)
    assert not any(image_ref in clause or "embed:" in clause for clause in spoken)
    with pytest.raises(RuntimeError, match="real image-search result"):
        [chunk async for chunk in fixture.main_stream(admitted,
            message_history=admitted.message_history + [{"role": "tool", "content": "not an image"}], **kwargs)]


@pytest.mark.parametrize("name,payload", [
    ("images-search", '{"title":"Sunset ocean fixture"}'),
    ("web-search", '{"title":"Sunset ocean fixture","embed_ref":"unrelated-tool-ref"}'),
    ("images-search", '{"title":"A different image","embed_ref":"unrelated-image-ref"}'),
    ("images-search", '{"title":"Sunset ocean fixture","embed_ref":"bad)\\nmarkup"}'),
])
def test_rich_fixture_never_invents_refs_from_missing_or_unrelated_tool_data(name, payload):
    assert fixture._image_preview_refs([{"name": name, "content": payload}]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_guard", [None, *GUARDS])
async def test_url_provider_substitutes_require_every_guard_and_exact_public_fixture(isolated, monkeypatch, missing_guard):
    from backend.shared.testing.voice_call_fixture import VOICE_RICH_SOURCE_URL
    from backend.shared.providers.groq.safeguard import GroqSafeguardClient
    from backend.apps.ai.processing import url_validator

    if missing_guard:
        monkeypatch.delenv(missing_guard)

    class HTTPClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url):
            return SimpleNamespace(status_code=404)

    monkeypatch.setattr(url_validator.httpx, "AsyncClient", lambda **kwargs: HTTPClient())
    monkeypatch.setattr(url_validator, "_generate_randomized_headers", lambda: {})
    client = GroqSafeguardClient()
    report = await client.report_malicious_urls(urls=[VOICE_RICH_SOURCE_URL], assistant_response="fixture")
    status = await url_validator.check_url_status(VOICE_RICH_SOURCE_URL)
    assert report.all_urls_safe is (missing_guard is None)
    assert status["is_valid"] is (missing_guard is None)
    unrelated_url = VOICE_RICH_SOURCE_URL + "?private=do-not-allow"
    report = await client.report_malicious_urls(urls=[unrelated_url], assistant_response="fixture")
    assert report.all_urls_safe is False and unrelated_url in report.malicious_urls
    assert (await url_validator.check_url_status(unrelated_url))["is_valid"] is False


def test_speech_context_reuses_encrypted_worker_binary_fixture(isolated):
    from backend.apps.audio.assistant_speech.live_mock import assistant_speech_live_mock_audio

    context = fixture.speech_fixture_context(request(fixture.RAMEN_REQUEST))
    audio = assistant_speech_live_mock_audio(context)
    assert audio.is_file() and len(audio.read_bytes()) > 100


def test_admitted_voice_delivery_survives_api_and_celery_request_serialization():
    from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as APIRequest
    from backend.apps.ai.skills.ask_skill import AskSkillRequest as WorkerRequest
    from backend.shared.python_utils.recent_work_summary_cache import PRIVATE_CONTEXT_FIELDS

    api_request = APIRequest(chat_id="chat", message_id="turn", user_id="owner", user_id_hash="owner-hash",
        voice_mode=True, voice_call_id="active-call", voice_turn_id="issued-turn",
        message_history=[{"role": "user", "content": fixture.RAMEN_REQUEST, "created_at": 1}])
    dispatched = WorkerRequest(**api_request.model_dump(exclude_none=True))
    payload = {key: value for key, value in dispatched.model_dump(exclude_none=True).items()
               if key not in PRIVATE_CONTEXT_FIELDS}
    worker_request = WorkerRequest.model_validate(payload)
    assert worker_request.voice_mode is True
    assert worker_request.voice_call_id == "active-call"
    assert worker_request.voice_turn_id == "issued-turn"
