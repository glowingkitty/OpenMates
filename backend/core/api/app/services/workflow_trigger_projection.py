"""Read-only next-run projection from the scheduler's authoritative trigger rows."""
from typing import Any


def project_workflow_next_runs(records: list[dict[str, Any]], triggers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Never show stale JSON times, completed once-runs, or another owner's trigger."""
    index = {(item.get("workflow_id"), item.get("owner_hash") or item.get("hashed_user_id")): item for item in triggers}
    projected = []
    for record in records:
        result = dict(record)
        trigger = index.get((record["id"], record.get("owner_hash"))) or {}
        next_run = trigger.get("next_run_at")
        result["next_run_at"] = next_run if (record.get("enabled") and trigger.get("enabled")
            and isinstance(next_run, int) and not isinstance(next_run, bool) and next_run > 0) else None
        projected.append(result)
    return projected
