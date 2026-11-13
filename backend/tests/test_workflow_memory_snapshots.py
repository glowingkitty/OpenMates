"""Workflow Ask AI explicit Memory snapshots."""

from datetime import datetime, timezone

import pytest

from backend.core.api.app.services.workflow_ai_service import render_bounded_ask_ai_prompt
from backend.core.api.app.services.workflow_memory_snapshots import (
    MemorySnapshotError, normalize_step_snapshots, revision_records, usable_snapshots)
from backend.core.api.app.services.workflow_models import WorkflowGraph

NOW = datetime(2026, 12, 2, 6, 0, tzinfo=timezone.utc)
SNAP = {"title": "Writing style", "body": "SECRET-BODY terse", "revision": "r7",
        "valid_until": "2026-12-01T00:00:00Z", "taken_at": "2026-11-01T00:00:00Z"}
PROMPT = "Write in {{memory.m1}} voice"


def _graph(prompt: str, snapshots: dict) -> WorkflowGraph:
    return WorkflowGraph(nodes=[{"id": "ask", "type": "app_skill_action",
        "config": {"app_id": "ai", "skill_id": "ask", "input": {"prompt": prompt, "memory_snapshots": snapshots}}}])


# contract-test: direct surface=rest_api assertions=app-memories.workflows.explicit-snapshots
def test_snapshot_saved_only_on_explicit_mention():
    graph = _graph(PROMPT, {"m1": SNAP, "other": {**SNAP, "title": "Other"}})
    assert set(graph.nodes[0].config["input"]["memory_snapshots"]) == {"m1"}
    unmentioned = _graph("No mention", {"m1": SNAP})
    assert "memory_snapshots" not in unmentioned.nodes[0].config["input"]
    assert normalize_step_snapshots(PROMPT, {"m1": {"title": "x"}}) == {}


# contract-test: direct surface=rest_api assertions=app-memories.workflows.explicit-snapshots
def test_runtime_uses_only_snapshot_and_nothing_else():
    live = {**SNAP, "valid_until": "2027-01-01T00:00:00Z"}
    used = usable_snapshots(PROMPT, {"m1": live, "other": live}, NOW)
    assert [item["memory_id"] for item in used] == ["m1"]
    prompt = render_bounded_ask_ai_prompt(PROMPT, {}, used)
    assert "SECRET-BODY" in prompt and "{{" not in prompt
    assert "other" not in prompt.lower().replace("authored", "")


# contract-test: direct surface=rest_api assertions=app-memories.workflows.explicit-snapshots,app-memories.expiry.client-enforced
def test_expired_snapshot_is_not_used():
    with pytest.raises(MemorySnapshotError) as error:
        usable_snapshots(PROMPT, {"m1": SNAP}, NOW)
    assert error.value.code == "WORKFLOW_MEMORY_EXPIRED"


# contract-test: direct surface=rest_api assertions=app-memories.workflows.explicit-snapshots
def test_revision_recorded_without_body():
    live = {**SNAP, "valid_until": None}
    records = revision_records(usable_snapshots(PROMPT, {"m1": live}, NOW))
    assert records == [{"memory_id": "m1", "revision": "r7"}]
    assert "SECRET-BODY" not in str(records) and "Writing style" not in str(records)


# contract-test: direct surface=rest_api assertions=app-memories.workflows.explicit-snapshots
def test_deleted_memory_removes_snapshot_and_needs_attention():
    graph = WorkflowGraph(nodes=[{"id": "ask", "type": "app_skill_action", "config": {"app_id": "ai", "skill_id": "ask",
        "input": {"prompt": PROMPT, "memory_snapshots": {"m1": {**SNAP, "needs_attention": True}},
                  "memory_attention": {"m1": "deleted", "stale": "deleted"}}}}])
    stored = graph.nodes[0].config["input"]
    assert "memory_snapshots" not in stored and stored["memory_attention"] == {"m1": "deleted"}
    with pytest.raises(MemorySnapshotError) as error:
        usable_snapshots(PROMPT, stored.get("memory_snapshots"), NOW)
    assert error.value.code == "WORKFLOW_MEMORY_NEEDS_ATTENTION"
