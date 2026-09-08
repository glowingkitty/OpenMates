# contract-test-file: infrastructure
# backend/tests/test_focus_mode_routing.py
# Regression coverage for focus-mode routing state transitions.
# Relevant focus modes are activation candidates only; active focus state alone
# may enable focus-specific execution policy such as Deep research delegation.
# Keep these tests dependency-free so routing regressions fail deterministically.

from pathlib import Path

from backend.apps.ai.processing.focus_mode_routing import (
    gate_tools_for_deep_research,
    resolve_deep_research_tool_choice,
    resolve_subchat_enablement,
    should_expose_subchat_tool,
    should_force_deep_research_delegation,
    should_enable_subchats_for_active_focus,
)


def test_relevant_deep_research_does_not_enable_subchats_by_itself() -> None:
    assert should_enable_subchats_for_active_focus(None) is False


def test_active_deep_research_enables_subchats() -> None:
    assert should_enable_subchats_for_active_focus("web-research") is True


def test_active_deep_research_overrides_preprocessing_subchat_decision() -> None:
    assert resolve_subchat_enablement(False, active_focus_id="web-research") is True


def test_existing_subchat_enablement_is_preserved_without_active_focus() -> None:
    assert resolve_subchat_enablement(True, active_focus_id=None) is True


def test_relevant_deep_research_preserves_preselected_tools() -> None:
    web_search_tool = {"function": {"name": "web-search"}}
    activate_focus_tool = {"function": {"name": "activate_focus_mode"}}
    start_sub_chats_tool = {"function": {"name": "start_sub_chats"}}
    available_tools = [web_search_tool, activate_focus_tool, start_sub_chats_tool]

    gated_tools = gate_tools_for_deep_research(
        available_tools,
        active_focus_id=None,
        start_sub_chats_tool=start_sub_chats_tool,
    )

    assert gated_tools == available_tools


def test_active_deep_research_forces_sub_chat_delegation() -> None:
    web_search_tool = {"function": {"name": "web-search"}}
    start_sub_chats_tool = {"function": {"name": "start_sub_chats"}}

    gated_tools = gate_tools_for_deep_research(
        [web_search_tool, start_sub_chats_tool],
        active_focus_id="web-research",
        start_sub_chats_tool=start_sub_chats_tool,
    )

    assert gated_tools == [start_sub_chats_tool]


def test_active_deep_research_requires_the_sub_chat_tool() -> None:
    assert resolve_deep_research_tool_choice(
        "auto",
        active_focus_id="web-research",
        chat_depth=0,
        is_sub_chat_continuation=False,
    ) == "required"


def test_deep_research_does_not_override_terminal_no_tool_choice() -> None:
    assert resolve_deep_research_tool_choice(
        "none",
        active_focus_id="web-research",
        chat_depth=0,
        is_sub_chat_continuation=False,
    ) == "none"


def test_deep_research_synthesis_does_not_restart_delegation() -> None:
    assert should_force_deep_research_delegation(
        active_focus_id="web-research",
        chat_depth=0,
        is_sub_chat_continuation=True,
    ) is False
    assert resolve_deep_research_tool_choice(
        "auto",
        active_focus_id="web-research",
        chat_depth=0,
        is_sub_chat_continuation=True,
    ) == "auto"
    assert should_expose_subchat_tool(
        enable_subchats=True,
        chat_depth=0,
        is_sub_chat_continuation=True,
    ) is False


def test_child_chat_can_still_delegate_one_level_deeper() -> None:
    assert should_expose_subchat_tool(
        enable_subchats=True,
        chat_depth=1,
        is_sub_chat_continuation=False,
    ) is True


def test_deep_research_child_executes_its_angle_without_more_delegation() -> None:
    assert should_expose_subchat_tool(
        enable_subchats=True,
        chat_depth=1,
        is_sub_chat_continuation=False,
        active_focus_id="web-research",
    ) is False


def test_parent_continuation_ai_reservation_is_guarded_before_orchestration_call() -> None:
    source = (Path(__file__).resolve().parents[1] / "apps/ai/processing/main_processor.py").read_text()
    function_source = source[
        source.index("async def _reserve_ai_iteration("):
        source.index("async def _fail_reserved_operation(")
    ]

    continuation_guard = function_source.index(
        "if is_sub_chat_continuation(request_data) and not is_anonymous:"
    )
    orchestration_call = function_source.index("SubChatOrchestrationService(directus_service).execute")

    assert continuation_guard < orchestration_call


def _focus_prompt_scope(active_focus_id="jobs-career_insights", *, language="en", inline=None, translation_available=True):
    """Execute the production prompt-assembly slice without importing providers.

    This is supporting unit evidence only; real authenticated inference tests
    remain required to establish the public behavior across requests.
    """
    import ast
    import logging
    from types import SimpleNamespace
    from typing import Optional
    from backend.apps.ai.processing import focus_mode_routing

    source = Path("backend/apps/ai/processing/main_processor.py").read_text()
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_main_processing")
    start = next(i for i, n in enumerate(function.body) if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "active_focus_prompt_text")
    end = next(i for i, n in enumerate(function.body) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "follow_up_suggestions_enabled" for t in n.targets))
    instruction = "Full focus instruction: ask about constraints.\nPreserve all configured details."
    translator = SimpleNamespace(get_nested_translation=lambda key, lang="en": instruction if lang == "en" and translation_available else None)
    scope = dict(vars(focus_mode_routing))
    scope.update(Optional=Optional, logger=logging.getLogger(__name__), log_prefix="test", request_data=SimpleNamespace(active_focus_id=active_focus_id), discovered_apps_metadata={"jobs": SimpleNamespace(focuses=[SimpleNamespace(id="career_insights", system_prompt=inline, systemprompt_translation_key="focus_modes.jobs_career_insights.systemprompt")])}, prompt_parts=["Base instructions"], preprocessing_results=SimpleNamespace(output_language=language), translation_service=translator, TranslationService=lambda: translator, chat_depth=0)
    exec(compile(ast.Module(body=function.body[start:end], type_ignores=[]), "production-focus-prompt", "exec"), scope)
    return scope, instruction


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_translation_only_focus_instruction_on_each_active_request():
    for _ in range(3):
        scope, instruction = _focus_prompt_scope()
        assert instruction in "\n".join(scope["prompt_parts"])


# contract-test: supporting surface=rest_api assertions=focus-modes.off-instruction
def test_off_focus_excludes_instruction():
    scope, instruction = _focus_prompt_scope(None)
    assert instruction not in "\n".join(scope["prompt_parts"])


# contract-test: supporting surface=rest_api assertions=focus-modes.off-instruction,focus-modes.history-events
def test_ai_deactivation_removes_instruction_before_next_inference():
    import ast
    import asyncio
    import json
    import logging
    from types import SimpleNamespace
    from backend.apps.ai.processing import focus_mode_routing

    tree = ast.parse(Path("backend/apps/ai/processing/main_processor.py").read_text())
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name) and n.test.left.id == "skill_id" and any(isinstance(v, ast.Constant) and v.value == "deactivate_focus_mode" for v in n.test.comparators))
    body = [n for n in branch.body if not isinstance(n, ast.Continue)]
    function = ast.AsyncFunctionDef(name="run_branch", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=body + [ast.Return(value=ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[]))], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    instruction = "Full focus instruction"
    focus_part = f"--- Active Focus: jobs-career_insights ---\n{instruction}\n--- End Active Focus ---"
    scope = dict(vars(focus_mode_routing))
    scope.update(json=json, logger=logging.getLogger(__name__), log_prefix="test", request_data=SimpleNamespace(active_focus_id="jobs-career_insights"), cache_service=None, current_message_history=[], tool_call_id="deactivate-1", tool_name="system-deactivate_focus_mode", prompt_parts=[focus_part, "Base instructions"], active_focus_prompt_text=instruction, active_focus_prompt_section=focus_part, full_system_prompt=focus_part + "\n\nBase instructions")
    exec(compile(module, "production-focus-deactivate", "exec"), scope)
    result = asyncio.run(scope["run_branch"]())
    assert scope["request_data"].active_focus_id is None
    assert instruction not in result.get("full_system_prompt", scope["full_system_prompt"])
    transitions = [message for message in scope["current_message_history"] if message["role"] == "system"]
    assert len(transitions) == 1
    assert "jobs-career_insights" in transitions[0]["content"]
    assert instruction not in transitions[0]["content"]



# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_active_focus_language_fallback_keeps_full_instruction():
    scope, instruction = _focus_prompt_scope(language="xx")
    assert instruction in "\n".join(scope["prompt_parts"])


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_inline_focus_instruction_preserves_precedence():
    scope, translated = _focus_prompt_scope(inline="Full inline instruction")
    assert "Full inline instruction" in "\n".join(scope["prompt_parts"])
    assert translated not in "\n".join(scope["prompt_parts"])


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_missing_active_focus_instruction_does_not_silently_answer_unfocused():
    import pytest
    with pytest.raises(ValueError, match="Active focus instructions are unavailable"):
        _focus_prompt_scope(translation_available=False)
