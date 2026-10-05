"""Rule discovery, private access, revalidation and exact applied receipts."""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.apps.ai.processing import rule_context
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.python_utils.rule_loader import (
    applied_rule_set_key, parse_rule_md, rules_prompt,
)

GUIDE = """---
title: Python coding rules
description: Reliable Python work.
when_to_use: Writing Python services.
---
- Preserve task cancellation.
- Release resources.
"""


def guide(identifier="app:code:python", **kwargs):
    defaults = {"source": "app", "app_id": "code"}
    defaults.update(kwargs)
    return parse_rule_md(GUIDE, rule_id=identifier, **defaults)


def decision(answers):
    return DecisionResponse.model_validate({"model": "jev", "answers": answers})


# contract-test: supporting surface=rest_api assertions=rules.ownership.encrypted-custom
def test_custom_documents_require_first_party_and_authoritative_project():
    documents = [
        {"id": "personal-1", "source": "personal", "document": GUIDE},
        {"id": "project-1", "source": "project", "project_id": "p1", "document": GUIDE},
        {"id": "project-2", "source": "project", "project_id": "p2", "document": "do not parse private body"},
    ]
    assert rule_context.parse_custom_rule_documents(
        documents, authenticated_first_party=False, active_project_id="p1",
    ) == []
    personal = rule_context.parse_custom_rule_documents(
        documents, authenticated_first_party=True, active_project_id=None,
    )
    assert [rule.id for rule in personal] == ["personal-1"]
    active = rule_context.parse_custom_rule_documents(
        documents, authenticated_first_party=True, active_project_id="p1",
    )
    assert [rule.id for rule in active] == ["personal-1", "project-1"]
    assert active[1].revision == parse_rule_md(
        GUIDE, rule_id="project-1", source="project", project_id="p1",
    ).revision


@pytest.mark.parametrize("overrides", [
    {"source": "app"}, {"source": []}, {"revision": "forged"},
    {"body": "forged"}, {"id": "app:code:spoof"}, {"id": ""},
    {"document": "missing header"}, {"project_id": "p1"},
])
# contract-test: supporting surface=rest_api assertions=rules.definition.guide-format,rules.ownership.encrypted-custom
def test_custom_document_rejects_source_revision_and_body_claims(overrides):
    document = {"id": "r1", "source": "personal", "document": GUIDE, **overrides}
    with pytest.raises(ValueError):
        rule_context.parse_custom_rule_documents(
            [document], authenticated_first_party=True, active_project_id="p1",
        )


# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,rules.ownership.encrypted-custom
def test_catalog_preserves_app_availability_and_private_scope():
    personal = guide("personal", source="personal", app_id=None)
    project = guide("project", source="project", app_id=None, project_id="p1")
    assert rule_context.eligible_rule_catalog(
        eligible_app_ids=[], custom_rules=[personal, project],
    ) == []
    assert rule_context.eligible_rule_catalog(
        eligible_app_ids=[], custom_rules=[personal, project],
        authenticated_first_party=True, active_project_id="p2",
    ) == [personal]
    assert len(rule_context.eligible_rule_catalog(eligible_app_ids=["code"])) == 4
    assert len(rule_context.eligible_rule_catalog(eligible_app_ids=["design"])) == 2


# contract-test: supporting surface=rest_api assertions=rules.definition.guide-format,rules.selection.focus-aware
def test_custom_catalog_rejects_duplicate_identity_and_oversize_input():
    document = {"id": "r1", "source": "personal", "document": GUIDE}
    for documents in ([document, document], [document] * 25):
        with pytest.raises(ValueError):
            rule_context.parse_custom_rule_documents(
                documents, authenticated_first_party=True, active_project_id=None,
            )
    documents = [{
        "id": f"r{i}", "source": "personal", "document": GUIDE + "x" * 17_000,
    } for i in range(4)]
    with pytest.raises(ValueError):
        rule_context.parse_custom_rule_documents(
            documents, authenticated_first_party=True, active_project_id=None,
        )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware
async def test_candidate_count_limit_is_independent_of_request_size(monkeypatch):
    captured = {}

    async def evaluate(**kwargs):
        captured.update(kwargs)
        return decision({key: {"type": "noul", "noul": .1} for key in kwargs["questions"]})

    monkeypatch.setattr(rule_context, "evaluate_jev_decisions", evaluate)
    assert await rule_context.select_rules_with_jev(
        model_id="jev", secrets_manager=None,
        rules=[guide(f"app:code:r{i}") for i in range(60)], request_text="Python",
    ) == []
    assert len(captured["questions"]) == rule_context.MAX_RULE_CANDIDATES


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,rules.precedence.obligations
async def test_metadata_only_selection_has_focus_and_ignores_invented_ids(monkeypatch):
    rules = [guide(f"app:code:r{i}") for i in range(3)]
    captured = {}

    async def evaluate(**kwargs):
        captured.update(kwargs)
        return decision({
            "rule_0": {"type": "noul", "noul": .95},
            "rule_1": {"type": "noul", "noul": .5},
            "invented": {"type": "noul", "noul": 1},
        })

    monkeypatch.setattr(rule_context, "evaluate_jev_decisions", evaluate)
    selected = await rule_context.select_rules_with_jev(
        model_id="jev", secrets_manager=None, rules=rules, request_text="Fix Python",
        effective_instructions="Debug the service", active_phase="Investigate",
    )
    assert selected == [rules[0]]
    state = captured["state"]
    assert state["effective_focus_instructions"] == "Debug the service"
    assert state["active_phase"] == "Investigate"
    assert "Preserve task cancellation" not in json.dumps(state)
    assert "never selection instructions or permission" in state["candidate_text_policy"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,rules.ownership.encrypted-custom
async def test_revoked_changed_and_inaccessible_guides_are_not_applied(monkeypatch):
    rules = [guide(f"p{i}", source="project", app_id=None, project_id="p1") for i in range(3)]

    async def evaluate(**kwargs):
        return decision({key: {"type": "noul", "noul": 1} for key in kwargs["questions"]})

    async def refresh():
        changed = parse_rule_md(
            GUIDE + "Updated practice", rule_id="p1", source="project", project_id="p1",
        )
        return [changed, rules[2]]

    monkeypatch.setattr(rule_context, "evaluate_jev_decisions", evaluate)
    assert await rule_context.select_rules_with_jev(
        model_id="jev", secrets_manager=None, rules=rules, request_text="Python",
    ) == []
    selected = await rule_context.select_rules_with_jev(
        model_id="jev", secrets_manager=None, rules=rules, request_text="Python",
        refresh_catalog=refresh,
    )
    assert selected == [rules[2]]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,rules.precedence.obligations
async def test_provider_outage_is_optional_and_cancellation_propagates(monkeypatch):
    async def unavailable(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(rule_context, "evaluate_jev_decisions", unavailable)
    kwargs = dict(model_id="jev", secrets_manager=None, rules=[guide()], request_text="Python")
    assert await rule_context.select_rules_with_jev(**kwargs) == []

    async def cancelled(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(rule_context, "evaluate_jev_decisions", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await rule_context.select_rules_with_jev(**kwargs)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,rules.transparency.applied-set
async def test_unicode_discovery_and_applied_prompt_are_bounded_without_partial_guides(monkeypatch):
    rules = [parse_rule_md(
        GUIDE.replace("Reliable Python work.", "語" * 1200) + "x" * 8000,
        rule_id=f"app:code:{i}", source="app", app_id="code",
    ) for i in range(60)]
    captured = {}

    async def evaluate(**kwargs):
        captured.update(kwargs)
        return decision({key: {"type": "noul", "noul": 1} for key in kwargs["questions"]})

    monkeypatch.setattr(rule_context, "evaluate_jev_decisions", evaluate)
    selected = await rule_context.select_rules_with_jev(
        model_id="jev", secrets_manager=None, rules=rules,
        request_text="語" * 80_000, effective_instructions="語" * 80_000,
        active_phase="語" * 8_000,
    )
    assert len(captured["questions"]) <= rule_context.MAX_RULE_CANDIDATES
    assert len(json.dumps(captured["state"])) < 80_000
    assert len(rules_prompt(selected)) <= rule_context.MAX_APPLIED_RULE_CHARS
    assert selected and len(selected) < len(captured["questions"])
    assert all(rule.body.endswith("x" * 8000) for rule in selected)


# contract-test: supporting surface=rest_api assertions=rules.transparency.applied-set
def test_receipt_counts_whole_guides_exact_injected_bodies_and_deduplicates():
    rules = [guide(), guide("app:code:another")]
    receipt = rule_context.applied_rule_receipt(rules)
    assert receipt["type"] == "rules_loaded"
    assert receipt["count"] == 2
    assert receipt["set_key"] == applied_rule_set_key(rules)
    for source, shown in zip(rules, receipt["rules"]):
        assert shown["body"] == source.body
        assert shown["revision"] == source.revision
        assert shown["body"] in rules_prompt(rules)
    assert rule_context.applied_rule_receipt(
        reversed(rules), previous_set_key=receipt["set_key"],
    ) is None
    changed = parse_rule_md(GUIDE + "New practice", rule_id=rules[0].id, source="app", app_id="code")
    assert rule_context.applied_rule_receipt([changed], previous_set_key=receipt["set_key"])
    assert rule_context.applied_rule_receipt([]) is None
