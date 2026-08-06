# backend/tests/test_focus_mode_routing.py
# Regression coverage for focus-mode routing state transitions.
# Relevant focus modes are activation candidates only; active focus state alone
# may enable focus-specific execution policy such as Deep research delegation.
# Keep these tests dependency-free so routing regressions fail deterministically.

from backend.apps.ai.processing.focus_mode_routing import (
    gate_tools_for_deep_research,
    should_enable_subchats_for_active_focus,
)


def test_relevant_deep_research_does_not_enable_subchats_by_itself() -> None:
    assert should_enable_subchats_for_active_focus(None) is False


def test_active_deep_research_enables_subchats() -> None:
    assert should_enable_subchats_for_active_focus("web-research") is True


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
