"""Optional context must remain bound to the activation that selected it."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import agentic_context, context_preselection, rule_context
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.tests.test_rule_context import GUIDE, guide


# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,rules.ownership.encrypted-custom
@pytest.mark.asyncio
async def test_private_rule_decision_is_discarded_after_same_project_reactivation(monkeypatch):
    binding = {"project_id": "project", "activation_id": "activation-1"}
    monkeypatch.setattr(agentic_context, "fresh_project", AsyncMock(side_effect=lambda *args: dict(binding)))

    async def decision(**kwargs):
        binding["activation_id"] = "activation-2"
        return DecisionResponse(model="typesafe/jev-1.13", answers={
            key: {"type": "noul", "noul": 1} for key in kwargs["questions"]})

    monkeypatch.setattr(rule_context, "evaluate_jev_decisions", decision)
    request = SimpleNamespace(user_id="owner", chat_id="chat", current_user_content="Write reliable Python",
        custom_rule_documents=[{"id": "private-guide", "source": "project", "project_id": "project", "document": GUIDE}])
    selected = await agentic_context.select_rule_guides(request=request, directus=object(), cache=object(),
        eligible_app_ids=["code"], model_id="typesafe/jev-1.13", secrets_manager=None)
    assert selected == []


# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,rules.ownership.encrypted-custom
@pytest.mark.asyncio
async def test_preselected_rule_reload_rechecks_activation_after_body_resolution(monkeypatch):
    binding = {"activation_id": "activation-1"}
    monkeypatch.setattr(context_preselection, "fresh_project", AsyncMock(side_effect=lambda *args: dict(binding)))
    current = guide("private-guide", source="project", app_id=None, project_id="project")

    async def catalog(*args):
        binding["activation_id"] = "activation-2"
        return [current]

    monkeypatch.setattr(context_preselection, "_rules", catalog)
    request = SimpleNamespace(_preselected_rule_project_activation="activation-1")
    selected = await context_preselection.reload_preselected_rules(request, None, None, ["code"],
        [{"id": current.id, "revision": current.revision}])
    assert selected == []


# contract-test: supporting surface=rest_api assertions=rules.transparency.applied-set,focus-modes.context-reselection
def test_rule_receipts_deduplicate_retries_but_preserve_returning_phase_sets():
    request = SimpleNamespace(chat_id="chat", message_id="turn")
    first = agentic_context.receipt_event(request, {"type": "rules_loaded", "set_key": "A", "context_revision": "0"})
    retry = agentic_context.receipt_event(request, {"type": "rules_loaded", "set_key": "A", "context_revision": "0"})
    returning = agentic_context.receipt_event(request, {"type": "rules_loaded", "set_key": "A", "context_revision": "2"})
    assert first["event_id"] == retry["event_id"]
    assert first["event_id"] != returning["event_id"]


# contract-test: supporting surface=rest_api assertions=workflows.chat.relevance-discovery
def test_saved_graph_context_is_whole_and_bounded():
    small = {"workflow_id": "small", "graph": {"nodes": []}}
    large = {"workflow_id": "large", "graph": {"nodes": [{"instructions": "x" * 20_000}]}}
    prompt = agentic_context.context_prompt(rules=[], workflows=[large, small], documents=[], related=[])
    assert '"workflow_id": "small"' in prompt
    assert '"workflow_id": "large"' not in prompt
    assert '"nodes": []' in prompt
