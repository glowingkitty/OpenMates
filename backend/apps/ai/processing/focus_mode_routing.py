# backend/apps/ai/processing/focus_mode_routing.py
# Defines dependency-free focus-mode routing policy shared by preprocessing and
# main processing. Relevance only exposes activation candidates; execution
# policy changes apply only after focus state has been explicitly activated.
# Tests live in backend/tests/test_focus_mode_routing.py.

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlsplit


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


def can_synthesize_deep_research(stage: str | None) -> bool:
    """Legacy roots stay final-only; tracked roots must finish verification."""
    return stage in {None, "synthesis", "failed"}


@dataclass
class DelegatedPrimaryReadState:
    """Require bounded source discovery/read attempts using only authorized tools."""

    enabled: bool
    has_source_urls: bool = False
    search_attempted: bool = False
    read_attempted: bool = False

    def select_tools(
        self, tools: list[dict[str, Any]], tool_choice: str, remaining_requests: int | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        if not self.enabled or self.read_attempted or tool_choice != "auto":
            return tools, tool_choice
        name = "web-read" if self.has_source_urls else (
            "web-search" if not self.search_attempted else None
        )
        selected = [tool for tool in tools if tool.get("function", {}).get("name") == name]
        if not name or not selected:
            return tools, tool_choice
        if remaining_requests is not None:
            limit = self.request_limit(name, remaining_requests)
            if limit <= 0:
                return tools, tool_choice
            selected = copy.deepcopy(selected)
            for tool in selected:
                requests = tool.get("function", {}).get("parameters", {}).get("properties", {}).get("requests")
                if isinstance(requests, dict):
                    requests["maxItems"] = min(requests.get("maxItems", limit), limit)
        return selected, "required"

    def request_limit(self, tool_name: str, remaining_requests: int) -> int:
        remaining = max(0, remaining_requests)
        if not self.enabled or self.read_attempted:
            return remaining
        if tool_name == "web-search":
            return max(0, remaining - 1)  # Keep one existing slot for the primary read.
        if tool_name == "web-read":
            return min(1, remaining)
        return remaining

    def bound_requests(self, arguments: Any, tool_name: str, remaining_requests: int):
        """Keep the model's ordered prefix; callers explicitly report every omission."""
        limit = self.request_limit(tool_name, remaining_requests)
        requests = arguments.get("requests") if isinstance(arguments, dict) else None
        if (not self.enabled or self.read_attempted or tool_name not in {"web-search", "web-read"}
                or not isinstance(requests, list) or len(requests) <= limit):
            return arguments, []
        return {**arguments, "requests": requests[:limit]}, requests[limit:]

    def observe_attempt(self, tool_name: str) -> None:
        # Validation and provider errors are still attempts, never forced retries.
        if self.enabled:
            self.search_attempted |= tool_name == "web-search"
            self.read_attempted |= tool_name == "web-read"

    def observe_search_results(self, results: Any) -> None:
        if not self.enabled:
            return
        if isinstance(results, list):
            for result in results:
                self.observe_search_results(result)
        elif (isinstance(results, dict) and not results.get("error")
              and results.get("status") not in {"error", "failed"}):
            self.has_source_urls |= has_http_source_url(results.get("url"))
            # Only the registered web-search result containers, never arbitrary
            # strings/instructions or URLs returned by unrelated/private apps.
            self.observe_search_results(results.get("results"))


def has_http_source_url(text: Any) -> bool:
    """Recognize assigned HTTP sources; the normal read skill still validates URLs."""
    if not isinstance(text, str):
        return False
    for candidate in re.findall(r"https?://[^\s<>\"`]+", text):
        try:
            parsed = urlsplit(candidate.rstrip(".,;)]}"))
            if parsed.hostname and not parsed.username and not parsed.password:
                return True
        except ValueError:
            continue
    return False
