"""Project routing stops at consent before private selection or answer setup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import jev_preprocessing, preprocessor
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.shared.providers.typesafe.models import DecisionResponse

PROJECT = "11111111-1111-4111-8111-111111111111"
ITEM = "22222222-2222-4222-8222-222222222222"
PROMPT = "suggestions how to improve the readme of my OpenMates project?"


def answers_for(questions, *, project=True, specialist=False):
    answers = {}
    for key, question in questions.items():
        if question["type"] == "noul":
            answers[key] = {"type": "noul", "noul": .9}
        else:
            choice = (f"project-{PROJECT}" if key == "project_target" and project
                      else f"project-focus:{PROJECT}:{ITEM}" if specialist
                      else "default" if key == "project_specialist" else "none")
            answers[key] = {"type": "choice", "choice": choice, "confidence": .99,
                            "probabilities": {value: float(value == choice) for value in question["criteria"]}}
    return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})


# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent,projects.focus.custom-catalog-privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("has_custom_focus", [False, True])
async def test_project_route_skips_detailed_decisions_and_only_discovers_present_custom_focus(monkeypatch, has_custom_focus):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        return answers_for(kwargs["questions"], specialist="project_specialist" in kwargs["questions"])

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    catalog = [{"focus_id": f"project-focus:{PROJECT}:{ITEM}", "item_id": ITEM,
                "revision": "a" * 64, "title": "Improve documentation",
                "description": "Review README quality", "when_to_use": "Documentation review"}] if has_custom_focus else []
    loader = AsyncMock(return_value=catalog)
    result = await jev_preprocessing.decide_app_and_project_routing_with_jev(
        model_id="test/jev", secrets_manager=None,
        message_history=[{"role": "user", "content": PROMPT}],
        available_apps=["projects", "web"], available_skills=["projects-create: Create project"],
        available_focus_modes=[], project_focus_catalog_loader=loader,
        project_candidates=[{"project_id": PROJECT, "name": "OpenMates", "summary": "", "focuses": catalog}],
    )
    assert result["pending_project_focus_id"] == f"project-{PROJECT}"
    assert len(calls) == (2 if has_custom_focus else 1)
    assert set(calls[0]["questions"]) == {"app_0", "app_1", "project_target"}
    assert all(not key.startswith(("skill_", "memory_")) for call in calls for key in call["questions"])
    loader.assert_awaited_once()
    if has_custom_focus:
        assert result["pending_project_specialist"]["item_id"] == ITEM
        assert set(calls[1]["questions"]) == {"project_specialist"}


# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent,projects.focus.auto-selection-setting
@pytest.mark.asyncio
async def test_disabled_project_cannot_be_chosen_and_unrelated_request_skips_focus_discovery(monkeypatch):
    async def evaluate(**kwargs):
        assert "project_target" not in kwargs["questions"]
        return answers_for(kwargs["questions"], project=False)

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    loader = AsyncMock()
    result = await jev_preprocessing.decide_app_and_project_routing_with_jev(
        model_id="test/jev", secrets_manager=None, message_history=[{"role": "user", "content": PROMPT}],
        available_apps=["projects"], available_skills=[], available_focus_modes=[],
        project_candidates=[{"project_id": PROJECT, "name": "OpenMates", "auto_selection": False}],
        project_focus_catalog_loader=loader,
    )
    assert "pending_project_focus_id" not in result
    loader.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent,projects.memories.active-access
@pytest.mark.asyncio
async def test_whole_preprocessor_returns_consent_without_mates_rules_or_full_routing(monkeypatch):
    from backend.core.api.app.services import project_focus_request_service
    from backend.core.api.app.utils import server_mode
    request = AskSkillRequest(chat_id="chat", message_id="turn", user_id="user", user_id_hash="hash",
        message_history=[{"role": "user", "content": PROMPT, "created_at": 1}], current_user_content=PROMPT,
        client_capabilities=["project_file_jobs"], project_focus_candidates=[{"project_id": PROJECT, "name": "OpenMates", "focuses": []}])
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: False)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(available=True, prompt_rows=())))
    monkeypatch.setattr(project_focus_request_service, "validated_project_candidates", AsyncMock(return_value=request.project_focus_candidates))
    async def evaluate(**kwargs):
        return answers_for(kwargs["questions"])
    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    mates = AsyncMock(side_effect=AssertionError("Main/detail setup ran before Project consent"))
    result = await preprocessor.handle_preprocessing(
        request_data=request, base_instructions={"preprocess_request_tool": {}},
        skill_config=SimpleNamespace(default_llms=SimpleNamespace(decision_model="test/jev",
            main_processing_simple="test/main", main_processing_simple_name="Main")),
        cache_service=SimpleNamespace(get_user_by_id=AsyncMock(return_value={}), get_mates_configs=mates),
        secrets_manager=None, directus_service=None, encryption_service=None, discovered_apps_metadata={},
    )
    assert result.can_proceed and result.pending_project_focus_id == f"project-{PROJECT}"
    assert result.relevant_app_skills == [] and result.load_app_settings_and_memories == []
    assert result.relevant_rules is None
    assert "pending_project_focus_id" not in result.model_dump()
    mates.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=projects.focus.custom-catalog-privacy,projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_unknown_catalog_requests_only_selected_project_then_reuses_stage_one(monkeypatch):
    calls = []
    async def evaluate(**kwargs):
        calls.append(kwargs)
        return answers_for(kwargs["questions"])
    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    loader = AsyncMock(return_value=[])
    kwargs = dict(model_id="test/jev", secrets_manager=None,
        message_history=[{"role": "user", "content": PROMPT}],
        available_apps=["projects", "web"], available_skills=[], available_focus_modes=[],
        project_focus_catalog_loader=loader)
    result = await jev_preprocessing.decide_app_and_project_routing_with_jev(
        **kwargs, project_candidates=[{"project_id": PROJECT, "name": "OpenMates"}])
    assert result["pending_project_catalog_id"] == PROJECT
    loader.assert_not_awaited()
    ready = await jev_preprocessing.decide_app_and_project_routing_with_jev(
        **kwargs, project_candidates=[{"project_id": PROJECT, "name": "OpenMates", "focuses": []}],
        project_routing_focus_id=result["pending_project_focus_id"], selected_app_ids=result["selected_app_ids"])
    assert len(calls) == 1  # No repeated routing or empty-catalog Jev pass.
    assert "pending_project_catalog_id" not in ready
    assert ready["pending_project_focus_id"] == f"project-{PROJECT}"


# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent,projects.files.chat-focus-required
@pytest.mark.asyncio
async def test_consent_stream_exits_before_main_context_or_provider_setup(monkeypatch):
    from backend.apps.ai.processing import main_processor, project_focus_orchestration
    request = AskSkillRequest(chat_id="chat", message_id="turn", user_id="user", user_id_hash="hash",
        message_history=[], client_capabilities=["project_file_jobs"],
        project_focus_candidates=[{"project_id": PROJECT, "name": "OpenMates"}])
    result = preprocessor.PreprocessingResult(can_proceed=True, routing_only=True,
        pending_project_focus_id=f"project-{PROJECT}", relevant_focus_modes=[f"project-{PROJECT}"])
    proposal = AsyncMock(return_value='{"embed_id":"consent"}')
    context = AsyncMock(side_effect=AssertionError("Answer setup before consent"))
    provider = AsyncMock(side_effect=AssertionError("Answer inference before consent"))
    monkeypatch.setattr(project_focus_orchestration, "request_project_focus", proposal)
    monkeypatch.setattr(main_processor, "_load_main_agentic_context", context)
    monkeypatch.setattr(main_processor, "call_main_llm_stream", provider)
    chunks = [chunk async for chunk in main_processor.handle_main_processing(
        task_id="task", request_data=request, preprocessing_results=result, base_instructions={},
        directus_service=None, encryption_service=None, user_vault_key_id=None,
        all_mates_configs=[], discovered_apps_metadata={})]
    assert chunks[-1]["__awaiting_focus_mode_confirmation__"] is True
    proposal.assert_awaited_once()
    context.assert_not_awaited()
    provider.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent,projects.files.chat-focus-required
@pytest.mark.asyncio
@pytest.mark.parametrize("staged", [False, True])
async def test_compact_routing_failure_retains_named_project_consent_boundary(monkeypatch, staged):
    from backend.core.api.app.services import project_focus_request_service
    from backend.core.api.app.utils import server_mode
    request = AskSkillRequest(chat_id="chat", message_id="turn", user_id="user", user_id_hash="hash",
        message_history=[{"role": "user", "content": PROMPT, "created_at": 1}], current_user_content=PROMPT,
        client_capabilities=["project_file_jobs"], project_focus_candidates=[{"project_id": PROJECT, "name": "OpenMates", "focuses": []}])
    if staged:
        request.current_user_content = "Review the project I just connected"
        request.project_routing_focus_id = f"project-{PROJECT}"
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: False)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", AsyncMock(return_value=preprocessor.RoutingLedgerSnapshot(available=True, prompt_rows=())))
    monkeypatch.setattr(project_focus_request_service, "validated_project_candidates", AsyncMock(return_value=request.project_focus_candidates))
    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", AsyncMock(side_effect=RuntimeError("Provider unavailable")))
    forbidden = AsyncMock(side_effect=AssertionError("Detailed inference ran before consent"))
    monkeypatch.setattr(preprocessor, "call_preprocessing_llm", forbidden)
    result = await preprocessor.handle_preprocessing(
        request_data=request, base_instructions={"preprocess_request_tool": {}},
        skill_config=SimpleNamespace(default_llms=SimpleNamespace(decision_model=None if staged else "test/jev", main_processing_simple="test/main", main_processing_simple_name="Main")),
        cache_service=SimpleNamespace(get_user_by_id=AsyncMock(return_value={})), secrets_manager=None,
        directus_service=None, encryption_service=None, discovered_apps_metadata={})
    assert result.routing_only and result.pending_project_focus_id == f"project-{PROJECT}"
    assert result.selected_app_ids is None  # Detailed fallback runs after activation.
    forbidden.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=projects.focus.custom-catalog-privacy,projects.focus.inferred-consent
@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["catalog", "specialist"])
async def test_optional_focus_failure_preserves_selected_project_without_another_routing_pass(monkeypatch, failure_stage):
    calls = []
    async def evaluate(**kwargs):
        calls.append(kwargs)
        if "project_specialist" in kwargs["questions"]:
            raise RuntimeError("Optional provider unavailable")
        return answers_for(kwargs["questions"])
    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    catalog = [{"focus_id": f"project-focus:{PROJECT}:{ITEM}", "item_id": ITEM,
                "revision": "a" * 64, "title": "Documentation"}]
    loader = (AsyncMock(side_effect=RuntimeError("Metadata unavailable")) if failure_stage == "catalog"
              else AsyncMock(return_value=catalog))
    result = await jev_preprocessing.decide_app_and_project_routing_with_jev(
        model_id="test/jev", secrets_manager=None, message_history=[{"role": "user", "content": PROMPT}],
        available_apps=["projects"], available_skills=[], available_focus_modes=[],
        project_candidates=[{"project_id": PROJECT, "name": "OpenMates", "focuses": catalog}],
        project_focus_catalog_loader=loader)
    assert result["pending_project_focus_id"] == f"project-{PROJECT}"
    assert "pending_project_specialist" not in result
    assert len(calls) == (1 if failure_stage == "catalog" else 2)
