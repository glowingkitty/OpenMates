# backend/apps/ai/processing/focus_mode_routing.py
# Defines dependency-free focus-mode routing policy shared by preprocessing and
# main processing. Relevance only exposes activation candidates; execution
# policy changes apply only after focus state has been explicitly activated.
# Tests live in backend/tests/test_focus_mode_routing.py.

from typing import Any


DEEP_RESEARCH_FOCUS_ID = "web-research"


def should_enable_subchats_for_active_focus(active_focus_id: str | None) -> bool:
    return active_focus_id == DEEP_RESEARCH_FOCUS_ID


def should_force_deep_research_delegation(
    *,
    active_focus_id: str | None,
    chat_depth: int,
    is_sub_chat_continuation: bool,
) -> bool:
    return (
        chat_depth == 0
        and not is_sub_chat_continuation
        and should_enable_subchats_for_active_focus(active_focus_id)
    )


def should_expose_subchat_tool(
    *,
    enable_subchats: bool,
    chat_depth: int,
    is_sub_chat_continuation: bool,
) -> bool:
    return enable_subchats and chat_depth < 2 and not is_sub_chat_continuation


def resolve_subchat_enablement(
    enable_subchats: bool,
    *,
    active_focus_id: str | None,
) -> bool:
    return enable_subchats or should_enable_subchats_for_active_focus(active_focus_id)


def gate_tools_for_deep_research(
    available_tools: list[dict[str, Any]],
    *,
    active_focus_id: str | None,
    start_sub_chats_tool: dict[str, Any],
) -> list[dict[str, Any]]:
    if should_enable_subchats_for_active_focus(active_focus_id):
        return [start_sub_chats_tool]
    return available_tools


def resolve_deep_research_tool_choice(
    tool_choice: str,
    *,
    active_focus_id: str | None,
    chat_depth: int,
    is_sub_chat_continuation: bool,
) -> str:
    if (
        tool_choice == "auto"
        and should_force_deep_research_delegation(
            active_focus_id=active_focus_id,
            chat_depth=chat_depth,
            is_sub_chat_continuation=is_sub_chat_continuation,
        )
    ):
        return "required"
    return tool_choice
