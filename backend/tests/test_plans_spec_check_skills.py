"""Plans specification and check skills: validation and embed result shapes."""

import pytest

from backend.apps.plans.skills.create_skill import CreateSkill
from backend.apps.plans.skills.check_skill import CheckSkill
from backend.apps.plans.skills.specification_skill import SpecificationSkill


def _skill(cls):
    return cls.__new__(cls)


def src(binding, kind, role="required", **extra):
    return {"source_binding_id": binding, "source_kind": kind, "role": role, "label": binding, **extra}


# contract-test: supporting surface=rest_api assertions=contracts.ui.human-readable-default
@pytest.mark.asyncio
async def test_specification_result_shape():
    result = await _skill(SpecificationSkill).execute(
        title=" Offline notes ", summary="Notes work offline.", outcome="Users keep notes offline",
        scope_included=["editor"], requirements=[{"id": "R1", "statement": "Saves locally", "example": "airplane mode"}],
        flows=[{"id": "F1", "title": "Write", "kind": "user_flow", "steps": ["open", "type"]}], chat_id="c1",
    )
    assert result.success and result.type == "specification" and result.title == "Offline notes"
    assert result.scope == {"included": ["editor"], "excluded": []}
    assert result.requirements[0]["example"] == "airplane mode" and result.chat_id == "c1"


# contract-test: supporting surface=rest_api assertions=contracts.ui.human-readable-default
@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,message", [
    ({"title": "", "summary": "s"}, "title"),
    ({"title": "t", "summary": ""}, "summary"),
    ({"title": "t", "summary": "s", "requirements": [{"id": "R1", "statement": "a"}, {"id": "R1", "statement": "b"}]}, "Duplicate"),
    ({"title": "t", "summary": "s", "requirements": [{"id": "R1", "statement": " "}]}, "statement"),
    ({"title": "t", "summary": "s", "flows": [{"id": "F1", "title": "x", "kind": "other"}]}, "kind"),
])
async def test_specification_validation_errors(kwargs, message):
    result = await _skill(SpecificationSkill).execute(**kwargs)
    assert not result.success and message in result.error


# contract-test: supporting surface=rest_api assertions=contracts.guided.assumptions-explicit,contracts.guided.linked-split
@pytest.mark.asyncio
async def test_specification_carries_role_assumptions_design_and_links():
    result = await _skill(SpecificationSkill).execute(
        title="Bakery ordering - product", summary="Customers order loaves online.", role="Product",
        assumptions=[" Pickup only, no delivery ", ""], design_decisions=["One-page order form"],
        related_specifications=[{"title": "Bakery ordering - technical", "role": "technical", "relation": "implements payments"}],
    )
    assert result.success and result.role == "product"
    assert result.assumptions == ["Pickup only, no delivery"] and result.design_decisions == ["One-page order form"]
    assert result.related_specifications == [{"title": "Bakery ordering - technical", "role": "technical", "relation": "implements payments"}]


# contract-test: supporting surface=rest_api assertions=contracts.guided.linked-split
@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,message", [
    ({"role": "marketing"}, "role must be"),
    ({"related_specifications": [{"title": " "}]}, "needs a title"),
    ({"related_specifications": [{"title": "x", "role": "legal"}]}, "role must be"),
    ({"assumptions": "pickup only"}, "assumptions must be a list"),
    ({"design_decisions": [f"d{i}" for i in range(41)]}, "at most 40"),
])
async def test_specification_guided_field_validation(kwargs, message):
    result = await _skill(SpecificationSkill).execute(title="t", summary="s", **kwargs)
    assert not result.success and message in result.error


# contract-test: supporting surface=rest_api assertions=checks.sources.mixed-types,checks.definition.reusable-revisioned
@pytest.mark.asyncio
async def test_check_result_shape_mixed_sources():
    result = await _skill(CheckSkill).execute(
        title="Sync works", description="d", covered_claims=["R1"], requires_deterministic=True, chat_id="c1",
        sources=[src("a", "e2e", test_target="sync.spec.ts"), src("b", "ai_evaluation", "supporting", question="Looks right?", threshold=0.8),
                 src("c", "human_confirmation", "supporting", instruction="Confirm on device")],
    )
    assert result.success and result.type == "check" and result.chat_id == "c1"
    assert [s["source_kind"] for s in result.sources] == ["e2e", "ai_evaluation", "human_confirmation"]
    assert result.sources[1]["threshold"] == 0.8


# contract-test: supporting surface=rest_api assertions=checks.sources.deterministic-for-sensitive-claims
@pytest.mark.asyncio
async def test_check_requires_deterministic_required_source():
    result = await _skill(CheckSkill).execute(
        title="Encryption", requires_deterministic=True,
        sources=[src("a", "ai_evaluation", question="ok?"), src("b", "unit", "supporting")],
    )
    assert not result.success and "deterministic" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("sources,message", [
    ([], "required source"),
    ([src("a", "unit", "supporting")], "required source"),
    ([src("a", "bogus")], "valid source_kind"),
    ([src("a", "unit"), src("a", "e2e")], "unique"),
    ([src("a", "ai_evaluation")], "question"),
    ([src("a", "human_confirmation")], "instruction"),
])
# contract-test: supporting surface=rest_api assertions=checks.sources.mixed-types
async def test_check_source_validation(sources, message):
    result = await _skill(CheckSkill).execute(title="t", sources=sources)
    assert not result.success and message in result.error


# contract-test: supporting surface=rest_api assertions=checks.sources.mixed-types
@pytest.mark.asyncio
@pytest.mark.parametrize("skill_id,arguments", [
    ("check", {"title": "Ordering works", "sources": [src("a", "e2e", test_target="order.spec.ts"),
                                                      src("b", "human_confirmation", "supporting", instruction="Taste it")]}),
    ("specification", {"title": "Ordering", "summary": "s", "scope_included": ["loaves", "pickup"],
                       "requirements": [{"id": "R1", "statement": "a"}, {"id": "R2", "statement": "b"}]}),
])
async def test_executor_keeps_check_and_specification_lists_in_one_call(monkeypatch, skill_id, arguments):
    # A Check's sources and a Specification's requirements are one definition,
    # not one request per list item (real Gemini run sent 2 sources -> 2 broken calls).
    from backend.apps.ai.processing import skill_executor

    captured = []

    async def execute(app_id, skill_id, arguments, *_args, **_kwargs):
        captured.append(arguments)
        return {"status": "ok"}

    monkeypatch.setattr(skill_executor, "execute_skill", execute)
    result = await skill_executor.execute_skill_with_multiple_requests("plans", skill_id, arguments, max_retries=0)
    assert result == [{"status": "ok"}]
    assert captured == [arguments]


# contract-test: supporting surface=rest_api assertions=plans.assumptions.investigated-before-work
@pytest.mark.asyncio
async def test_plan_create_mints_ids_and_returns_contract_payload():
    result = await _skill(CreateSkill).execute(
        title=" Offline notes ", summary="s", goal="g", specification_ref="spec-1",
        assumptions=[{"text": " Pickup only "}, {"text": "No delivery", "required_before": "task_execution"}],
        user_id="u1", chat_id="c1", message_id="m1",
    )
    action = result.pending_client_action
    assert result.success and result.plan_id == action["plan_id"]
    assert action["contract"] == "openmates.plan_create_request" and action["version"] == 1
    assert action["title"] == "Offline notes" and action["specification_ref"] == "spec-1"
    assert action["chat_id"] == "c1" and action["message_id"] == "m1" and action["action"] == "create"
    assert [a["text"] for a in action["assumptions"]] == ["Pickup only", "No delivery"]
    assert [a["required_before"] for a in action["assumptions"]] == ["implementation", "task_execution"]
    ids = [a["assumption_id"] for a in action["assumptions"]]
    assert result.assumption_ids == ids and len(set(ids)) == 2 and result.plan_id not in ids


# contract-test: supporting surface=rest_api assertions=plans.assumptions.investigated-before-work
@pytest.mark.asyncio
@pytest.mark.parametrize("assumptions,message", [
    ([{"text": " "}], "requires text"),
    ([{"text": "x" * 2001}], "exceeds"),
    ([{"text": "x", "required_before": "never"}], "required_before"),
    ([{"text": "x"}] * 21, "At most"),
])
async def test_plan_create_rejects_invalid_assumptions(assumptions, message):
    result = await _skill(CreateSkill).execute(title="t", assumptions=assumptions, user_id="u1")
    assert not result.success and message in result.error and result.pending_client_action is None
