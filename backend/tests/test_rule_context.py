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


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
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
    assert personal == []
    active = rule_context.parse_custom_rule_documents(
        documents, authenticated_first_party=True, active_project_id="p1",
    )
    assert [rule.id for rule in active] == ["project-1"]
    assert active[0].revision == parse_rule_md(
        GUIDE, rule_id="project-1", source="project", project_id="p1",
    ).revision


@pytest.mark.parametrize("overrides", [
    {"source": "app"}, {"source": []}, {"revision": "forged"},
    {"body": "forged"}, {"id": "app:code:spoof"}, {"id": ""},
    {"document": "missing header"}, {"app_id": "code"},
])
# contract-test: supporting surface=rest_api assertions=app-memories.definition.context-documents,app-memories.selection.source-scoped
def test_custom_document_rejects_source_revision_and_body_claims(overrides):
    document = {"id": "r1", "source": "project", "project_id": "p1", "document": GUIDE, **overrides}
    with pytest.raises(ValueError):
        rule_context.parse_custom_rule_documents(
            [document], authenticated_first_party=True, active_project_id="p1",
        )


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.selection.source-scoped
def test_catalog_preserves_app_availability_and_private_scope():
    personal = guide("personal", source="personal", app_id=None)
    project = guide("project", source="project", app_id=None, project_id="p1")
    assert rule_context.eligible_rule_catalog(
        eligible_app_ids=[], custom_rules=[personal, project],
    ) == []
    # Personal Auto include rules (admitted only via the metadata catalog) are
    # eligible for a first-party caller; Project rules need the active Project.
    assert rule_context.eligible_rule_catalog(
        eligible_app_ids=[], custom_rules=[personal, project],
        authenticated_first_party=True, active_project_id="p2",
    ) == [personal]
    assert len(rule_context.eligible_rule_catalog(eligible_app_ids=["code"])) == 4
    assert len(rule_context.eligible_rule_catalog(eligible_app_ids=["design"])) == 2


# contract-test: supporting surface=rest_api assertions=app-memories.definition.context-documents,app-memories.selection.source-scoped
def test_custom_catalog_rejects_duplicate_identity_and_oversize_input():
    document = {"id": "r1", "source": "project", "project_id": "p1", "document": GUIDE}
    for documents in ([document, document], [document] * 25):
        with pytest.raises(ValueError):
            rule_context.parse_custom_rule_documents(
                documents, authenticated_first_party=True, active_project_id="p1",
            )
    documents = [{
        "id": f"r{i}", "source": "project", "project_id": "p1", "document": GUIDE + "x" * 17_000,
    } for i in range(4)]
    with pytest.raises(ValueError):
        rule_context.parse_custom_rule_documents(
            documents, authenticated_first_party=True, active_project_id="p1",
        )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
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
# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.precedence.obligations
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
# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.selection.source-scoped
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
# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.precedence.obligations
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
# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.transparency.loaded-set
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


# contract-test: supporting surface=rest_api assertions=app-memories.transparency.loaded-set
def test_receipt_counts_whole_guides_exact_injected_bodies_and_deduplicates():
    rules = [guide(), guide("app:code:another")]
    receipt = rule_context.applied_rule_receipt(rules)
    assert receipt["type"] == "memories_loaded"
    assert receipt["count"] == 2
    assert receipt["set_key"] == applied_rule_set_key(rules)
    for source, shown in zip(rules, receipt["memories"]):
        assert shown["body"] == source.body
        assert shown["revision"] == source.revision
        assert shown["body"] in rules_prompt(rules)
    assert rule_context.applied_rule_receipt(
        reversed(rules), previous_set_key=receipt["set_key"],
    ) is None
    changed = parse_rule_md(GUIDE + "New practice", rule_id=rules[0].id, source="app", app_id="code")
    assert rule_context.applied_rule_receipt([changed], previous_set_key=receipt["set_key"])
    assert rule_context.applied_rule_receipt([]) is None


# ---- Memory catalog: metadata-only selection, load modes, approval ----------
from types import SimpleNamespace  # noqa: E402

from backend.apps.ai.processing import context_preselection  # noqa: E402
from backend.shared.python_utils.memory_loader import MemoryCatalogEntry, parse_memory_catalog  # noqa: E402

SECRET = "SECRET-BODY-TEXT"


def memory_doc(title="Trip prefs", when="Planning trips.", mode="auto_include", extra=""):
    when_line = f"when_to_use: {when}\n" if when else ""
    return f"---\ntitle: {title}\n{when_line}load_mode: {mode}\n{extra}---\n{SECRET}\n"


def entry(identifier="m1", title="Trip prefs", when="Planning trips.", mode="auto_include", source="personal"):
    return {"id": identifier, "title": title, "when_to_use": when, "load_mode": mode, "source": source}


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.document.canonical-shape
@pytest.mark.parametrize("bad", [
    {"load_mode": "mention_only"}, {"load_mode": "other"}, {"source": "app"}, {"id": "app:code:x"},
    {"id": ""}, {"title": ""}, {"title": "x" * 181}, {"when_to_use": "x" * 1201},
    {"id": " padded "}, {"body": "forged"},
])
def test_memory_catalog_rejects_invalid_rows(bad):
    with pytest.raises(ValueError):
        parse_memory_catalog([{**entry(), **bad}])


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes
def test_memory_catalog_bounds_and_blank_when_to_use():
    assert parse_memory_catalog(None) == ()
    assert parse_memory_catalog([entry(when="")])[0].when_to_use == ""
    with pytest.raises(ValueError):
        parse_memory_catalog([entry(f"m{i}") for i in range(25)])
    with pytest.raises(ValueError):
        parse_memory_catalog([entry("dup"), entry("dup")])
    with pytest.raises(ValueError):
        parse_memory_catalog("not a list")


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes
def test_request_schema_validates_memory_catalog():
    from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest
    fields = AskSkillRequest.model_fields
    assert fields["memory_catalog"].annotation.__args__[0] is MemoryCatalogEntry


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.selection.source-scoped
def test_personal_bodies_in_custom_documents_are_never_accepted():
    docs = [{"id": "m1", "source": "personal", "document": memory_doc()},
            {"id": "m2", "source": "personal", "document": memory_doc("Ask me", mode="ask_first")},
            {"id": "p-1", "source": "project", "project_id": "p1", "document": memory_doc("Proj")}]
    parsed = rule_context.parse_custom_rule_documents(
        docs, authenticated_first_party=True, active_project_id="p1")
    assert [rule.id for rule in parsed] == ["p-1"]


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.document.canonical-shape
@pytest.mark.asyncio
async def test_decision_provider_sees_only_title_and_when_to_use_never_bodies(monkeypatch):
    request = SimpleNamespace(
        user_id="u1", chat_id="c1",
        custom_rule_documents=[{"id": "m1", "source": "personal", "document": memory_doc()}],
        memory_catalog=[entry("m1"), entry("m2", "Needs asking", "Taxes.", "ask_first"), entry("m3", "Always on", "")],
    )

    async def no_project(*_):
        return None

    monkeypatch.setattr(context_preselection, "fresh_project", no_project)
    rows = await context_preselection.discover_rule_metadata(request, None, None, [])
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {"m1", "m2", "m3"}
    assert SECRET not in json.dumps(rows)
    assert by_id["m1"]["description"] == "" and by_id["m1"]["revision"] is None
    assert by_id["m1"]["load_mode"] == "auto_include"
    assert by_id["m2"]["load_mode"] == "ask_first" and by_id["m2"]["revision"] is None
    assert by_id["m3"]["when_to_use"] == ""


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.document.canonical-shape
def test_blank_when_to_use_rows_share_a_small_always_on_budget():
    rows = [{"source": "personal", "when_to_use": "", "id": f"b{i}"} for i in range(10)]
    rows += [{"source": "personal", "when_to_use": "x", "id": "scoped"}, {"source": "app", "when_to_use": "", "id": "app"}]
    kept = rule_context.bound_always_on(rows)
    assert sum(1 for row in kept if row["when_to_use"] == "" and row["source"] == "personal") == rule_context.MAX_ALWAYS_ON_MEMORIES
    assert {"scoped", "app"} <= {row["id"] for row in kept}


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.selection.source-scoped
@pytest.mark.asyncio
async def test_jev_state_has_no_private_body_and_ask_first_is_never_injected(monkeypatch):
    auto = parse_rule_md(memory_doc(), rule_id="m1", source="personal")
    ask = parse_rule_md(memory_doc("Ask me", mode="ask_first"), rule_id="m2", source="personal")
    captured = {}

    async def evaluate(**kwargs):
        captured.update(kwargs)
        return decision({key: {"type": "noul", "noul": .95} for key in kwargs["questions"]})

    monkeypatch.setattr(rule_context, "evaluate_jev_decisions", evaluate)
    refresh = lambda: asyncio.sleep(0, result=[auto, ask])  # noqa: E731
    selected = await rule_context.select_rules_with_jev(
        model_id="jev", secrets_manager=None, rules=[auto, ask], request_text="Trip",
        refresh_catalog=refresh)
    assert selected == [auto]
    assert SECRET not in json.dumps(captured["state"]) and SECRET not in json.dumps(captured["questions"])
    assert [row["id"] for row in captured["state"]["candidates"]] == ["m1"]
    assert captured["state"]["candidates"][0]["description"] == ""


# contract-test: supporting surface=rest_api assertions=app-memories.conversation.explicit-approval,app-memories.load-modes
def test_returned_content_applies_for_both_modes_only_when_requested_and_in_catalog():
    catalog = parse_memory_catalog([entry("m2", "Ask me", mode="ask_first"), entry("m1")])
    requested = ["memory:m1", "memory:m2"]
    approved, remaining = rule_context.approved_memory_definitions(
        {"memory:m2": memory_doc("Ask me", mode="ask_first"), "memory:m1": [memory_doc()],
         "code:prefs": {"a": 1}}, catalog, requested_keys=requested)
    assert sorted(rule.id for rule in approved) == ["m1", "m2"] and remaining == {"code:prefs": {"a": 1}}
    # Not requested for this turn, or absent from the stored snapshot: rejected.
    with pytest.raises(ValueError):
        rule_context.approved_memory_definitions(
            {"memory:m1": memory_doc()}, catalog, requested_keys=["memory:m2"])
    with pytest.raises(ValueError):
        rule_context.approved_memory_definitions(
            {"memory:ghost": memory_doc()}, catalog, requested_keys=["memory:ghost"])
    # Mention only: accepted solely through the mention cleartext path.
    mentioned, _ = rule_context.approved_memory_definitions(
        {"memory:secret": memory_doc("Mentioned", when="")}, catalog, mentioned_keys=["memory:secret"])
    assert [rule.id for rule in mentioned] == ["secret"]
    # Content must match the metadata the selection stage saw.
    with pytest.raises(ValueError):
        rule_context.approved_memory_definitions(
            {"memory:m2": memory_doc("Swapped")}, catalog, requested_keys=requested)


# contract-test: supporting surface=rest_api assertions=app-memories.expiry.client-enforced
def test_ids_the_client_excluded_from_the_catalog_cannot_be_loaded_even_if_requested():
    catalog = parse_memory_catalog([entry("m1")])  # expired/mention-only ids were removed client-side
    with pytest.raises(ValueError):
        rule_context.approved_memory_definitions(
            {"memory:expired": memory_doc("Old")}, catalog, requested_keys=["memory:expired"])


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes
def test_project_catalog_rows_are_not_part_of_the_personal_memory_flow():
    catalog = parse_memory_catalog([entry("p-1", "Proj", source="project", mode="ask_first"), entry("m1")])
    assert [row.id for row in rule_context.personal_catalog(catalog)] == ["m1"]
    with pytest.raises(ValueError):
        rule_context.approved_memory_definitions(
            {"memory:p-1": memory_doc("Proj", mode="ask_first")}, catalog, requested_keys=["memory:p-1"])


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.transparency.loaded-set
def test_snapshot_has_no_body_and_received_memories_join_the_loaded_receipt():
    catalog = parse_memory_catalog([entry("m1"), entry("m2", "Ask me", mode="ask_first")])
    snapshot = rule_context.memory_catalog_snapshot(rule_context.personal_catalog(catalog))
    assert SECRET not in json.dumps(snapshot)
    assert {row["id"] for row in snapshot} == {"m1", "m2"}
    assert set(snapshot[0]) == {"id", "title", "when_to_use", "load_mode", "source"}
    approved, _ = rule_context.approved_memory_definitions(
        {"memory:m1": memory_doc()}, catalog, requested_keys=["memory:m1"])
    receipt = rule_context.applied_rule_receipt([guide(), *approved])
    assert receipt["count"] == 2 and "m1" in {m["id"] for m in receipt["memories"]}


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes
@pytest.mark.asyncio
async def test_continuation_uses_stored_snapshot_limited_to_requested_ids():
    pytest.importorskip("redis", reason="handler imports the Redis cache service")
    from backend.core.api.app.routes.handlers.websocket_handlers import app_settings_memories_confirmed_handler as handler
    rows = rule_context.memory_catalog_snapshot(parse_memory_catalog([entry("m1"), entry("m2")]))

    class Encryption:
        async def decrypt_with_user_key(self, ciphertext, key_id):
            assert ciphertext == "sealed" and key_id == "vault"
            return json.dumps(rows)

    got = await handler._requested_memory_catalog(
        {"memory_catalog_ciphertext": "sealed"}, ["memory:m2", "code:prefs"], Encryption(), "vault")
    assert [row["id"] for row in got] == ["m2"] and SECRET not in json.dumps(got)
    assert await handler._requested_memory_catalog({}, ["memory:m2"], Encryption(), "vault") == []
