"""Mixed-source Check aggregation, validation, revision conflicts and Plan gating state."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.user_check_service import (
    CheckError, UserCheckService, aggregate_run_status, validate_result_kind, validate_revision_sources,
)


def src(binding, kind, role="required"):
    return {"source_binding_id": binding, "source_kind": kind, "role": role}


def res(binding, status):
    return {"source_binding_id": binding, "status": status}


MIXED = [src("e", "e2e"), src("u", "unit"), src("a", "ai_evaluation"), src("h", "human_confirmation"),
         src("s", "integration", "supporting")]


# contract-test: supporting surface=rest_api assertions=checks.sources.mixed-types,checks.aggregation.required-sources-gate
def test_mixed_sources_pass_only_when_every_required_source_passed():
    results = [res("e", "passed"), res("u", "passed"), res("a", "passed"), res("h", "passed")]
    assert aggregate_run_status(MIXED, results) == "passed"
    assert aggregate_run_status(MIXED, results[:3] + [res("h", "waived")]) == "passed"


# contract-test: direct surface=rest_api assertions=checks.aggregation.required-sources-gate
def test_required_failure_wins_over_everything():
    results = [res("e", "failed"), res("u", "error"), res("a", "running"), res("h", "pending")]
    assert aggregate_run_status(MIXED, results) == "failed"


# contract-test: direct surface=rest_api assertions=checks.aggregation.required-sources-gate,checks.human.waiting-for-confirmation
def test_priority_error_blocked_running():
    base = [res("e", "passed"), res("u", "passed"), res("a", "passed"), res("h", "passed")]
    assert aggregate_run_status(MIXED, [res("a", "error")] + base[:2] + base[3:]) == "error"
    assert aggregate_run_status(MIXED, base[:2] + [res("a", "blocked")] + base[3:]) == "blocked"
    assert aggregate_run_status(MIXED, base[:2] + [res("a", "running")] + base[3:]) == "running"
    assert aggregate_run_status(MIXED, []) == "running"


# contract-test: supporting surface=rest_api assertions=checks.aggregation.required-sources-gate
def test_supporting_failure_does_not_gate():
    results = [res("e", "passed"), res("u", "passed"), res("a", "passed"), res("h", "passed"), res("s", "failed")]
    assert aggregate_run_status(MIXED, results) == "passed"


# contract-test: supporting surface=rest_api assertions=checks.human.waiting-for-confirmation
def test_pending_human_only_is_waiting_not_failed():
    results = [res("e", "passed"), res("u", "passed"), res("a", "passed")]
    assert aggregate_run_status(MIXED, results) == "waiting_for_confirmation"
    assert aggregate_run_status(MIXED, results + [res("h", "rejected")]) == "waiting_for_confirmation"
    assert aggregate_run_status(MIXED, results + [res("h", "failed")]) == "failed"


# contract-test: supporting surface=rest_api assertions=checks.sources.deterministic-for-sensitive-claims
def test_security_claim_needs_required_deterministic_source():
    ai_human = [src("a", "ai_evaluation"), src("h", "human_confirmation"), src("u", "unit", "supporting")]
    with pytest.raises(CheckError) as caught:
        validate_revision_sources(ai_human, True)
    assert caught.value.code == "CHECK_DETERMINISTIC_SOURCE_REQUIRED" and caught.value.status_code == 422
    validate_revision_sources(ai_human, False)
    validate_revision_sources([src("a", "ai_evaluation"), src("e", "e2e")], True)


# contract-test: direct surface=rest_api assertions=checks.definition.reusable-revisioned
def test_requires_one_required_source_and_unique_bindings():
    with pytest.raises(CheckError, match="CHECK_REQUIRED_SOURCE_MISSING"):
        validate_revision_sources([src("e", "e2e", "supporting")], False)
    with pytest.raises(CheckError, match="CHECK_SOURCE_INVALID"):
        validate_revision_sources([src("e", "e2e"), src("e", "unit")], False)


# contract-test: direct surface=rest_api assertions=checks.types.explicit,checks.sources.mixed-types
def test_result_kind_must_match_binding():
    assert validate_result_kind(MIXED, "e", "e2e")["source_kind"] == "e2e"
    with pytest.raises(CheckError) as caught:
        validate_result_kind(MIXED, "e", "unit")
    assert caught.value.code == "CHECK_RESULT_MISMATCH" and caught.value.status_code == 422
    with pytest.raises(CheckError, match="source_not_found"):
        validate_result_kind(MIXED, "zzz", "unit")


def directus(head=None):
    return SimpleNamespace(
        project=SimpleNamespace(get_project=AsyncMock(return_value={"project_id": "p"})),
        get_items=AsyncMock(return_value=[head] if head else []), create_item=AsyncMock(),
        _update_item=AsyncMock(return_value={}), _delete_item=AsyncMock(return_value=True),
    )


# contract-test: supporting surface=rest_api assertions=checks.runs.revision-bound
@pytest.mark.asyncio
async def test_revision_conflict_is_409_and_nothing_is_written():
    head = {"id": "row", "check_id": "c1", "current_revision_id": "rev-2", "current_revision_number": 2,
            "hashed_user_id": "h", "hashed_team_id": None, "status": "ready"}
    cms = directus(head)
    body = {"base_revision_id": "rev-1", "revision_id": "rev-3", "definition_hash": "x",
            "requires_deterministic": False, "sources": [src("e", "e2e")], "encrypted_definition": "c"}
    with pytest.raises(CheckError) as caught:
        await UserCheckService(cms).revise("c1", "owner", body)
    assert caught.value.status_code == 409 and caught.value.code == "revision_conflict"
    cms.create_item.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=checks.artifacts.private-traceable
@pytest.mark.asyncio
async def test_missing_check_is_404_for_foreign_owner():
    with pytest.raises(CheckError) as caught:
        await UserCheckService(directus()).get_check("c1", "other")
    assert caught.value.status_code == 404


# contract-test: direct surface=rest_api assertions=checks.human.explicit-confirmation,checks.human.waiting-for-confirmation
@pytest.mark.asyncio
async def test_human_confirm_recomputes_run_to_passed():
    run = {"id": "r-row", "run_id": "run1", "check_id": "c1", "check_revision_id": "rev1", "status": "waiting_for_confirmation"}
    revision = {"revision_id": "rev1", "sources": [src("e", "e2e"), src("h", "human_confirmation")]}
    stored = [{"source_binding_id": "e", "status": "passed"}]
    cms = directus()

    async def get_items(collection, params=None, **_):
        if collection == "user_check_runs":
            return [run]
        if collection == "user_check_revisions":
            return [revision]
        if collection == "user_check_source_results":
            if "filter[source_binding_id][_eq]" in params:
                return []
            return stored + ([{"source_binding_id": "h", "status": "passed"}] if cms.create_item.await_count else [])
        return []

    cms.get_items.side_effect = get_items
    cms.create_item.return_value = (True, {})
    out = await UserCheckService(cms).confirm("run1", "h", "owner", {"decision": "confirmed"})
    assert out["run"]["status"] == "passed"
    assert cms._update_item.await_args.args[2]["status"] == "passed"
    with pytest.raises(CheckError, match="CHECK_RESULT_MISMATCH"):
        await UserCheckService(cms).confirm("run1", "e", "owner", {"decision": "confirmed"})


# contract-test: supporting surface=rest_api assertions=checks.runs.revision-bound
@pytest.mark.asyncio
async def test_plan_required_checks_state_buckets_latest_run_on_current_revision():
    cms = directus()
    heads = {c: {"check_id": c, "current_revision_id": "rev-" + c, "status": "ready"} for c in "abcdef"}
    runs = {"a": "passed", "b": "failed", "c": "running", "d": "waiting_for_confirmation", "e": None, "f": "error"}

    async def get_items(collection, params=None, **_):
        if collection == "user_plan_check_links":
            return [{"check_id": c} for c in "abcdef"]
        check = params["filter[check_id][_eq]"]
        if collection == "user_checks":
            return [heads[check]]
        assert params["filter[check_revision_id][_eq]"] == "rev-" + check
        return [{"run_id": "r" + check, "status": runs[check]}] if runs[check] else []

    cms.get_items.side_effect = get_items
    state = await UserCheckService(cms).plan_required_checks_state(["plan-1"])
    assert state == {"required_total": 6, "passed": 1, "failing": 2, "running": 1,
                     "waiting_for_confirmation": 1, "missing_run": 1}
    assert (await UserCheckService(cms).plan_required_checks_state([]))["required_total"] == 0
