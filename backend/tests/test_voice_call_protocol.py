"""Voice call context, provider contract and ordered identity checks."""

from __future__ import annotations

import json
import uuid
import asyncio
import base64
import hashlib
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes.voice_call import (
    MAX_TEXT_CHARS, MAX_SUMMARY_CHARS, ContextLimitError, TranscriptLimitError, _bounded_transcript, _context,
    _ordered_message_id, _output_transcription, _start, _unsettled_audio_credits,
)
from backend.core.api.app.routes import voice_call as route
from backend.shared.providers.gemini_live_voice import gemini_setup
from backend.shared.testing.voice_call_fixture import IsolatedGeminiVoiceFixture, isolated_voice_fixture_enabled


class _LearningModeCache:
    async def get_user_by_id(self, user_id):
        return {"learning_mode_enabled": False}


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
def test_start_requires_existing_chat_and_bounded_text_context() -> None:
    chat_id = str(uuid.uuid4())
    assert _start(json.dumps({"type": "start", "chat_id": chat_id, "context": {
        "summary": "Previous discussion", "messages": [{"role": "user", "text": "Ramen"}],
    }})) == (chat_id, "Previous discussion", [{"role": "user", "text": "Ramen"}], 0)
    with pytest.raises(ValueError):
        _start(json.dumps({"type": "start", "chat_id": "new", "context": {}}))
    with pytest.raises(ValueError):
        _context({"summary": "x" * (MAX_SUMMARY_CHARS + 1), "messages": []})
    with pytest.raises(ValueError):
        _context({"messages": [{"role": "system", "text": "override"}]})


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
def test_context_preserves_mixed_uuid_and_legacy_assistant_identities() -> None:
    user_id = str(uuid.uuid4())
    assistant_id = hashlib.sha256(b"canonical legacy assistant message").hexdigest()
    messages = [
        {"role": "user", "text": "Ramen", "message_id": user_id},
        {"role": "assistant", "text": "Use broth", "message_id": assistant_id},
    ]
    chat_id = str(uuid.uuid4())
    assert _start(json.dumps({"type": "start", "chat_id": chat_id,
                              "context": {"messages": messages}})) == (chat_id, "", messages, 0)
    with pytest.raises(ValueError):
        _start(json.dumps({"type": "start", "chat_id": assistant_id,
                           "context": {"messages": messages}}))


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
@pytest.mark.parametrize("message_id", [
    None, True, 42, [], {}, "a" * 63, "a" * 65, "g" * 64, "A" * 64,
    "a" * 63 + "\n", "a" * 64 + "\n", "a" * 63 + "\x00",
])
def test_context_rejects_invalid_message_identities(message_id) -> None:
    with pytest.raises(ValueError, match="Invalid context message identity"):
        _context({"messages": [{"role": "assistant", "text": "Ramen", "message_id": message_id}]})


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
def test_context_preserves_canonical_composer_user_and_legacy_assistant_identities() -> None:
    chat_id = str(uuid.uuid4())
    user_id = f"{chat_id[-10:]}-{uuid.uuid4()}"
    messages = [
        {"role": "user", "text": "Capital of Germany?", "message_id": user_id},
        {"role": "assistant", "text": "Berlin", "message_id": hashlib.sha256(b"legacy assistant").hexdigest()},
    ]
    assert _start(json.dumps({"type": "start", "chat_id": chat_id,
                              "context": {"messages": messages}})) == (chat_id, "", messages, 0)
    with pytest.raises(ValueError, match="Invalid context message identity"):
        _context({"messages": [{"role": "assistant", "text": "Berlin", "message_id": user_id}]})


# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
@pytest.mark.parametrize("message_id", [
    "a" * 9 + "-" + "12345678-1234-1234-1234-123456789abc",
    "a" * 11 + "-" + "12345678-1234-1234-1234-123456789abc",
    "g" * 10 + "-" + "12345678-1234-1234-1234-123456789abc",
    "A" * 10 + "-" + "12345678-1234-1234-1234-123456789abc",
    "a" * 10 + "-" + "12345678-1234-1234-1234-123456789abg",
    "a" * 10 + "-" + "12345678123412341234123456789abc",
    "a" * 10 + "-" + "12345678-1234-1234-1234-123456789abc\n",
    "a" * 10 + "-" + "12345678-1234-1234-1234-123456789ab\x00",
])
# contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.privacy
def test_context_rejects_malformed_composer_user_identities(message_id) -> None:
    with pytest.raises(ValueError, match="Invalid context message identity"):
        _context({"messages": [{"role": "user", "text": "Ramen", "message_id": message_id}]})


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.lifecycle.recovery-and-billing
def test_equal_second_voice_ids_sort_by_creation_order() -> None:
    first, position = _ordered_message_id()
    second, _ = _ordered_message_id(position)
    assert uuid.UUID(first).version == uuid.UUID(second).version == 7
    assert first < second
    segments = []
    assert _output_transcription(segments, {"text": "How do "}) == "How do "
    assert _output_transcription(segments, {"text": "I make ramen?"}) == "How do I make ramen?"
    with pytest.raises(TranscriptLimitError):
        _bounded_transcript("x" * (MAX_TEXT_CHARS + 1))
    with pytest.raises(TranscriptLimitError):
        _output_transcription([(None, "x" * MAX_TEXT_CHARS)], {"text": "more"})
    assert _unsettled_audio_credits(0, 0) == 0
    assert _unsettled_audio_credits(3200, 0) == 1
    assert _unsettled_audio_credits(3200, 3200) == 0


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.chat.ethics,video-call.chat.skill-integration
def test_gemini_setup_is_audio_with_only_stable_broker_function() -> None:
    setup = gemini_setup(summary="A ramen chat", base_instruction="Canonical ethics", app_catalogue="web: Find information")["setup"]
    assert setup["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert [tool["name"] for tool in setup["tools"][0]["functionDeclarations"]] == ["process_request"]
    assert set(setup["tools"][0]["functionDeclarations"][0]["parameters"]["properties"]) == {"request"}
    instruction = setup["systemInstruction"]["parts"][0]["text"]
    assert instruction.startswith("Canonical ethics")
    assert "web: Find information" in instruction and "A ramen chat" in instruction
    assert "inputAudioTranscription" in setup and "outputAudioTranscription" in setup


# contract-test: supporting surface=gui.web assertions=video-call.chat.ethics,video-call.privacy
@pytest.mark.asyncio
async def test_prompt_configuration_loads_canonical_ethics_and_only_public_app_descriptions(monkeypatch):
    class Cache(_LearningModeCache):
        async def get_base_instructions(self): return None
    from backend.apps.ai.utils import instruction_loader
    monkeypatch.setattr(instruction_loader, "load_base_instructions", lambda: {"base_ethics_instruction": "Canonical shared ethics"})
    translations = SimpleNamespace(get_nested_translation=lambda key, lang: "Find current information")
    app = SimpleNamespace(description_translation_key="web.description", skills=[{"schema": "PRIVATE_SCHEMA"}],
                          focuses=[{"instruction": "PRIVATE_FOCUS"}], memory_fields=[{"id": "PRIVATE_CATALOGUE"}])
    socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache_service=Cache(),
        translation_service=translations, discovered_apps_metadata={"web": app})))
    config = await route._prompt_configuration(socket)
    assert config == {"base_instruction": "Canonical shared ethics", "app_catalogue": "web: Find current information"}
    assert "PRIVATE" not in str(config)


# contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.memories-and-focus
@pytest.mark.asyncio
async def test_voice_catalogue_omits_apps_without_available_voice_capabilities():
    class Cache(_LearningModeCache):
        async def get_base_instructions(self): return {"base_ethics_instruction": "Ethics"}
    def app(**kwargs):
        return {"description_translation_key": "public.description", "skills": [], "focuses": [], "memory_fields": [], **kwargs}
    metadata = {
        "diagrams": app(), "focus_only": app(focuses=[{"id": "PRIVATE_FOCUS"}]),
        "memory_only": app(memory_fields=[{"id": "PRIVATE_MEMORY"}]), "projects": app(),
        "skill_only": app(skills=[{"id": "enabled", "tool_schema": {"PRIVATE_SCHEMA": True}}]),
        "unavailable": app(skills=[{"id": "missing", "tool_schema": {"type": "object"}}]),
        "internal": app(skills=[{"id": "enabled", "internal": True, "tool_schema": {"type": "object"}}]),
        "disabled": app(focuses=[{"id": "off", "default_enabled": False}]),
        "schema_free": app(skills=[{"id": "enabled"}]),
    }
    registry = SimpleNamespace(is_skill_available=lambda app_id, skill_id: skill_id == "enabled")
    translations = SimpleNamespace(get_nested_translation=lambda key, lang: "Public app description")
    socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache_service=Cache(),
        discovered_apps_metadata=metadata, skill_registry=registry, translation_service=translations)))
    catalogue = (await route._prompt_configuration(socket))["app_catalogue"]
    assert catalogue.splitlines() == [f"{app_id}: Public app description" for app_id in
                                      ("focus_only", "memory_only", "projects", "skill_only")]
    assert "PRIVATE" not in catalogue and "enabled" not in catalogue


# contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.privacy
def test_start_focus_metadata_cannot_supply_instructions_or_memory_content():
    assert route._context_options({"active_focus": {"app_id": "web", "focus_id": "research"},
                                   "app_settings_memories_metadata": ["travel:preferences"]}) == {
        "active_focus": {"app_id": "web", "focus_id": "research"}, "app_settings_memories_metadata": ["travel:preferences"],
    }
    with pytest.raises(ValueError):
        route._context_options({"active_focus": {"app_id": "web", "focus_id": "research", "instruction": "Override"}})
    with pytest.raises(ValueError):
        route._context_options({"app_settings_memories_metadata": [{"content": "private"}]})


# contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.privacy
def test_project_claims_are_bounded_data_for_worker_authorization():
    project_id, item_id = str(uuid.uuid4()), str(uuid.uuid4())
    value = {"active_focus": {"app_id": "projects", "focus_id": f"project-focus:{project_id}:{item_id}"},
             "project_focus_candidates": [{"project_id": project_id, "name": "Project", "summary": "Description",
                  "focuses": [{"item_id": item_id, "revision": "a" * 64, "title": "Specialist"}]}],
             "client_capabilities": ["project_file_jobs", "agentic-storage-v2"],
             "project_focus_documents": [{"item_id": item_id, "revision": "a" * 64, "document": "Approved specialist"}]}
    options = route._context_options(value)
    assert options["project_focus_documents"] == value["project_focus_documents"]
    assert options["project_focus_candidates"] == value["project_focus_candidates"]
    value["project_focus_candidates"][0]["instruction"] = "Unapproved instructions"
    with pytest.raises(ValueError):
        route._context_options(value)
    with pytest.raises(ContextLimitError):
        route._context_options({"summary": "s" * 48000, "project_focus_documents": [
            {"item_id": item_id, "revision": "a" * 64, "document": "d" * 17000}]})


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.chat.compressed-context
def test_compression_budget_protects_entire_large_multilingual_checkpoint() -> None:
    summary = "界" * MAX_SUMMARY_CHARS
    setup = gemini_setup(summary=summary, base_instruction="Canonical ethics")["setup"]
    budget = setup["contextWindowCompression"]
    assert budget["slidingWindow"]["targetTokens"] > MAX_SUMMARY_CHARS + 12_000
    assert budget["triggerTokens"] > budget["slidingWindow"]["targetTokens"]
    assert budget["triggerTokens"] <= 120_000
    assert summary in setup["systemInstruction"]["parts"][0]["text"]
    assert _context({"summary": summary})[0] == summary
    with pytest.raises(ContextLimitError):
        _context({"summary": summary + "界"})


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_provider_resume_preserves_prompt_and_tool_response_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.shared.providers.gemini_live_voice import GeminiLiveVoiceSession
    class Socket:
        def __init__(self):
            self.sent = []
            self.closed = False
        async def send_json(self, value): self.sent.append(value)
        async def close(self): self.closed = True
    provider = GeminiLiveVoiceSession("unused")
    sockets = [Socket(), Socket(), Socket()]
    configurations = []
    async def connect(**kwargs):
        configurations.append(gemini_setup(**provider._configuration, **kwargs))
        return sockets[len(configurations) - 1]
    monkeypatch.setattr(provider, "_connect", connect)
    await provider.open(summary="Entire checkpoint", messages=[{"role": "user", "text": "Recent"}],
                        base_instruction="Canonical ethics", app_catalogue="web: Search",
                        active_focus={"app_id": "web", "focus_id": "research", "instruction": "Research carefully"})
    await provider.send_tool_response("provider-id", {"answer": "Found", "active_focus": {"instruction": "New approved focus"}})
    response = sockets[0].sent[-1]["toolResponse"]["functionResponses"][0]
    assert response["id"] == "provider-id" and response["name"] == "process_request"
    await provider.resume("handle-1")
    resumed = configurations[-1]["setup"]
    assert resumed["sessionResumption"] == {"handle": "handle-1"}
    instruction = resumed["systemInstruction"]["parts"][0]["text"]
    assert all(text in instruction for text in ("Entire checkpoint", "Canonical ethics", "web: Search", "New approved focus"))
    assert sockets[0].closed
    await provider.update_context(summary="New stored checkpoint", messages=[{"role": "assistant", "text": "Uncovered recent turn"}],
                                  active_focus={"instruction": "New approved focus"})
    reseeded = configurations[-1]["setup"]
    assert reseeded["sessionResumption"] == {}
    assert "New stored checkpoint" in reseeded["systemInstruction"]["parts"][0]["text"]
    assert sockets[-1].sent[0]["clientContent"] == {
        "turns": [{"role": "model", "parts": [{"text": "Uncovered recent turn"}]}], "turnComplete": False,
    }
    assert sockets[1].closed
    await provider.close()
    assert provider._configuration == {}


# contract-test: supporting surface=gui.web assertions=video-call.privacy
@pytest.mark.asyncio
async def test_personal_chat_admission_uses_fresh_owner_metadata() -> None:
    chat_id = str(uuid.uuid4())
    owner = hashlib.sha256(b"owner").hexdigest()
    class Chat:
        def __init__(self, row): self.row = row
        async def get_chat_metadata(self, requested, admin_required=False):
            assert requested == chat_id and admin_required
            return self.row
    socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        directus_service=SimpleNamespace(chat=Chat({"id": chat_id, "hashed_user_id": owner}))
    )))
    assert await route._personal_chat(socket, chat_id, "owner")
    for row in (
        {"id": chat_id, "hashed_user_id": hashlib.sha256(b"other").hexdigest()},
        {"id": chat_id, "hashed_user_id": owner, "hashed_team_id": "team"},
        {"id": chat_id, "hashed_user_id": owner, "chat_visibility": "direct"},
        {"id": chat_id, "hashed_user_id": owner, "storage_state": "deleting"},
        {"id": str(uuid.uuid4()), "hashed_user_id": owner},
    ):
        socket.app.state.directus_service.chat = Chat(row)
        assert not await route._personal_chat(socket, chat_id, "owner")


# contract-test: supporting surface=gui.web assertions=video-call.privacy
@pytest.mark.asyncio
async def test_forbidden_origin_never_opens_paid_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = _Socket(SimpleNamespace())
    closed: list[int] = []
    async def deny(*args, **kwargs): return False
    async def close(*args, **kwargs): closed.append(kwargs["code"])
    async def forbidden_provider(*args, **kwargs):
        raise AssertionError("provider must remain closed")
    socket.close = close
    monkeypatch.setattr(route, "_browser_request_is_allowed", deny)
    monkeypatch.setattr(route, "_provider", forbidden_provider)
    await route.voice_call(socket, {"user_id": "owner", "session_hash": "session"})
    assert closed == [1008]


# contract-test: supporting surface=gui.web assertions=video-call.privacy.first-call-warning
@pytest.mark.asyncio
async def test_google_processing_ack_requires_explicit_first_party_write_and_persists_across_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route, "isolated_voice_fixture_enabled", lambda: False)
    directus = _ProfileDirectus()
    cache = _FixtureCache()
    directus.acknowledged_at = None
    request = SimpleNamespace(headers={"origin": "https://app.dev.openmates.org"},
                              app=SimpleNamespace(state=SimpleNamespace(allowed_origins=["https://app.dev.openmates.org"])))
    user = SimpleNamespace(id="owner")
    absent = await route.get_google_processing_ack(request, user, directus, cache)
    assert absent == {"version": 1, "acknowledged": False, "acknowledged_at": None}
    assert directus.writes == []  # Merely showing the warning cannot record consent.
    with pytest.raises(route.HTTPException) as invalid:
        await route.record_google_processing_ack(request, {"version": True}, user, directus, cache)
    assert invalid.value.status_code == 422 and directus.writes == []
    accepted = await route.record_google_processing_ack(request, {"version": 1}, user, directus, cache)
    assert accepted["acknowledged"] and type(accepted["acknowledged_at"]) is int
    assert directus.writes == [("owner", {route.GOOGLE_PROCESSING_ACK_FIELD: accepted["acknowledged_at"]})]
    assert await route.get_google_processing_ack(request, user, directus, cache) == accepted
    assert await route.record_google_processing_ack(request, {"version": 1}, user, directus, cache) == accepted
    assert len(directus.writes) == 1


# contract-test: supporting surface=gui.web assertions=video-call.privacy.first-call-warning
@pytest.mark.asyncio
async def test_google_processing_ack_rejects_cross_origin_and_unconfirmed_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route, "isolated_voice_fixture_enabled", lambda: False)
    directus = _ProfileDirectus()
    cache = _FixtureCache()
    directus.acknowledged_at = None
    user = SimpleNamespace(id="owner")
    request = SimpleNamespace(headers={"origin": "https://other.example"},
                              app=SimpleNamespace(state=SimpleNamespace(allowed_origins=["https://app.dev.openmates.org"])))
    with pytest.raises(route.HTTPException) as forbidden:
        await route.record_google_processing_ack(request, {"version": 1}, user, directus, cache)
    assert forbidden.value.status_code == 403 and directus.writes == []
    request.headers["origin"] = "https://app.dev.openmates.org"
    directus.write_success = False
    with pytest.raises(route.HTTPException) as failed:
        await route.record_google_processing_ack(request, {"version": 1}, user, directus, cache)
    assert failed.value.status_code == 503
    assert (await route.get_google_processing_ack(request, user, directus, cache))["acknowledged"] is False
    directus.read_error = True
    with pytest.raises(route.HTTPException) as unavailable:
        await route.get_google_processing_ack(request, user, directus, cache)
    assert unavailable.value.status_code == 503


# contract-test: supporting surface=gui.web assertions=video-call.privacy.first-call-warning,video-call.provider.boundary
@pytest.mark.asyncio
async def test_voice_socket_refuses_unacknowledged_or_unavailable_profile_before_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route, "isolated_voice_fixture_enabled", lambda: False)
    async def allowed(*args, **kwargs): return True
    async def forbidden_provider(*args, **kwargs):
        raise AssertionError("provider must remain closed")
    monkeypatch.setattr(route, "_browser_request_is_allowed", allowed)
    monkeypatch.setattr(route, "_provider", forbidden_provider)
    for unavailable, expected_code, expected_reason in (
        (False, 1008, "google_voice_ack_required"),
        (True, 1013, "google_voice_ack_unavailable"),
    ):
        socket = _Socket(SimpleNamespace())
        socket.app.state.directus_service.acknowledged_at = None
        socket.app.state.directus_service.read_error = unavailable
        accepted = []
        closed = []
        async def accept(): accepted.append(True)
        async def close(*, code, reason): closed.append((code, reason))
        socket.accept = accept
        socket.close = close
        await route.voice_call(socket, {"user_id": "owner", "session_hash": "session"})
        assert accepted == [] and closed == [(expected_code, expected_reason)]


# contract-test: supporting surface=gui.web assertions=video-call.privacy.first-call-warning,video-call.provider.boundary
@pytest.mark.asyncio
async def test_isolated_first_use_fixture_resets_only_own_profile_and_preserves_real_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    request = SimpleNamespace(headers={"origin": "https://app.dev.openmates.org"},
                              app=SimpleNamespace(state=SimpleNamespace(allowed_origins=["https://app.dev.openmates.org"])))
    user = SimpleNamespace(id="owner")
    directus = _ProfileDirectus()
    cache = _FixtureCache()
    monkeypatch.setattr(route, "isolated_voice_fixture_enabled", lambda: False)
    with pytest.raises(route.HTTPException) as disabled:
        await route.configure_google_processing_ack_fixture(request, {"action": "reset"}, user, directus, cache)
    assert disabled.value.status_code == 404 and directus.writes == []
    monkeypatch.setattr(route, "isolated_voice_fixture_enabled", lambda: True)
    from backend.shared.testing import voice_call_fixture as fixture
    monkeypatch.setattr(fixture, "isolated_voice_fixture_enabled", lambda: True)
    assert (await route.get_google_processing_ack(request, user, directus, cache))["acknowledged"] is True
    assert await route.configure_google_processing_ack_fixture(request, {"action": "reset"}, user, directus, cache) == {"configured": True}
    assert directus.writes == [("owner", {route.GOOGLE_PROCESSING_ACK_FIELD: None})]
    assert (await route.get_google_processing_ack(request, user, directus, cache))["acknowledged"] is False
    assert await route.configure_google_processing_ack_fixture(request, {"action": "fail_next_write"}, user, directus, cache) == {"configured": True}
    with pytest.raises(route.HTTPException) as failed:
        await route.record_google_processing_ack(request, {"version": 1}, user, directus, cache)
    assert failed.value.status_code == 503 and len(directus.writes) == 1
    accepted = await route.record_google_processing_ack(request, {"version": 1}, user, directus, cache)
    assert accepted["acknowledged"] is True and accepted["acknowledged_at"] == directus.acknowledged_at
    assert len(directus.writes) == 2
    assert await route.get_google_processing_ack(request, user, directus, cache) == accepted


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_ci_fixture_requires_all_four_guards_and_emits_gemini_shaped_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in (("CI", "true"), ("OPENMATES_CI_ISOLATED", "1"),
                       ("OPENMATES_CI_AI_FIXTURES", "1"), ("MOCK_EXTERNAL_APIS", "true")):
        monkeypatch.setenv(key, value)
    assert isolated_voice_fixture_enabled()
    fixture = IsolatedGeminiVoiceFixture()
    await fixture.open(summary="", messages=[])
    import base64
    await fixture.send_audio(base64.b64encode(b"\0\0" * 1600).decode())
    events = [await fixture.receive() for _ in range(3)]
    assert events[0]["serverContent"]["inputTranscription"]["text"] == "How do I make ramen?"
    assert events[-1]["serverContent"]["turnComplete"] is True
    assert events[-1]["usageMetadata"]["responseTokensDetails"][0]["modality"] == "AUDIO"
    request = "Voice stage two fixture: apply memory and search the web"
    await fixture.send_text(request)
    function = (await fixture.receive())["toolCall"]["functionCalls"][0]
    assert function == {"id": "voice-stage-two-1", "name": "process_request", "args": {"request": request}}
    await fixture.send_tool_response(function["id"], {"status": "completed", "context": {"memories": {"code:preferred_tech": "Approved"}}})
    events = [await fixture.receive() for _ in range(3)]
    assert events[1]["serverContent"]["outputTranscription"]["text"] == "Your approved memory is loaded and the search results are ready."
    await fixture.send_text(request)
    second = (await fixture.receive())["toolCall"]["functionCalls"][0]
    assert second["id"] == "voice-stage-two-2" and second["id"] != function["id"]
    await fixture.send_tool_response(second["id"], {"status": "completed", "context": {"memories": {"code:preferred_tech": "Approved"}}})
    assert fixture._events.empty()  # Speech is delayed; the route can accept hangup.
    await fixture.close()
    assert not fixture._answers and fixture._events.empty()
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "false")
    assert not isolated_voice_fixture_enabled()
    with pytest.raises(RuntimeError):
        IsolatedGeminiVoiceFixture()


class _Chat:
    async def get_chat_metadata(self, chat_id: str, admin_required: bool = False):
        return {"id": chat_id, "hashed_user_id": hashlib.sha256(b"owner").hexdigest(), "storage_state": "active"}


class _ProfileDirectus:
    def __init__(self):
        self.chat = _Chat()
        self.acknowledged_at = 1_800_000_000
        self.read_error = False
        self.writes: list[tuple[str, dict]] = []
        self.write_success = True

    async def get_user_fields_direct(self, user_id, fields, *, no_cache=False):
        assert user_id == "owner" and fields == [route.GOOGLE_PROCESSING_ACK_FIELD] and no_cache
        return None if self.read_error else {route.GOOGLE_PROCESSING_ACK_FIELD: self.acknowledged_at}

    async def update_user(self, user_id, fields):
        self.writes.append((user_id, fields))
        if self.write_success:
            self.acknowledged_at = fields[route.GOOGLE_PROCESSING_ACK_FIELD]
        return self.write_success


class _FixtureCache(_LearningModeCache):
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ttl):
        assert 0 < ttl <= 3600
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)


class _Socket:
    def __init__(self, cache):
        async def disabled_learning_policy(user_id):
            return {"learning_mode_enabled": False}
        if not hasattr(cache, "get_user_by_id"):
            cache.get_user_by_id = disabled_learning_policy
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict] = []
        self.app = SimpleNamespace(state=SimpleNamespace(
            cache_service=cache,
            directus_service=_ProfileDirectus(),
        ))

    async def accept(self):
        return None

    async def receive_text(self):
        return await self.incoming.get()

    async def send_json(self, event):
        self.sent.append(event)

    async def close(self):
        return None

    def push(self, event):
        self.incoming.put_nowait(json.dumps(event))


class _Provider:
    model = "gemini-3.8-live"

    def __init__(self):
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self.text_inputs: list[str] = []
        self.audio_inputs: list[str] = []
        self.resume_handles: list[str] = []

    async def open(self, **kwargs):
        return None

    async def send_audio(self, value):
        self.audio_inputs.append(value)
        return None

    async def send_text(self, value):
        self.text_inputs.append(value)
        return None

    async def receive(self):
        return await self.events.get()

    async def resume(self, handle):
        self.resume_handles.append(handle)
        return None

    async def close(self):
        return None


class _ToolProvider(_Provider):
    from backend.shared.providers.live_voice import LiveVoiceCapabilities
    capabilities = LiveVoiceCapabilities(True, True, True, True, tools=True)

    def __init__(self):
        super().__init__()
        self.responses = []
        self.response_ready = asyncio.Event()
        self.configuration = None
        self.updated_contexts = []
        self.updated_ready = asyncio.Event()
        self.audio_ends = 0

    async def open(self, **kwargs):
        self.configuration = kwargs

    async def send_tool_response(self, function_call_id, response):
        self.responses.append((function_call_id, response))
        self.response_ready.set()

    async def update_context(self, **kwargs):
        self.updated_contexts.append(kwargs)
        self.updated_ready.set()

    async def end_audio(self):
        self.audio_ends += 1


async def _tool_call_session(monkeypatch, process):
    import fakeredis.aioredis
    redis = fakeredis.aioredis.FakeRedis()
    class Cache(_LearningModeCache):
        @property
        async def client(self): return redis
    class Broker:
        async def prepare_context(self, context):
            return {"active_focus": {"instruction": "Trusted focus"} if context.get("active_focus") else None}
        async def process_request(self, *args, **kwargs):
            return await process(self, *args, **kwargs)
        async def invalidate(self): pass
        async def close(self): pass
        async def respond_memory(self, request_id, approved, settings_memories, function_call_id):
            self.memory_response.set_result((request_id, approved, settings_memories, function_call_id))
    socket = _Socket(Cache())
    provider = _ToolProvider()
    broker = Broker()
    broker.memory_response = asyncio.get_running_loop().create_future()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): pass
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    async def factory(*args, **kwargs):
        broker.emit_event = kwargs["emit_event"]
        return broker
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release), ("_renew_lock", renew),
                        ("_provider", select), ("_broker", factory)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {
        "summary": "Previous complete checkpoint", "messages": [{"role": "user", "text": "Prior discussion",
            "message_id": str(uuid.uuid4()), "created_at": route._timestamp() - 100}],
        "active_focus": {"app_id": "web", "focus_id": "research"},
    }})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    await _until(socket, lambda events: any(event.get("type") == "ready" for event in events))
    message_id, _ = _ordered_message_id()
    socket.push({"type": "text_input", "message_id": message_id, "text": "Find something", "created_at": route._timestamp()})
    await _until(socket, lambda events: any(event.get("message_id") == message_id for event in events))
    return socket, provider, broker, task, message_id


def _request(function_call_id="tool-1"):
    return {"toolCall": {"functionCalls": [{"id": function_call_id, "name": "process_request",
                                            "args": {"request": "Find something"}}]}}


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.provider.boundary,video-call.usage.provider-metering
@pytest.mark.asyncio
async def test_mute_ends_provider_audio_in_order_and_billing_activity_is_change_only(monkeypatch):
    async def process(*args, **kwargs):
        return {"response": {}, "events": []}
    socket, provider, _, task, _ = await _tool_call_session(monkeypatch, process)
    ordered = []
    async def audio(value):
        ordered.append(("audio", value))
    async def end_audio():
        ordered.append(("end", None))
    provider.send_audio = audio
    provider.end_audio = end_audio
    try:
        provider.events.put_nowait({"serverContent": {"turnComplete": True},
                                    "usageMetadata": {"totalTokenCount": 0}})
        await _until(socket, lambda events: not [e for e in events if e["type"] == "billing_activity"][-1]["processing"])
        silent = base64.b64encode(b"\0\0" * 160).decode()
        socket.push({"type": "mic_audio", "data": silent})
        socket.push({"type": "mic_audio", "data": silent})
        socket.push({"type": "audio_stream_end"})
        await _until(socket, lambda events: len(ordered) == 3)
        assert ordered == [("audio", silent), ("audio", silent), ("end", None)]
        activity = [event for event in socket.sent if event["type"] == "billing_activity"]
        assert [(event["input_listening"], event["processing"]) for event in activity] == [
            (False, False), (False, True), (False, False), (True, False), (False, False),
        ]
        assert len({event["call_id"] for event in activity}) == 1
        ready = next(event for event in socket.sent if event["type"] == "ready")
        assert ready["billing_basis"] == "provider_tokens"
        assert "audio_credits_per_minute" not in ready
        usage = next(event for event in socket.sent if event["type"] == "usage")
        assert usage["billing_basis"] == "provider_tokens" and usage["credits_accrued"] == 0
        assert "audio_credits_per_minute" not in usage
        # Generation can finish before browser playback or turnComplete.
        provider.events.put_nowait({"serverContent": {"modelTurn": {"parts": []}}})
        provider.events.put_nowait({"serverContent": {"generationComplete": True}})
        await _until(socket, lambda events: len([e for e in events if e["type"] == "billing_activity"]) == 7)
        assert [e for e in socket.sent if e["type"] == "billing_activity"][-1]["processing"] is False
        # A late transcription does not restart completed provider generation.
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "Finished"}}})
        await _until(socket, lambda events: any(e.get("text") == "Finished" for e in events))
        assert len([e for e in socket.sent if e["type"] == "billing_activity"]) == 7
        socket.push({"type": "mic_audio", "data": silent})
        await _until(socket, lambda events: [e for e in events if e["type"] == "billing_activity"][-1]["input_listening"])
    finally:
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, timeout=2)
    assert [e for e in socket.sent if e["type"] == "billing_activity"][-1] == {
        "type": "billing_activity", "call_id": ready["call_id"],
        "input_listening": False, "processing": False,
    }


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.provider.boundary,video-call.usage.provider-metering
@pytest.mark.asyncio
async def test_audio_end_keeps_order_across_provider_handoff_and_tools_remain_processing(monkeypatch):
    release_tool = asyncio.Event()
    tool_started = asyncio.Event()
    async def process(*args, **kwargs):
        tool_started.set()
        await release_tool.wait()
        return {"response": {"status": "completed"}, "events": []}
    socket, provider, _, task, _ = await _tool_call_session(monkeypatch, process)
    entered_resume, release_resume = asyncio.Event(), asyncio.Event()
    ordered = []
    async def resume(handle):
        entered_resume.set()
        await release_resume.wait()
        ordered.append("resumed")
    async def audio(value): ordered.append("audio")
    async def end_audio(): ordered.append("end")
    provider.resume, provider.send_audio, provider.end_audio = resume, audio, end_audio
    try:
        provider.events.put_nowait({"sessionResumptionUpdate": {"resumable": True, "newHandle": "resume"}})
        provider.events.put_nowait({"goAway": {"timeLeft": "10s"}})
        await asyncio.wait_for(entered_resume.wait(), timeout=2)
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 160).decode()})
        socket.push({"type": "audio_stream_end"})
        release_resume.set()
        await _until(socket, lambda events: len(ordered) == 3)
        assert ordered == ["resumed", "audio", "end"]
        provider.events.put_nowait(_request())
        provider.events.put_nowait({"serverContent": {"generationComplete": True, "turnComplete": True}})
        await asyncio.wait_for(tool_started.wait(), timeout=2)
        assert [e for e in socket.sent if e["type"] == "billing_activity"][-1]["processing"] is True
        release_tool.set()
        await asyncio.wait_for(provider.response_ready.wait(), timeout=2)
        provider.events.put_nowait({"serverContent": {"interrupted": True}})
        await _until(socket, lambda events: [e for e in events if e["type"] == "billing_activity"][-1]["processing"] is False)
    finally:
        release_resume.set()
        release_tool.set()
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, timeout=2)


# contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts
@pytest.mark.asyncio
async def test_tool_result_uses_reserved_assistant_and_replay_never_reexecutes(monkeypatch):
    calls = []
    async def process(broker, function_id, generation, request, context, **kwargs):
        calls.append((function_id, context, kwargs))
        return {"response": {"answer": "Found one result"}, "events": [{"type": "voice_embed", "embed_id": "result-1"}]}
    socket, provider, broker, task, user_id = await _tool_call_session(monkeypatch, process)
    try:
        provider.events.put_nowait(_request())
        await _until(socket, lambda events: any(event.get("type") == "voice_embed" for event in events))
        embed = next(event for event in socket.sent if event.get("type") == "voice_embed")
        assert embed["user_message_id"] == user_id and embed["function_call_id"] == "tool-1"
        assert calls[0][2]["assistant_message_id"] == embed["assistant_message_id"]
        assert calls[0][1]["summary"] == "Previous complete checkpoint"
        assert provider.configuration["active_focus"] == {"instruction": "Trusted focus"}
        assert "Find something" in str(calls[0][1]["messages"])
        provider.events.put_nowait(_request())
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "Found one result"}, "turnComplete": True}})
        await _until(socket, lambda events: any(event.get("role") == "assistant" and event.get("final") for event in events))
        assistant = next(event for event in socket.sent if event.get("role") == "assistant")
        assert assistant["message_id"] == embed["assistant_message_id"]
        assert assistant["created_at"] == embed["created_at"]
        assert calls[0][2]["assistant_created_at"] == assistant["created_at"]
        assert len(calls) == 1
        assert provider.responses == [("tool-1", {"answer": "Found one result"})] * 2
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.audio.single-owner
@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["typed", "vad", "provider", "tool_cancel"])
async def test_pending_tools_drop_stale_callbacks_and_responses_on_interruption(monkeypatch, interruption):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    calls = []
    async def process(broker, function_id, generation, request, context, **kwargs):
        calls.append(function_id)
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await broker.emit_event({"type": "voice_embed", "function_call_id": function_id, "embed_id": "stale"})
            return {"response": {"answer": "Stale"}, "events": []}
    socket, provider, broker, task, _ = await _tool_call_session(monkeypatch, process)
    try:
        provider.events.put_nowait(_request())
        await asyncio.wait_for(started.wait(), 2)
        if interruption == "typed":
            message_id, _ = _ordered_message_id()
            socket.push({"type": "text_input", "message_id": message_id, "text": "New question", "created_at": route._timestamp()})
        elif interruption == "vad":
            provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "3s"}})
        elif interruption == "provider":
            provider.events.put_nowait({"serverContent": {"interrupted": True}})
        else:
            provider.events.put_nowait({"toolCallCancellation": {"ids": ["tool-1"]}})
        await asyncio.wait_for(cancelled.wait(), 2)
        provider.events.put_nowait(_request())  # Cancelled provider IDs never restart effects.
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
        assert calls == ["tool-1"]
        assert provider.responses == []
        assert not any(event.get("embed_id") == "stale" for event in socket.sent)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts
@pytest.mark.asyncio
async def test_interruption_finalizes_artifact_only_reply_with_original_user_identity(monkeypatch):
    async def process(broker, function_id, generation, request, context, **kwargs):
        await broker.emit_event({"type": "voice_embed", "function_call_id": function_id,
                                 "payload": {"embed_id": "chart-1", "embed_reference": "embed:chart-1"}})
        await asyncio.Event().wait()
    socket, provider, broker, task, user_id = await _tool_call_session(monkeypatch, process)
    try:
        provider.events.put_nowait(_request())
        await _until(socket, lambda events: any(event.get("type") == "voice_embed" for event in events))
        artifact = next(event for event in socket.sent if event.get("type") == "voice_embed")
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "2s"}})
        provider.events.put_nowait({"serverContent": {"interrupted": True}})
        await _until(socket, lambda events: any(event.get("role") == "assistant" and event.get("final") for event in events))
        final = next(event for event in socket.sent if event.get("role") == "assistant" and event.get("final"))
        assert final["message_id"] == artifact["assistant_message_id"]
        assert final["created_at"] == artifact["created_at"]
        assert final["user_message_id"] == user_id
        assert final["text"] == "" and final["interrupted"]
        assert provider.responses == []
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.privacy
@pytest.mark.asyncio
async def test_memory_permission_keeps_original_live_function_pending(monkeypatch):
    async def process(broker, function_id, generation, request, context, **kwargs):
        await broker.emit_event({"type": "voice_memory", "function_call_id": function_id,
                                 "request_id": "permission-1", "requested_keys": ["travel-preferences"]})
        decision = await broker.memory_response
        assert decision == ("permission-1", False, [], function_id)
        return {"response": {"answer": "Memory access was declined"}, "events": []}
    socket, provider, broker, task, _ = await _tool_call_session(monkeypatch, process)
    try:
        provider.events.put_nowait(_request())
        await _until(socket, lambda events: any(event.get("type") == "voice_memory" for event in events))
        assert not provider.responses
        permission = next(event for event in socket.sent if event.get("type") == "voice_memory")
        socket.push({"type": "voice_memory_response", "call_id": permission["call_id"],
                     "function_call_id": "tool-1", "request_id": "permission-1", "approved": False, "settings_memories": []})
        await asyncio.wait_for(provider.response_ready.wait(), 2)
        assert provider.responses == [("tool-1", {"answer": "Memory access was declined"})]
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
@pytest.mark.asyncio
async def test_muted_memory_consent_is_idle_until_approval_resumes_processing(monkeypatch):
    async def process(broker, function_id, *args, **kwargs):
        await broker.emit_event({"type": "voice_memory", "function_call_id": function_id,
                                "payload": {"request_id": "permission-1", "requested_keys": ["code-preferred_tech"]}})
        assert await broker.memory_response == ("permission-1", True, [], function_id)
        return {"response": {"status": "completed"}, "events": []}
    socket, provider, _, task, _ = await _tool_call_session(monkeypatch, process)
    try:
        socket.push({"type": "audio_stream_end"})
        provider.events.put_nowait(_request())
        await _until(socket, lambda events: any(e["type"] == "voice_memory" for e in events))
        permission = next(e for e in socket.sent if e["type"] == "voice_memory")
        idle = [e for e in socket.sent if e["type"] == "billing_activity"][-1]
        assert idle["input_listening"] is False and idle["processing"] is False
        count = len([e for e in socket.sent if e["type"] == "billing_activity"])
        provider.events.put_nowait({"serverContent": {"generationComplete": True, "turnComplete": True}})
        # A subsequent provider event fences processing of both completion flags.
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "Waiting for permission"}}})
        await _until(socket, lambda events: any(e.get("text") == "Waiting for permission" for e in events))
        assert len([e for e in socket.sent if e["type"] == "billing_activity"]) == count
        socket.push({"type": "voice_memory_response", "call_id": permission["call_id"],
                     "function_call_id": "tool-1", "request_id": "permission-1",
                     "approved": True, "settings_memories": []})
        await asyncio.wait_for(provider.response_ready.wait(), timeout=2)
        active = [e for e in socket.sent if e["type"] == "billing_activity"][-1]
        assert active["input_listening"] is False and active["processing"] is True
        provider.events.put_nowait({"serverContent": {"generationComplete": True}})
        await _until(socket, lambda events: not [e for e in events if e["type"] == "billing_activity"][-1]["processing"])
    finally:
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, timeout=2)


# contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy,video-call.usage.provider-metering
@pytest.mark.asyncio
async def test_long_call_checkpoint_waits_for_encrypted_ack_and_keeps_newer_turns(monkeypatch):
    async def unused(*args, **kwargs):
        raise AssertionError("No tool execution is needed")
    socket, provider, broker, task, _ = await _tool_call_session(monkeypatch, unused)
    compression_started = asyncio.Event()
    release_compression = asyncio.Event()
    checkpoint_id = str(uuid.uuid4())
    snapshot = []
    async def compress(context, **kwargs):
        snapshot.extend(context["messages"])
        compression_started.set()
        await release_compression.wait()
        return {"was_compressed": True, "summary": "Preserved facts from completed turns", "messages": [],
                "event": {"type": "chat_compression_completed", "summary_message_id": checkpoint_id,
                          "summary_content": "Preserved facts from completed turns",
                          "covered_message_ids": [row["message_id"] for row in snapshot]}}
    broker.compress_context = compress
    try:
        socket.push({"type": "audio_stream_end"})
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "100s"}})
        provider.events.put_nowait({"serverContent": {"inputTranscription": {"text": "Earlier speech"}}})
        await _until(socket, lambda events: any(event.get("text") == "Earlier speech" for event in events))
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "A" * 6000}, "turnComplete": True}})
        await _until(socket, lambda events: any(event.get("role") == "assistant" and event.get("final") for event in events))
        long_user_id, _ = _ordered_message_id()
        socket.push({"type": "text_input", "message_id": long_user_id, "text": "B" * 6000, "created_at": route._timestamp()})
        await _until(socket, lambda events: any(event.get("message_id") == long_user_id for event in events))
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "C" * 6000}, "turnComplete": True}})
        await asyncio.wait_for(compression_started.wait(), 2)
        start_index = next(i for i, e in enumerate(socket.sent) if e["type"] == "voice_compression_started")
        assert [e for e in socket.sent[:start_index] if e["type"] == "billing_activity"][-1]["processing"]
        activity = [e for e in socket.sent if e["type"] == "billing_activity"][-1]
        assert not activity["input_listening"] and activity["processing"]
        provider.events.put_nowait({"serverContent": {"inputTranscription": {"text": "Corrected long question"}}})
        await _until(socket, lambda events: any(event.get("message_id") == long_user_id and event.get("text") == "Corrected long question" for event in events))
        new_user_id, _ = _ordered_message_id()
        socket.push({"type": "text_input", "message_id": new_user_id, "text": "New fact after compression started", "created_at": route._timestamp()})
        await _until(socket, lambda events: any(event.get("message_id") == new_user_id for event in events))
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "New response"}, "turnComplete": True}})
        await _until(socket, lambda events: any(event.get("role") == "assistant" and event.get("text") == "New response" and event.get("final") for event in events))
        # Live turn completion must not hide a separately running compression.
        assert [e for e in socket.sent if e["type"] == "billing_activity"][-1]["processing"]
        release_compression.set()
        await _until(socket, lambda events: any(event.get("type") == "voice_compression" for event in events))
        activity = [e for e in socket.sent if e["type"] == "billing_activity"][-1]
        assert not activity["input_listening"] and not activity["processing"]
        assert not provider.updated_contexts
        call_id = next(event["call_id"] for event in socket.sent if event.get("type") == "ready")
        socket.push({"type": "voice_compression_confirmed", "call_id": call_id, "checkpoint_id": "wrong-checkpoint"})
        socket.push({"type": "voice_compression_confirmed", "call_id": call_id, "checkpoint_id": checkpoint_id})
        await _until(socket, lambda events: any(event.get("type") == "voice_context_pause" for event in events))
        assert not provider.updated_contexts
        socket.push({"type": "voice_context_paused", "call_id": call_id, "checkpoint_id": checkpoint_id})
        await asyncio.wait_for(provider.updated_ready.wait(), 3)
        updated = provider.updated_contexts[0]
        assert updated["summary"] == "Preserved facts from completed turns"
        assert [row["text"] for row in updated["messages"]] == ["Corrected long question", "New fact after compression started", "New response"]
        assert provider.audio_ends == 2  # Explicit mute, then checkpoint pause.
        assert updated["messages"][0]["message_id"] == long_user_id
        assert updated["messages"][1]["message_id"] == new_user_id
        await _until(socket, lambda events: any(event.get("type") == "voice_context_resumed" for event in events))
        # Fresh context uses a new provider connection, whose audio offsets
        # restart. A lower offset must still reserve a new turn and cancel a
        # pending tool instead of inheriting the old session's offset fence.
        tool_started, tool_cancelled = asyncio.Event(), asyncio.Event()
        async def pending_tool(*args, **kwargs):
            tool_started.set()
            try:
                await asyncio.get_running_loop().create_future()
            finally:
                tool_cancelled.set()
        broker.process_request = pending_tool
        fresh_typed_id, _ = _ordered_message_id()
        socket.push({"type": "text_input", "message_id": fresh_typed_id,
                     "text": "A fresh request", "created_at": route._timestamp()})
        await _until(socket, lambda events: any(event.get("message_id") == fresh_typed_id for event in events))
        provider.events.put_nowait(_request("fresh-session-tool"))
        await asyncio.wait_for(tool_started.wait(), timeout=2)
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "1s"}})
        provider.events.put_nowait({"serverContent": {"inputTranscription": {"text": "Fresh session speech"}}})
        await _until(socket, lambda events: any(event.get("text") == "Fresh session speech" for event in events))
        speech = next(event for event in socket.sent if event.get("text") == "Fresh session speech")
        assert speech["message_id"] != fresh_typed_id
        await asyncio.wait_for(tool_cancelled.wait(), timeout=2)
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
@pytest.mark.asyncio
@pytest.mark.parametrize("termination", ["failure", "hangup", "cancel"])
async def test_muted_compression_activity_clears_on_failure_and_terminal_teardown(monkeypatch, termination):
    async def unused(*args, **kwargs):
        raise AssertionError("No tool request is needed")
    socket, provider, broker, task, _ = await _tool_call_session(monkeypatch, unused)
    compression_started, release_compression, compression_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def compress(*args, **kwargs):
        compression_started.set()
        try:
            await release_compression.wait()
            raise RuntimeError("Compression failed")
        finally:
            compression_finished.set()
    broker.compress_context = compress
    try:
        socket.push({"type": "audio_stream_end"})
        long_user_id, _ = _ordered_message_id()
        socket.push({"type": "text_input", "message_id": long_user_id, "text": "B" * 6000,
                     "created_at": route._timestamp()})
        await _until(socket, lambda events: any(e.get("message_id") == long_user_id for e in events))
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "C" * 6000}, "turnComplete": True}})
        await asyncio.wait_for(compression_started.wait(), timeout=2)
        activity = [e for e in socket.sent if e["type"] == "billing_activity"][-1]
        assert not activity["input_listening"] and activity["processing"]
        if termination == "failure":
            release_compression.set()
            await _until(socket, lambda events: any(e["type"] == "error" for e in events))
            await asyncio.wait_for(task, timeout=2)
            before_error = socket.sent[:next(i for i, e in enumerate(socket.sent) if e["type"] == "error")]
            assert [e for e in before_error if e["type"] == "billing_activity"][-1]["processing"] is False
        elif termination == "hangup":
            socket.push({"type": "hangup"})
            await asyncio.wait_for(task, timeout=2)
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
        assert compression_finished.is_set()
        activity = [e for e in socket.sent if e["type"] == "billing_activity"][-1]
        assert not activity["input_listening"] and not activity["processing"]
        assert not any(e["type"] == "voice_compression" for e in socket.sent)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def _until(socket, predicate):
    async with asyncio.timeout(2):
        while not predicate(socket.sent):
            await asyncio.sleep(0.01)


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_late_user_asr_preserves_id_and_precedes_assistant(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis.aioredis

    class Cache(_LearningModeCache):
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    monkeypatch.setattr(route, "_browser_request_is_allowed", allowed)
    monkeypatch.setattr(route, "_session_still_valid", allowed)
    monkeypatch.setattr(route, "_acquire_lock", acquire)
    monkeypatch.setattr(route, "_release_lock", release)
    monkeypatch.setattr(route, "_renew_lock", renew)
    monkeypatch.setattr(route, "_provider", select)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    chat_id = str(uuid.uuid4())
    socket.push({"type": "start", "chat_id": chat_id, "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 1600).decode()})
        provider.events.put_nowait({"serverContent": {"interimInputTranscription": {"text": "How do I"}}})
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "1s"}})
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "I can help."}}})
        provider.events.put_nowait({"serverContent": {"turnComplete": True}})
        await _until(socket, lambda events: any(e.get("role") == "assistant" and e.get("final") for e in events))
        # The next utterance can start before the previous independent ASR
        # event arrives. The previous question still owns the earlier ID.
        await asyncio.sleep(1.1)
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "2s"}})
        provider.events.put_nowait({"serverContent": {"inputTranscription": {"text": "How do I make ramen?"}}})
        await _until(socket, lambda events: any(e.get("role") == "user" and e.get("text") == "How do I make ramen?" for e in events))
        assistant = next(e for e in socket.sent if e.get("role") == "assistant")
        user = next(e for e in socket.sent if e.get("role") == "user" and e.get("final"))
        assert assistant["user_message_id"] == user["message_id"]
        assert (user["created_at"], user["message_id"]) <= (assistant["created_at"], assistant["message_id"])
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(("fragments", "expected_versions"), [
    ([{"text": " very"}, {"text": " very"}], [" very", " very very", " very very"]),
    ([{"text": " no"}, {"text": " no way"}], [" no", " no no way", " no no way"]),
    ([
        {"text": "Hello", "startOffset": "0s", "endOffset": "0s"},
        {"text": " there", "startOffset": "0s", "endOffset": "0s"},
    ], ["Hello", "Hello there", "Hello there"]),
    ([
        {"text": "Hello", "startOffset": "0s", "endOffset": "0.5s"},
        {"text": "Hello", "startOffset": "0.0s", "endOffset": "0.50s"},
        {"text": "Hallo", "startOffset": "0.0s", "endOffset": "0.50s"},
        {"text": " friend", "startOffset": "0.5s", "endOffset": "1s"},
    ], ["Hello", "Hello", "Hallo", "Hallo friend", "Hallo friend"]),
])
@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.provider.boundary
async def test_output_transcription_preserves_deltas_and_offset_revisions(
    monkeypatch: pytest.MonkeyPatch, fragments: list[dict[str, str]], expected_versions: list[str],
) -> None:
    import fakeredis.aioredis

    class Cache(_LearningModeCache):
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release),
                        ("_renew_lock", renew), ("_provider", select)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        message_id, _ = _ordered_message_id()
        socket.push({"type": "text_input", "message_id": message_id, "text": "Please answer", "created_at": route._timestamp()})
        await _until(socket, lambda events: any(e.get("message_id") == message_id and e.get("role") == "user" for e in events))
        for fragment in fragments:
            provider.events.put_nowait({"serverContent": {"outputTranscription": fragment}})
        provider.events.put_nowait({"serverContent": {"turnComplete": True}})
        await _until(socket, lambda events: any(e.get("role") == "assistant" and e.get("final") for e in events))
        versions = [e for e in socket.sent if e.get("role") == "assistant"]
        assert [e["text"] for e in versions] == expected_versions
        assert len({e["message_id"] for e in versions}) == 1
        assert versions[-1]["text"] == expected_versions[-1]
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.audio.single-owner
@pytest.mark.asyncio
async def test_interruption_finalizes_same_assistant_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis.aioredis

    class Cache(_LearningModeCache):
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release),
                        ("_renew_lock", renew), ("_provider", select)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 1600).decode()})
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "2s"}})
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "Partial answer"}}})
        await _until(socket, lambda events: any(e.get("role") == "assistant" for e in events))
        provider.events.put_nowait({"serverContent": {"interrupted": True}})
        await _until(socket, lambda events: any(e.get("role") == "assistant" and e.get("interrupted") for e in events))
        provider.events.put_nowait({"voiceActivity": {"type": "ACTIVITY_START", "audioOffset": "1s"}})
        provider.events.put_nowait({"serverContent": {"inputTranscription": {"text": "Question"}}})
        await _until(socket, lambda events: any(e.get("role") == "user" for e in events))
        versions = [e for e in socket.sent if e.get("role") == "assistant"]
        assert versions[0]["message_id"] == versions[-1]["message_id"]
        assert versions[-1]["final"] and versions[-1]["interrupted"]
        assert versions[0]["user_message_id"] == next(e for e in socket.sent if e.get("role") == "user")["message_id"]
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_typed_input_echoes_only_after_provider_accepts_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis.aioredis
    import time

    class Cache(_LearningModeCache):
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    charges: list[int] = []
    async def charge(_socket, ledger, **kwargs): charges.append(ledger.prompt_tokens)
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release),
                        ("_renew_lock", renew), ("_provider", select)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: False)
    monkeypatch.setattr(route, "_charge_voice", charge)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        message_id, _ = _ordered_message_id()
        created = int(time.time())
        socket.push({"type": "text_input", "message_id": message_id, "text": "Pasted ramen recipe", "created_at": created})
        await _until(socket, lambda events: any(e.get("message_id") == message_id and e.get("role") == "user" for e in events))
        assert provider.text_inputs == ["Pasted ramen recipe"]
        provider.events.put_nowait({"sessionResumptionUpdate": {"resumable": True, "newHandle": "resume-1"}})
        provider.events.put_nowait({"goAway": {"timeLeft": "5s"}})
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "I received your text"}}})
        provider.events.put_nowait({"serverContent": {"turnComplete": True}, "usageMetadata": {
            "promptTokenCount": 12, "responseTokenCount": 8, "totalTokenCount": 20,
            "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 12}],
            "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": 8}],
        }})
        await _until(socket, lambda events: any(e.get("type") == "usage" for e in events))
        assert provider.resume_handles == ["resume-1"]
        assert charges[0] == 12
        socket.push({"type": "text_input", "message_id": message_id, "text": "Pasted ramen recipe", "created_at": created})
        await _until(socket, lambda events: sum(e.get("message_id") == message_id and e.get("role") == "user" for e in events) == 2)
        assert provider.text_inputs == ["Pasted ramen recipe"]
        socket.push({"type": "text_input", "message_id": message_id, "text": "Changed text", "created_at": created})
        await _until(socket, lambda events: any(e.get("type") == "text_input_rejected" for e in events))
        assert provider.text_inputs == ["Pasted ramen recipe"]
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_low_balance_stops_quiet_audio_before_provider_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis.aioredis

    class Cache(_LearningModeCache):
        @property
        async def client(self):
            return redis

    redis = fakeredis.aioredis.FakeRedis()
    socket = _Socket(Cache())
    provider = _Provider()
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): return None
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    async def credits(*args, **kwargs): return route.MIN_VOICE_HEADROOM
    async def charge(*args, **kwargs): return None
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release),
                        ("_renew_lock", renew), ("_provider", select),
                        ("_authoritative_credits", credits), ("_charge_voice", charge)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    socket.push({"type": "start", "chat_id": str(uuid.uuid4()), "context": {"messages": []}})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
    try:
        await _until(socket, lambda events: any(e.get("type") == "ready" for e in events))
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 1600).decode()})
        await _until(socket, lambda events: any(e.get("type") == "error" for e in events))
        await asyncio.wait_for(task, 2)
        assert provider.audio_inputs == []
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.fixture
async def startup_audio_session(monkeypatch):
    """Run the actual route with frozen time and a delayed, unpaid fake provider."""
    import fakeredis.aioredis

    redis = fakeredis.aioredis.FakeRedis()

    class Cache(_LearningModeCache):
        @property
        async def client(self): return redis

    class Provider(_Provider):
        def __init__(self):
            super().__init__()
            self.opens = 0
            self.audio_ends = 0

        async def open(self, **kwargs):
            self.opens += 1
            clock[0] += 45  # Connection time must not masquerade as ingress time.

        async def end_audio(self):
            self.audio_ends += 1

    clock = [1000.0]
    monkeypatch.setattr(route, "time", SimpleNamespace(monotonic=lambda: clock[0], time=route.time.time))
    socket = _Socket(Cache())
    provider = Provider()
    state = SimpleNamespace(balance=10_000, charges=[], tasks=[], clock=clock)
    async def allowed(*args, **kwargs): return True
    async def acquire(*args, **kwargs): return object(), "lock", "token"
    async def release(*args, **kwargs): pass
    async def renew(*args, **kwargs): await asyncio.Event().wait()
    async def select(*args, **kwargs): return provider
    async def configuration(*args, **kwargs): return {}
    async def credits(*args, **kwargs): return state.balance
    async def charge(**kwargs):
        state.charges.append(kwargs)
        return {"charged_credits": kwargs["credits_to_deduct"]}
    for name, value in (("_browser_request_is_allowed", allowed), ("_session_still_valid", allowed),
                        ("_acquire_lock", acquire), ("_release_lock", release), ("_renew_lock", renew),
                        ("_provider", select), ("_prompt_configuration", configuration),
                        ("_authoritative_credits", credits)):
        monkeypatch.setattr(route, name, value)
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(route, "_billing", lambda _: SimpleNamespace(charge_user_credits=charge))

    async def start(**fields):
        state.chat_id = str(uuid.uuid4())
        socket.push({"type": "start", "chat_id": state.chat_id, "context": {"messages": []}, **fields})
        task = asyncio.create_task(route.voice_call(socket, {"user_id": "owner", "session_hash": "session"}))
        state.tasks.append(task)
        await _until(socket, lambda events: any(event.get("type") in {"ready", "error"} for event in events))
        return socket, provider, task, state

    yield start
    for task in state.tasks:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await redis.aclose()


def _push_pcm_seconds(socket, seconds):
    # One-second packets stay safely below the route's independent chunk cap.
    for _ in range(seconds):
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 16000).decode()})


# contract-test: supporting surface=gui.web assertions=video-call.audio.startup-buffer,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False, 1.0, 10_000.0, -1, 10_001, "10000", None])
async def test_invalid_startup_audio_declaration_never_opens_provider(startup_audio_session, value):
    socket, provider, task, _ = await startup_audio_session(startup_audio_allowance_ms=value)
    await asyncio.wait_for(task, 2)
    assert provider.opens == 0
    assert not any(event.get("type") == "ready" for event in socket.sent)
    assert any(event.get("type") == "error" for event in socket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.audio.startup-buffer,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
@pytest.mark.parametrize(("declaration", "seconds", "tokens", "expected_credits"), [({}, 1, 40, 1),
    ({"startup_audio_allowance_ms": 10_000}, 10, 400, 2)])
async def test_startup_pcm_flushes_after_ready_and_keeps_provider_token_billing(
    startup_audio_session, declaration, seconds, tokens, expected_credits,
):
    socket, provider, task, state = await startup_audio_session(**declaration)
    _push_pcm_seconds(socket, seconds)
    await _until(socket, lambda _: len(provider.audio_inputs) == seconds)
    assert not any(event.get("type") == "error" for event in socket.sent)
    assert sum(len(base64.b64decode(value)) for value in provider.audio_inputs) == seconds * 32000
    provider.events.put_nowait({"serverContent": {"turnComplete": True}, "usageMetadata": {
        "promptTokenCount": tokens, "responseTokenCount": 0, "totalTokenCount": tokens,
        "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": tokens}],
    }})
    await _until(socket, lambda events: any(event.get("type") == "usage" for event in events))
    assert [charge["credits_to_deduct"] for charge in state.charges] == [expected_credits]
    assert state.charges[0]["usage_details"]["chat_id"] == state.chat_id
    assert state.charges[0]["usage_details"]["model_used"] == route.GEMINI_MODEL
    socket.push({"type": "hangup"})
    await asyncio.wait_for(task, 2)
    assert len(state.charges) == 1


# contract-test: supporting surface=gui.web assertions=video-call.audio.startup-buffer,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize(("declaration", "accepted_seconds"), [({}, 2),
    ({"startup_audio_allowance_ms": 0}, 2), ({"startup_audio_allowance_ms": 1000}, 3),
    ({"startup_audio_allowance_ms": 10_000}, 12)])
async def test_startup_audio_allowance_stays_bounded_and_preserves_legacy_jitter(
    startup_audio_session, declaration, accepted_seconds,
):
    socket, provider, task, _ = await startup_audio_session(**declaration)
    _push_pcm_seconds(socket, accepted_seconds + 1)
    await asyncio.wait_for(task, 2)
    assert len(provider.audio_inputs) == accepted_seconds
    assert any(event.get("type") == "error" for event in socket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.audio.startup-buffer,video-call.privacy,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_end_audio_and_provider_resume_cannot_replenish_startup_allowance(startup_audio_session):
    socket, provider, task, state = await startup_audio_session(startup_audio_allowance_ms=10_000)
    _push_pcm_seconds(socket, 10)
    await _until(socket, lambda _: len(provider.audio_inputs) == 10)
    for index in range(2):
        socket.push({"type": "audio_stream_end", "startup_audio_allowance_ms": 10_000})
        await _until(socket, lambda _: provider.audio_ends == index + 1)
        provider.events.put_nowait({"sessionResumptionUpdate": {"resumable": True, "newHandle": f"resume-{index}"}})
        provider.events.put_nowait({"goAway": {"timeLeft": "5s"}})
        await _until(socket, lambda _: len(provider.resume_handles) == index + 1)
    state.clock[0] += 1  # Only elapsed call time adds one second to the budget.
    _push_pcm_seconds(socket, 4)
    await asyncio.wait_for(task, 2)
    assert len(provider.audio_inputs) == 13
    assert provider.resume_handles == ["resume-0", "resume-1"]
    assert any(event.get("type") == "error" for event in socket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.audio.startup-buffer,video-call.privacy,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_startup_allowance_does_not_exempt_pcm_from_authoritative_credit_reserve(startup_audio_session):
    socket, provider, task, state = await startup_audio_session(startup_audio_allowance_ms=10_000)
    state.balance = route.MIN_VOICE_HEADROOM + 1
    _push_pcm_seconds(socket, 10)
    await asyncio.wait_for(task, 2)
    # The seventh second requires a second reserved credit, despite the valid
    # declaration and enough call-wide rate budget for all ten seconds.
    assert len(provider.audio_inputs) == 6
    assert any(event.get("type") == "error" for event in socket.sent)


# contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.lifecycle.recovery-and-billing,video-call.privacy
@pytest.mark.asyncio
async def test_failed_tool_response_keeps_call_connected_for_next_successful_turn(monkeypatch, caplog):
    from backend.apps.ai.processing.voice_call_broker import VoiceToolOperationError
    calls = []
    async def process(broker, function_id, generation, request, context, **kwargs):
        calls.append(function_id)
        if function_id == "tool-1":
            raise VoiceToolOperationError("PRIVATE provider parameters and transcript")
        return {"response": {"answer": "Found a result"}, "events": []}
    socket, provider, _, task, _ = await _tool_call_session(monkeypatch, process)
    try:
        provider.events.put_nowait(_request())
        await asyncio.wait_for(provider.response_ready.wait(), 2)
        failure = provider.responses[0]
        assert failure[0] == "tool-1"
        assert failure[1]["status"] == "failed" and failure[1]["error"] == "tool_operation_failed"
        assert len(json.dumps(failure[1])) < 512
        assert not task.done() and not any(event["type"] in ("error", "ended") for event in socket.sent)
        # Replayed failed calls reuse the same response, with no paid retry.
        provider.events.put_nowait(_request())
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "That operation failed."}, "turnComplete": True}})
        await _until(socket, lambda events: any(e.get("text") == "That operation failed." and e.get("final") for e in events))
        assert calls == ["tool-1"] and provider.responses == [failure, failure]
        assert [e for e in socket.sent if e["type"] == "billing_activity"][-1]["processing"] is False
        message_id, _ = _ordered_message_id()
        socket.push({"type": "text_input", "message_id": message_id, "text": "Try a different request", "created_at": route._timestamp()})
        await _until(socket, lambda events: any(e.get("message_id") == message_id for e in events))
        provider.events.put_nowait(_request("tool-2"))
        await _until(socket, lambda events: len(provider.responses) == 3)
        assert provider.responses[-1] == ("tool-2", {"answer": "Found a result"})
        provider.events.put_nowait({"serverContent": {"outputTranscription": {"text": "Found a result"}, "turnComplete": True}})
        await _until(socket, lambda events: any(e.get("text") == "Found a result" and e.get("final") for e in events))
        assert calls == ["tool-1", "tool-2"] and not task.done()
        assert "PRIVATE" not in json.dumps(socket.sent) + json.dumps(provider.responses) + caplog.text
    finally:
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    assert [e for e in socket.sent if e["type"] == "billing_activity"][-1]["processing"] is False


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [PermissionError("authority revoked"), RuntimeError("unknown fatal error"), TimeoutError("unknown worker outcome")])
async def test_unclassified_and_authority_tool_failures_still_end_call(monkeypatch, failure, caplog):
    async def process(*args, **kwargs):
        raise failure
    socket, provider, _, task, _ = await _tool_call_session(monkeypatch, process)
    provider.events.put_nowait(_request())
    await asyncio.wait_for(task, 2)
    assert provider.responses == []
    terminal = next(event for event in socket.sent if event.get("type") == "error" and event.get("code") == "call_unavailable")
    assert terminal["stage"] == "active"
    assert terminal["error_origin"]["category"] == type(failure).__name__
    assert terminal["error_origin"]["function"] == "process"
    assert terminal["error_origin"]["line"] > 0
    assert str(failure) not in json.dumps(socket.sent) + caplog.text
# contract-test: supporting surface=gui.web assertions=video-call.chat.assistant-identity,video-call.provider.boundary
@pytest.mark.asyncio
@pytest.mark.parametrize("category,voice,name", [("medical_health", "Charon", "Melvin"), ("software_development", "Erinome", "Sophia")])
async def test_voice_mate_uses_canonical_prompt_and_fixed_voice(category, voice, name):
    socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache_service=SimpleNamespace())))
    configuration = await route._prompt_configuration(socket, mate_category=category)
    from backend.apps.ai.utils.mate_utils import load_mates_config
    mate = next(mate for mate in load_mates_config() if mate.category == category)
    assert mate.default_system_prompt in configuration["mate_instruction"]
    assert configuration["mate_category"] == category and configuration["mate_name"] == name
    setup = gemini_setup(base_instruction=configuration["base_instruction"],
        mate_instruction=configuration["mate_instruction"], voice_name=configuration["voice_name"])["setup"]
    assert setup["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == voice
    assert mate.default_system_prompt in setup["systemInstruction"]["parts"][0]["text"]
    assert setup["systemInstruction"]["parts"][0]["text"].startswith(configuration["base_instruction"])


# contract-test: supporting surface=gui.web assertions=video-call.chat.assistant-identity,video-call.privacy
@pytest.mark.asyncio
async def test_voice_mate_rejects_unknown_category_and_preserves_learning_prompt():
    socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache_service=SimpleNamespace())))
    with pytest.raises(ValueError, match="Unknown voice mate"):
        await route._prompt_configuration(socket, mate_category="arbitrary_prompt")
    from backend.apps.ai.utils.mate_utils import load_mates_config
    from backend.apps.ai.utils.voice_mate import mate_voice_configuration, GEMINI_MATE_VOICES
    for mate in load_mates_config():
        config = mate_voice_configuration(mate, learning_mode=True)
        assert mate.learning_mode_system_prompt in config["mate_instruction"]
        assert config["voice_name"] == GEMINI_MATE_VOICES[mate.voice_profile.key]
    for category in ({"prompt": "override"}, "../medical_health", 12):
        with pytest.raises(ValueError, match="mate category"):
            route._context_options({"mate_category": category})


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("ack_timeout", [False, True])
async def test_camera_tool_waits_for_exact_owned_upload_ack_and_off_keeps_audio_connected(monkeypatch, ack_timeout):
    from io import BytesIO
    from PIL import Image
    from unittest.mock import AsyncMock
    from backend.shared.providers.live_voice import LiveVoiceCapabilities
    started = asyncio.Event()
    source_expired, source_waiting = asyncio.Event(), asyncio.Event()
    db_started, release_db = asyncio.Event(), asyncio.Event()
    received = []
    from backend.shared.python_utils import voice_call_visuals as visuals_module
    if ack_timeout:
        monkeypatch.setattr(visuals_module, "SOURCE_SAVE_TIMEOUT", 0.001)
    original_source = visuals_module.VoiceCallVisuals.source
    async def observed_source(self, user_message_id):
        source_waiting.set()
        if ack_timeout:
            await db_started.wait()
        value = await original_source(self, user_message_id)
        if value is None:
            source_expired.set()
        return value
    monkeypatch.setattr(visuals_module.VoiceCallVisuals, "source", observed_source)
    async def process(broker, *args, **kwargs):
        received.append(kwargs["visual_source"])
        started.set()
        return {"response": {"status": "completed"}, "events": []}
    socket, provider, _, task, _ = await _tool_call_session(monkeypatch, process)
    try:
        provider.capabilities = LiveVoiceCapabilities(True, True, True, True, tools=True, video_input=True)
        provider.send_video = AsyncMock()
        call_id = next(event["call_id"] for event in socket.sent if event["type"] == "ready")
        socket.push({"type": "camera_state", "call_id": call_id, "enabled": True})
        await _until(socket, lambda events: any(e["type"] == "camera_state" and e["enabled"] for e in events))
        output = BytesIO()
        Image.new("RGB", (64, 32), "blue").save(output, format="JPEG")
        encoded = base64.b64encode(output.getvalue()).decode()
        socket.push({"type": "camera_frame", "call_id": call_id, "frame_id": "source-frame",
                     "captured_at": route.time.time() * 1000, "data": encoded})
        await _until(socket, lambda _: provider.send_video.await_count == 1)
        user_id, _ = _ordered_message_id()
        socket.push({"type": "text_input", "message_id": user_id, "text": "Find this object",
                     "created_at": route._timestamp()})
        await _until(socket, lambda events: any(e["type"] == "voice_source_frame" for e in events))
        source = next(e for e in socket.sent if e["type"] == "voice_source_frame")
        assert source["data"] == encoded and source["user_message_id"] == user_id
        transcript_index = next(i for i, e in enumerate(socket.sent) if e.get("message_id") == user_id)
        assert transcript_index < socket.sent.index(source)
        provider.events.put_nowait(_request())
        await _until(socket, lambda events: any(e["type"] == "billing_activity" and e["processing"] for e in events))
        await asyncio.wait_for(source_waiting.wait(), 2)
        assert not started.is_set()
        async def source_upload(*args, **kwargs):
            db_started.set()
            if ack_timeout:
                await release_db.wait()
            return [{"embed_id": "saved-source", "user_id": "owner",
                "content_hash": hashlib.sha256(output.getvalue()).hexdigest(), "content_type": "image/jpeg"}]
        socket.app.state.directus_service.get_items = source_upload
        socket.push({"type": "source_frame_saved", "call_id": call_id, "user_message_id": user_id,
            "frame_id": "source-frame", "embed_reference": {"type": "image", "embed_id": "saved-source"}})
        if ack_timeout:
            await asyncio.wait_for(db_started.wait(), 2)
            await asyncio.wait_for(source_expired.wait(), 2)
            release_db.set()
            await asyncio.wait_for(provider.response_ready.wait(), 2)
            assert not started.is_set() and not received
            assert provider.responses[-1][1]["error"] == "tool_operation_failed"
            assert not task.done() and not any(e["type"] == "error" for e in socket.sent)
        else:
            await asyncio.wait_for(started.wait(), 2)
            assert received[0]["data"] == encoded
        socket.push({"type": "camera_state", "call_id": call_id, "enabled": False})
        await _until(socket, lambda events: any(e["type"] == "camera_state" and not e["enabled"] for e in events))
        socket.push({"type": "camera_frame", "call_id": call_id, "frame_id": "denied",
            "captured_at": route.time.time() * 1000, "data": encoded})
        await _until(socket, lambda events: any(e["type"] == "camera_error" for e in events))
        assert not task.done() and provider.send_video.await_count == 1
        if ack_timeout:
            provider.send_audio = AsyncMock()
            socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 16).decode()})
            await _until(socket, lambda _: provider.send_audio.await_count == 1)
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output,video-call.video.source-frame-provenance,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_arrival_burst_drops_camera_samples_without_error_or_interrupting_audio(monkeypatch):
    from io import BytesIO
    from PIL import Image
    from unittest.mock import AsyncMock
    from backend.shared.providers.live_voice import LiveVoiceCapabilities
    from backend.shared.python_utils.voice_call_visuals import VoiceCallVisuals
    original_accept = VoiceCallVisuals.accept
    # A fixed ingress clock makes every sample after the first over budget,
    # without sleeping or changing asyncio's clock.
    monkeypatch.setattr(VoiceCallVisuals, "accept", lambda self, event: original_accept(self, event, now=100))
    async def unused(*args, **kwargs):
        raise AssertionError("No tool request is needed")
    socket, provider, _, task, _ = await _tool_call_session(monkeypatch, unused)
    try:
        provider.capabilities = LiveVoiceCapabilities(True, True, True, True, tools=True, video_input=True)
        provider.send_video, provider.send_audio = AsyncMock(), AsyncMock()
        call_id = next(event["call_id"] for event in socket.sent if event["type"] == "ready")
        socket.push({"type": "camera_state", "call_id": call_id, "enabled": True})
        output = BytesIO()
        Image.new("RGB", (32, 32), "green").save(output, format="JPEG")
        encoded = base64.b64encode(output.getvalue()).decode()
        for index in range(3):
            socket.push({"type": "camera_frame", "call_id": call_id, "frame_id": f"burst-{index}",
                "captured_at": route.time.time() * 1000, "data": encoded})
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 16).decode()})
        await _until(socket, lambda _: provider.send_audio.await_count == 1)
        assert provider.send_video.await_count == 1
        assert not any(event["type"] in {"camera_error", "error", "ended"} for event in socket.sent)
        assert not task.done()
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# contract-test: supporting surface=gui.web assertions=video-call.usage.provider-metering,video-call.video.source-frame-provenance
def test_visual_admission_reserve_releases_only_for_reported_image_or_video_usage():
    from backend.core.api.app.routes.voice_call import _unsettled_visual_credits, _has_visual_usage
    assert _unsettled_visual_credits(100, 0) > 0
    assert _unsettled_visual_credits(100, 100) == 0
    assert not _has_visual_usage({"promptTokensDetails": [{"modality": "TEXT", "tokenCount": 100}]})
    for modality in ("IMAGE", "VIDEO"):
        assert _has_visual_usage({"promptTokensDetails": [{"modality": modality, "tokenCount": 258}]})


# contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output,video-call.provider.boundary
@pytest.mark.asyncio
async def test_gemini_camera_frames_share_live_socket_and_preserve_audio_protocol():
    from unittest.mock import AsyncMock
    from backend.shared.providers.gemini_live_voice import GeminiLiveVoiceSession
    provider = GeminiLiveVoiceSession("unused-test-key")
    provider._socket = SimpleNamespace(send_json=AsyncMock())
    await provider.send_audio("pcm")
    await provider.send_video("jpeg")
    await provider.end_audio()
    assert provider.capabilities.video_input
    assert [call.args[0] for call in provider._socket.send_json.await_args_list] == [
        {"realtimeInput": {"audio": {"data": "pcm", "mimeType": "audio/pcm;rate=16000"}}},
        {"realtimeInput": {"video": {"data": "jpeg", "mimeType": "image/jpeg"}}},
        {"realtimeInput": {"audioStreamEnd": True}},
    ]


# contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output,video-call.usage.provider-metering,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_camera_only_activity_counts_while_mic_idle_and_camera_off_preserves_mic_activity(monkeypatch):
    from io import BytesIO
    from PIL import Image
    from unittest.mock import AsyncMock
    from backend.shared.providers.live_voice import LiveVoiceCapabilities
    async def unused(*args, **kwargs):
        raise AssertionError("No tool request is needed")
    socket, provider, _, task, _ = await _tool_call_session(monkeypatch, unused)
    def latest_activity():
        return [event for event in socket.sent if event["type"] == "billing_activity"][-1]
    try:
        provider.capabilities = LiveVoiceCapabilities(True, True, True, True, tools=True, video_input=True)
        provider.send_video, provider.send_audio = AsyncMock(), AsyncMock()
        call_id = next(event["call_id"] for event in socket.sent if event["type"] == "ready")
        socket.push({"type": "audio_stream_end"})
        provider.events.put_nowait({"serverContent": {"turnComplete": True}})
        await _until(socket, lambda _: not latest_activity()["input_listening"] and not latest_activity()["processing"])
        socket.push({"type": "camera_state", "call_id": call_id, "enabled": True})
        output = BytesIO()
        Image.new("RGB", (32, 32), "green").save(output, format="JPEG")
        socket.push({"type": "camera_frame", "call_id": call_id, "frame_id": "camera-only",
            "captured_at": route.time.time() * 1000, "data": base64.b64encode(output.getvalue()).decode()})
        await _until(socket, lambda _: latest_activity()["input_listening"])
        assert not latest_activity()["processing"] and provider.send_video.await_count == 1
        assert provider.send_audio.await_count == 0
        socket.push({"type": "camera_state", "call_id": call_id, "enabled": False})
        await _until(socket, lambda _: not latest_activity()["input_listening"])
        socket.push({"type": "mic_audio", "data": base64.b64encode(b"\0\0" * 16).decode()})
        await _until(socket, lambda _: provider.send_audio.await_count == 1 and latest_activity()["input_listening"])
        socket.push({"type": "camera_state", "call_id": call_id, "enabled": True})
        socket.push({"type": "camera_state", "call_id": call_id, "enabled": False})
        await _until(socket, lambda events: len([event for event in events if event["type"] == "camera_state"]) == 4)
        assert latest_activity()["input_listening"]
        socket.push({"type": "audio_stream_end"})
        await _until(socket, lambda _: not latest_activity()["input_listening"])
        socket.push({"type": "hangup"})
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
