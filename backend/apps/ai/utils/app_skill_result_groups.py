"""Presentation decisions for grouped app-skill results.

Ordinary failures use the existing error banner. Expected maps quota failures
keep a completed parent with zero children and a readable error explanation.
The tool result still reports its provider failure to the assistant and caller;
this helper controls only whether the result parent survives in the chat.
"""

from typing import Any

MAPS_QUOTA_STATUSES = {"quota_exhausted", "quota_unavailable", "rate_limited"}


def is_request_group_failure(app_id: str, skill_id: str, group: dict[str, Any]) -> bool:
    has_results = "results" in group
    if app_id == "hosting" and skill_id == "search_domains" and has_results:
        return False
    if app_id == "maps" and skill_id == "search" and isinstance(group.get("results"), list) and group.get("status") in MAPS_QUOTA_STATUSES:
        return False
    return bool(group.get("error")) or not has_results


def maps_result_parent_metadata(group: dict[str, Any]) -> dict[str, Any]:
    fields = ("provider", "warnings", "filter_summary", "coverage", "search_context", "error")
    metadata = {key: group[key] for key in fields if key in group}
    if "status" in group:
        metadata["search_status"] = group["status"]
    return metadata
