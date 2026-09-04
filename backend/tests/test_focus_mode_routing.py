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
