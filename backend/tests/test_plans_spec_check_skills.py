"""Plans specification and check skills: validation and embed result shapes."""

import pytest

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
