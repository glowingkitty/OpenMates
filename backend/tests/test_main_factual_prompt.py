"""The narrow factual first-turn prompt keeps all answer guidance."""
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import main_processor as main
from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.schemas.chat import AIHistoryMessage


def _proven_turn():
    question = "What is the capital of Peru?"
    request = SimpleNamespace(
        current_user_content=question,
        message_history=[SimpleNamespace(role="user", content=question)],
        admission_context={
            "scope_complete": True,
            "context_revision": "server-admission-v1",
            "explicit_related_task_ids": [],
        },
        related_task_candidates=[],
        user_preferences={},
    )
    preprocessing = SimpleNamespace(
        context_fast_path=True,
        plain_prose_response=True,
        complexity="low",
        early_task_area="general",
        output_language="en",
        selected_app_ids=[],
        relevant_app_skills=[],
        relevant_focus_modes=[],
        load_app_settings_and_memories=[],
        relevant_rules=[],
        relevant_workflows=[],
        relevant_related_work=[],
        relevant_embedded_previews=[],
    )
    return request, preprocessing


@pytest.mark.parametrize("question", [
    "What’s the capital of Spain?",
    "What's the capital of Peru?",
    "What is the capital of Kenya?",
    "Who was Ada Lovelace?",
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_proven_empty_first_turn_with_zero_forwarded_tools_omits_optional_format_guidance(question):
    request, preprocessing = _proven_turn()
    request.current_user_content = question
    request.message_history[0].content = question
    assert main._omit_fact_question_format_guidance(request, preprocessing, None, [])


@pytest.mark.parametrize(("question", "proven", "keeps_interactive"), [
    ("What’s the capital of Spain?", True, False),
    ("What is the capital of Spain for a quiz?", True, True),
    ("What is the capital of Spain in an interactive form?", True, True),
    ("What is the capital of Spain?", False, True),
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_proven_fact_omits_only_unneeded_interactive_protocol(question, proven, keeps_interactive):
    # A complete admission proof is required before the main prompt can shrink.
    request, preprocessing = _proven_turn()
    request.current_user_content = question
    request.message_history[0].content = question
    if not proven:
        preprocessing.context_fast_path = False
    assert main._omit_fact_question_format_guidance(
        request, preprocessing, None, [],
    ) is proven
    omit_interactive = main._omit_fact_question_interactive_guidance(
        request, preprocessing, None, [],
    )
    assert omit_interactive is not keeps_interactive
    safety = "SAFETY_RULE: Answer safely."
    composer = "COMPOSER_RULE: Suggest a contextual next message when useful."
    prompt_parts = [safety, composer, main.INTERACTIVE_QUESTIONS_INSTRUCTION]
    if omit_interactive:
        prompt_parts = main._without_optional_fact_interactive_section(prompt_parts)
    assert (main.INTERACTIVE_QUESTIONS_INSTRUCTION in prompt_parts) is keeps_interactive
    assert safety in prompt_parts and composer in prompt_parts


@pytest.mark.parametrize("question", [
    "What is the capital of Spain for a questionnaire?",
    "What is the capital of Spain in a survey?",
    "What is the capital of Spain on a rating form?",
    "What is the capital of Spain for a dialogue choice?",
    "What is the capital of Spain with an interactive_response?",
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_interactive_content_and_intent_preserve_protocol(question):
    request, preprocessing = _proven_turn()
    request.current_user_content = question
    request.message_history[0].content = question
    assert not main._omit_fact_question_interactive_guidance(request, preprocessing, None, [])


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_unselected_project_discovery_inventory_does_not_block_proven_empty_turn():
    request, preprocessing = _proven_turn()
    request.current_user_content = "What’s the capital of Spain?"
    request.message_history[0].content = request.current_user_content
    request.project_focus_candidates = [{"project_id": "owned-project", "name": "Travel"}]
    request.project_focus_catalog = [{"project_id": "owned-project", "title": "Travel"}]
    assert main._omit_fact_question_format_guidance(request, preprocessing, None, [])


@pytest.mark.parametrize("followup", [False, True])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
def test_unselected_task_inventory_keeps_proven_plain_initial_and_followup_prompts_compact(followup):
    request, preprocessing = _proven_turn()
    request.related_task_candidates = [
        {"task_id": f"discovery-{index}", "explicit_dependency": False}
        for index in range(24)
    ]
    if followup:
        request.current_user_content = "And France?"
        request.message_history = [
            {"role": "user", "content": "What is the capital of Spain?"},
            {"role": "assistant", "content": "Madrid."},
            {"role": "user", "content": request.current_user_content},
        ]
    before = list(request.message_history)
    assert main._omit_fact_question_format_guidance(request, preprocessing, None, [])
    assert request.message_history == before


@pytest.mark.parametrize("candidates", [
    [{"task_id": "explicit", "explicit_dependency": True}],
    [{"task_id": "unknown"}],
    [None],
    {"not": "a candidate list"},
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_explicit_or_unproven_task_dependencies_keep_required_guidance(candidates):
    request, preprocessing = _proven_turn()
    request.related_task_candidates = candidates
    assert not main._omit_fact_question_format_guidance(request, preprocessing, None, [])


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_selected_related_work_keeps_guidance_despite_unselected_discovery_inventory():
    request, preprocessing = _proven_turn()
    request.related_task_candidates = [{"task_id": "discovery", "explicit_dependency": False}]
    preprocessing.relevant_related_work = [{"task_id": "selected"}]
    assert not main._omit_fact_question_format_guidance(request, preprocessing, None, [])


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_declared_request_schema_disabled_learning_mode_allows_exact_benchmark_turn():
    question = "What’s the capital of Spain?"
    request = AskSkillRequest(
        chat_id="chat", message_id="message", user_id="owner", user_id_hash="owner-hash",
        message_history=[AIHistoryMessage(role="user", content=question, created_at=1)],
        current_user_content=question,
        admission_context={
            "scope_complete": True, "context_revision": "server-admission-v1",
            "active_project_id": None, "active_project_activation_id": None,
            "active_focus_id": None, "accepted_plan_ref": None,
            "explicit_related_task_ids": [],
        },
        project_focus_candidates=[{"project_id": "owned-project", "name": "Travel"}],
        learning_mode={"enabled": False},
    )
    preprocessing = PreprocessingResult(
        context_fast_path=True, plain_prose_response=True, complexity="low", early_task_area="general", output_language="en",
        selected_app_ids=[], relevant_app_skills=[], relevant_focus_modes=[],
        load_app_settings_and_memories=[], relevant_rules=[], relevant_workflows=[],
        relevant_related_work=[], relevant_embedded_previews=[],
    )
    assert request.learning_mode == {"enabled": False}
    assert main._omit_fact_question_format_guidance(request, preprocessing, None, [])


@pytest.mark.parametrize("change", [
    "forwarded_tool", "no_complete_proof", "unknown_area", "selected_app",
    "prior_history", "mismatched_history", "code_intent", "document_intent",
    "math_intent", "attached_artifact", "relevant_workflow", "loaded_memory",
    "project_document", "active_focus", "user_override", "workflow_request",
    "related_task", "embedding", "learning_mode", "subjective_question",
    "unknown_question", "selected_project_document", "selected_project_binding",
    "project_routing_state", "missing_learning_mode_flag", "invalid_learning_mode_flag",
    "disabled_with_unexpected_learning_context",
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_format_guidance_remains_for_context_or_unknown_intent(change):
    request, preprocessing = _proven_turn()
    tools = []
    overrides = None
    if change == "forwarded_tool":
        tools = [{"type": "function", "function": {"name": "web_search"}}]
    elif change == "no_complete_proof":
        preprocessing.context_fast_path = False
    elif change == "unknown_area":
        preprocessing.early_task_area = None
    elif change == "selected_app":
        preprocessing.selected_app_ids = ["math"]
    elif change == "prior_history":
        request.message_history.insert(0, SimpleNamespace(role="user", content="Earlier turn"))
    elif change == "mismatched_history":
        request.message_history[0].content = "Another question?"
    elif change in {"code_intent", "document_intent", "math_intent"}:
        phrase = {
            "code_intent": "What is the Python code for a chart?",
            "document_intent": "What is the document format for a report?",
            "math_intent": "What is the equation for this plot?",
        }[change]
        request.current_user_content = phrase
        request.message_history[0].content = phrase
    elif change == "attached_artifact":
        request.embed_file_path_index = {"attachment.pdf": "embed-id"}
    elif change == "relevant_workflow":
        preprocessing.relevant_workflows = [{"id": "workflow"}]
    elif change == "loaded_memory":
        preprocessing.load_app_settings_and_memories = ["travel:trips"]
    elif change == "project_document":
        request.project_context_documents = [{"id": "document"}]
    elif change == "selected_project_document":
        request.project_focus_documents = [{"id": "focus"}]
    elif change == "selected_project_binding":
        request.current_project = {"project_id": "owned-project"}
    elif change == "project_routing_state":
        request.project_routing_focus_id = "owned-project"
    elif change == "active_focus":
        request.active_focus_id = "math-tutor"
    elif change == "user_override":
        overrides = SimpleNamespace(has_overrides=True)
    elif change == "workflow_request":
        request.user_preferences = {"workflow_ai": True}
    elif change == "related_task":
        request.related_task_candidates = [{"task_id": "task", "explicit_dependency": True}]
    elif change == "embedding":
        preprocessing.relevant_embedded_previews = ["code"]
    elif change == "learning_mode":
        request.learning_mode = {"enabled": True}
    elif change == "missing_learning_mode_flag":
        request.learning_mode = {}
    elif change == "invalid_learning_mode_flag":
        request.learning_mode = {"enabled": "false"}
    elif change == "disabled_with_unexpected_learning_context":
        request.learning_mode = {"enabled": False, "age_group": "adult"}
    elif change in {"subjective_question", "unknown_question"}:
        question = (
            "Who is the best artist?" if change == "subjective_question"
            else "What is an interesting idea?"
        )
        request.current_user_content = question
        request.message_history[0].content = question
    assert not main._omit_fact_question_format_guidance(request, preprocessing, overrides, tools)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_only_optional_format_sections_leave_prompt_prefix_and_recovery_consistent():
    instructions = {
        "base_ethics_instruction": "Ethics and privacy",
        "base_link_encouragement_instruction": "Cite links",
        "base_wikipedia_linking_instruction": "Wikipedia titles",
        "base_url_sourcing_instruction": "Verify sources",
        "base_code_block_instruction": "Code formatting",
        "base_document_generation_instruction": "Document HTML formatting",
        "base_plot_code_block_instruction": "Math plot formatting",
    }
    stable = [instructions[key] for key in instructions if key != "base_plot_code_block_instruction"]
    prompt = [*stable, "Current date and time", "Mate persona", "Model identity",
              "Language", "Questions", "Composer suggestion", instructions["base_plot_code_block_instruction"]]
    remaining, prefix = main._without_optional_fact_format_sections(prompt, stable, instructions)
    expected = [part for part in prompt if "formatting" not in part]
    assert remaining == expected
    assert prefix == [part for part in stable if "formatting" not in part]
    assert "\n\n".join(prefix) in "\n\n".join(remaining)
    assert "\n\n".join(remaining) == "\n\n".join(part for part in remaining if part)


@pytest.mark.parametrize("question", [
    "What’s the capital of Spain?",
    "Who was Ada Lovelace?",
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_proven_plain_fact_omits_app_guidance(question):
    request, preprocessing = _proven_turn()
    request.current_user_content = question
    request.message_history[0].content = question
    assert main._omit_fact_question_format_guidance(request, preprocessing, None, [])
    assert main._omit_fact_question_app_guidance(question)


@pytest.mark.parametrize("question", [
    "What is the capital of OpenMates?",
    "Who is the assistant?",
    "Who is the app owner?",
    "Who is the capability owner?",
    "Who is the settings owner?",
    "Who is the Memory owner?",
    "Who is the deep-link owner?",
    "Who is the Project owner?",
    "Who is the focus owner?",
    "Who is the workflow owner?",
    "Who is the account owner?",
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_product_or_app_intent_keeps_app_guidance(question):
    assert not main._omit_fact_question_app_guidance(question)


@pytest.mark.parametrize("change", [
    "unknown_question", "prior_history", "active_focus", "project_document",
    "relevant_workflow", "loaded_memory", "selected_app", "forwarded_tool",
    "user_override",
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_app_guidance_omission_requires_full_fact_proof(change):
    request, preprocessing = _proven_turn()
    tools = []
    overrides = None
    if change == "unknown_question":
        request.current_user_content = "What is an interesting idea?"
        request.message_history[0].content = request.current_user_content
    elif change == "prior_history":
        request.message_history.insert(0, SimpleNamespace(role="user", content="Earlier"))
    elif change == "active_focus":
        request.active_focus_id = "math-tutor"
    elif change == "project_document":
        request.project_context_documents = [{"id": "document"}]
    elif change == "relevant_workflow":
        preprocessing.relevant_workflows = [{"id": "workflow"}]
    elif change == "loaded_memory":
        preprocessing.load_app_settings_and_memories = ["travel:trips"]
    elif change == "selected_app":
        preprocessing.selected_app_ids = ["web"]
    elif change == "forwarded_tool":
        tools = [{"type": "function", "function": {"name": "web-search"}}]
    elif change == "user_override":
        overrides = SimpleNamespace(has_overrides=True)
    assert not (
        main._omit_fact_question_format_guidance(request, preprocessing, overrides, tools)
        and main._omit_fact_question_app_guidance(request.current_user_content)
    )


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_app_guidance_removal_keeps_equal_safety_text_and_prompt_consistency():
    # The capabilities text is filled dynamically; equal prose elsewhere must
    # survive even when it has the same value as an appended optional section.
    capabilities = "Capabilities: none (no apps available)"
    equal_safety_text = (" " + capabilities)[1:]
    assert equal_safety_text == capabilities and equal_safety_text is not capabilities
    deep_link = "App deep-link rules"
    settings_link = "Settings and Memory deep-link rules"
    stable = ["Ethics and privacy", "Cite sources", "Wikipedia language"]
    prompt = [*stable, equal_safety_text, "Current date", "Mate persona", "Model identity",
              capabilities, "Composer suggestion", deep_link, settings_link,
              "Interactive question protocol"]
    remaining = main._without_appended_fact_app_guidance(
        prompt, [capabilities, deep_link, settings_link],
    )
    assert remaining == [*stable, equal_safety_text, "Current date", "Mate persona",
                         "Model identity", "Composer suggestion", "Interactive question protocol"]
    assert remaining[3] is equal_safety_text
    prefix = "\n\n".join(stable)
    full = "\n\n".join(filter(None, remaining))
    recovery = "\n\n".join(part for part in remaining if part)
    assert full.startswith(prefix)
    assert full == recovery


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.parametrize("change", ["none", "incomplete", "complex", "artifact", "tool_history", "interactive_history"])
def test_contextual_followup_keeps_prior_response_requirements(change):
    request, preprocessing = _proven_turn()
    request.current_user_content = "And France?"
    request.message_history = [
        {"role": "user", "content": "What is the capital of Spain?"},
        {"role": "assistant", "content": "Madrid."},
        {"role": "user", "content": request.current_user_content},
    ]
    if change == "incomplete":
        request.admission_context["scope_complete"] = False
    elif change == "complex":
        preprocessing.complexity = "complex"
    elif change == "artifact":
        request.message_history[0]["content"] = "What is the capital in this document?"
    elif change == "tool_history":
        request.message_history[1]["tool_calls"] = [{"id": "search"}]
    elif change == "interactive_history":
        request.message_history[0]["content"] = "What is the capital of Spain for a quiz?"
    assert main._omit_fact_question_format_guidance(request, preprocessing, None, []) is (
        change in {"none", "interactive_history"})
    assert main._omit_fact_question_interactive_guidance(request, preprocessing, None, []) is (change == "none")


# contract-test: supporting surface=rest_api assertions=ai-model-routing.instructions.required-safety
def test_optional_instruction_alias_cannot_remove_required_safety():
    ethics, privacy = "Required ethics", "Required privacy"
    instructions = {"base_ethics_instruction": ethics, "base_privacy_instruction": privacy,
                    "base_code_block_instruction": ethics, "base_document_generation_instruction": privacy}
    prompt, prefix = main._without_optional_fact_format_sections(
        [ethics, privacy, ethics, privacy], [ethics, privacy], instructions)
    assert ethics in prompt and privacy in prompt
    assert prefix == [ethics, privacy]


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.parametrize("language,question", [
    ("es", "escribir archivo?"), ("es", "capital de Francia?"),
    ("de", "Schreibe Python für Frankreich?"), ("de", "Erstelle eine Datei?"),
    ("fr", "programme document?"), ("fr", "Écrire un fichier?"),
    ("fr", "Quelle est ma préférence ?"), ("de", "Was ist mein Plan?"),
    ("ja", "フランスの首都は？"),
])
def test_unknown_languages_and_localized_response_requirements_keep_full_prompt(language, question):
    request, preprocessing = _proven_turn()
    preprocessing.output_language = language
    request.current_user_content = question
    request.message_history[0].content = question
    assert not main._omit_fact_question_format_guidance(request, preprocessing, None, [])


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.parametrize("language,question", [("en", "And its currency?"), ("fr", "Et sa monnaie ?"), ("de", "Und seine Währung?")])
def test_public_pronoun_followups_retain_full_needed_history(language, question):
    request, preprocessing = _proven_turn()
    preprocessing.output_language = language
    request.current_user_content = question
    request.message_history = [{"role": "user", "content": "What is the capital of France?"},
                               {"role": "assistant", "content": "Paris."},
                               {"role": "user", "content": question}]
    original = list(request.message_history)
    assert main._omit_fact_question_format_guidance(request, preprocessing, None, [])
    assert request.message_history == original


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
def test_legacy_or_missing_positive_response_requirements_keep_full_guidance():
    request, preprocessing = _proven_turn()
    del preprocessing.plain_prose_response
    assert not main._omit_fact_question_format_guidance(request, preprocessing, None, [])


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.parametrize("tier", ["low", "simple", "medium", "high", "max", "unknown", None])
def test_compact_prose_tracks_current_low_tier_and_safe_legacy_alias(tier):
    request, preprocessing = _proven_turn()
    preprocessing.complexity = tier
    assert main._omit_fact_question_format_guidance(request, preprocessing, None, []) is (tier in {"low", "simple"})
