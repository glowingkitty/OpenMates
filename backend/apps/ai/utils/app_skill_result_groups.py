"""Presentation decisions for grouped app-skill results.

Ordinary failures use the existing error banner. Expected maps quota failures
keep a completed parent with zero children and a readable error explanation.
The tool result still reports its provider failure to the assistant and caller;
this helper controls only whether the result parent survives in the chat.
"""

from typing import Any

MAPS_QUOTA_STATUSES = {"quota_exhausted", "quota_unavailable", "rate_limited"}
SHOPPING_REFERENCE_FAILURE = "A reference image could not be accessed. Use its exact reference from this chat or upload it again."
SHOPPING_REQUEST_FAILURE = "The shopping request could not be completed."
SHOPPING_FAILURE_NOTICE = "Failed requests are not evidence of no matching products. Do not invent a catalogue or visual-matching explanation."


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


def jobs_result_parent_metadata(group: dict[str, Any]) -> dict[str, Any]:
    """Keep each Jobs parent tied to its own sources and bounded diagnostics."""
    metadata = {key: group[key] for key in ("country", "countries", "warnings") if key in group}
    providers = group.get("providers")
    if isinstance(providers, list):
        names = [name for name in providers if isinstance(name, str) and name]
        metadata["providers"] = names
        metadata["provider"] = ", ".join(names)
    return metadata


def shopping_result_parent_metadata(groups: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Keep comparison evidence and failed requests distinct from zero matches."""
    evaluations = []
    request_errors = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        request_id = group.get("id")
        if request_id is not None and type(request_id) not in (str, int):
            continue
        if group.get("error"):
            # Do not copy provider exception strings, URLs or image diagnostics
            # into model context or persisted previews.
            reference_errors = {
                "Reference image is unavailable to this caller",
                "Reference image is no longer available",
                "Reference images require an authenticated owner",
                "Reference image key is unavailable to this caller",
            }
            message = (SHOPPING_REFERENCE_FAILURE
                       if isinstance(group["error"], str) and group["error"] in reference_errors
                       else SHOPPING_REQUEST_FAILURE)
            request_errors.append({"request_id": request_id, "message": message})
        summary = group.get("visual_evaluation") if isinstance(group, dict) else None
        if not isinstance(summary, dict) or summary.get("status") not in {"evaluated", "partial", "unavailable"}:
            continue
        safe_summary = {"status": summary["status"]}
        for key in ("reference_count", "evaluated_count", "filtered_count", "minimum_score"):
            value = summary.get(key)
            if type(value) is int and 0 <= value <= 20:
                safe_summary[key] = value
        if isinstance(summary.get("notice"), str):
            safe_summary["notice"] = summary["notice"][:500]
        evaluations.append({"request_id": request_id, "visual_evaluation": safe_summary})
    metadata = {"visual_evaluations": evaluations} if evaluations else {}
    if request_errors:
        metadata["request_errors"] = request_errors
        metadata["failure_notice"] = SHOPPING_FAILURE_NOTICE
    return metadata


def sanitize_shopping_visual_evaluations(value: Any) -> list[dict[str, Any]]:
    """Preserve nested comparison status/ID without relaxing generic metadata exclusions."""
    if not isinstance(value, list):
        return []
    return shopping_result_parent_metadata([
        {"id": row.get("request_id"), "visual_evaluation": row.get("visual_evaluation") or {
            key: row.get(f"visual_evaluation_{key}") for key in (
                "status", "reference_count", "evaluated_count", "filtered_count", "minimum_score", "notice",
            )
        }}
        for row in value if isinstance(row, dict)
    ]).get("visual_evaluations", [])


def shopping_inference_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Retain bounded comparison/error evidence when history filters product rows.

    Generic result wrappers discard metadata for token efficiency. Shopping needs
    its server-authored evidence to distinguish filtered, unverified and failed
    requests, including an empty result list. Never copy arbitrary wrapper fields.
    """
    metadata: dict[str, Any] = {}
    raw_evaluations = payload.get("visual_evaluations")
    evaluations = sanitize_shopping_visual_evaluations(raw_evaluations[:20] if isinstance(raw_evaluations, list) else [])
    if evaluations:
        metadata["visual_evaluations"] = evaluations
    errors = payload.get("request_errors")
    if isinstance(errors, list):
        safe_errors = [{"request_id": row.get("request_id"), "message": row["message"]}
                       for row in errors[:20] if isinstance(row, dict)
                       and type(row.get("request_id")) in (str, int, type(None))
                       and row.get("message") in (SHOPPING_REFERENCE_FAILURE, SHOPPING_REQUEST_FAILURE)]
        if safe_errors:
            metadata["request_errors"] = safe_errors
            metadata["failure_notice"] = SHOPPING_FAILURE_NOTICE
    return metadata


def shopping_result_payload(results: list[dict[str, Any]], visual_metadata: dict[str, Any]) -> dict[str, Any]:
    """Use an explicit wrapper for comparison evidence, including zero matches.

    Ordinary calls retain their existing single-product or results/count shape.
    This helper is shared by TOON, JSON fallback and stored preview payloads.
    """
    if visual_metadata:
        return {"results": results, "count": len(results), **visual_metadata}
    return results[0] if len(results) == 1 else {"results": results, "count": len(results)}
