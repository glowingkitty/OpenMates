# backend/apps/ai/processing/focus_mode_routing.py
# Defines dependency-free focus-mode routing policy shared by preprocessing and
# main processing. Relevance only exposes activation candidates; execution
# policy changes apply only after focus state has been explicitly activated.
# Tests live in backend/tests/test_focus_mode_routing.py.

from typing import Any, Iterable


DEEP_RESEARCH_FOCUS_ID = "web-research"
WORKFLOW_CLARIFY_FOCUS_ID = "workflows-clarify_workflows"
WORKFLOW_CLARIFY_SKILLS = frozenset({"workflows-search", "workflows-create-or-modify"})

BRAND_NAMING_RESEARCH_SKILLS = frozenset({
    "hosting-search_domains", "web-search", "business-search_trademarks",
})


def resolve_automatic_focus_proposal(
    *, relevant_focus_modes: Iterable[str], eligible_focus_ids: set[str],
    has_active_focus: bool, chat_depth: int, is_continuation: bool,
    exact_skill_request: bool, explicit_focus_request: bool, apps_enabled: bool,
) -> str | None:
    """Propose one opted-in public match without bypassing focus consent.

    Relevance never grants access or starts research children. Ambiguity, an
    existing focus, exact user selections and continuation/rejection turns keep
    the ordinary tool path. A mode's preprocessing hint must exclude requests
    that do not need its specialized process, such as simple web lookups.
    """
    if (has_active_focus or chat_depth != 0 or is_continuation
            or exact_skill_request or explicit_focus_request or not apps_enabled):
        return None
    matched = list(dict.fromkeys(relevant_focus_modes))
    if len(matched) == 1 and matched[0] in eligible_focus_ids:
        return matched[0]
    return None


def brand_naming_research_skill_scope(
    *, active_focus_id: str | None, preselected_skills: set[str] | None,
    available_skills: set[str], exact_request: bool,
) -> set[str] | None:
    """Offer all finalist checks when an active naming conversation researches.

    Preprocessing can select only domains/web for a finalist request. The naming
    instructions need trademark search available too. Intake remains tool-free,
    explicit skill selections stay exact, and unavailable skills stay excluded.
    This offers capabilities; the focus prompt still decides what to call.
    """
    if (active_focus_id != "business-find_brand_name" or exact_request
            or not preselected_skills
            or not (preselected_skills & BRAND_NAMING_RESEARCH_SKILLS)):
        return preselected_skills
    return preselected_skills | (BRAND_NAMING_RESEARCH_SKILLS & available_skills)


def workflow_clarification_skill_scope(
    *, active_focus_id: str | None, relevant_focus_modes: list[str], explicit_focus_mention: bool,
) -> set[str] | None:
    """Keep clarification on Workflows even when the request names a search topic.

    Focus metadata allowlists are not enforced yet. This narrow runtime gate
    prevents natural-search preprocessing from turning a workflow edit into an
    immediate events/news search in the clarification chat.
    """
    if active_focus_id == WORKFLOW_CLARIFY_FOCUS_ID or (
        explicit_focus_mention and WORKFLOW_CLARIFY_FOCUS_ID in relevant_focus_modes
    ):
        return set(WORKFLOW_CLARIFY_SKILLS)
    return None


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
    active_focus_id: str | None = None,
) -> bool:
    return (
        enable_subchats
        and chat_depth < 2
        and not is_sub_chat_continuation
        and not (chat_depth > 0 and active_focus_id == DEEP_RESEARCH_FOCUS_ID)
    )


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
