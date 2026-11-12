"""A personal Memory selected by preprocessing becomes a `memory:<id>` load request.

Regression: Jev's selected-rule snapshots dropped `source`, so the preprocessor
never recognised a personal row; Ask first Memories were then also filtered out
as non-auto_include guides and no load request ever reached the client.
"""

import pytest

from backend.apps.ai.processing import jev_preprocessing
from backend.apps.ai.processing.rule_context import catalog_discovery, split_selected_rule_snapshots
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.python_utils.memory_loader import parse_memory_catalog

CATALOG = parse_memory_catalog([
    {"id": "career-profile", "title": "Career profile",
     "when_to_use": "Work history for a CV or application.", "load_mode": "ask_first", "source": "personal"},
    {"id": "eu-ai-updates", "title": "EU AI regulation updates",
     "when_to_use": "EU AI policy questions.", "load_mode": "auto_include", "source": "personal"},
])


def _answers(questions, selected_rule_ids):
    answers = {}
    for question_id, question in questions.items():
        if question["type"] == "noul":
            chosen = (question_id.startswith("rule_")
                      and question["instructions"]["candidate_id"] in selected_rule_ids)
            answers[question_id] = {"type": "noul", "noul": 0.95 if chosen else 0.05}
        elif question["type"] == "score":
            answers[question_id] = {
                "type": "score", "score": 0.1,
                "legend": {str(i): label for i, label in enumerate(question["criteria"])},
                "probabilities": {str(i): 1.0 if i == 0 else 0.0 for i in range(len(question["criteria"]))},
                "confidence": 0.99,
            }
        else:
            choices = list(question["criteria"])
            answers[question_id] = {"type": "choice", "choice": choices[0],
                                    "probabilities": {c: 1.0 if c == choices[0] else 0.0 for c in choices},
                                    "confidence": 0.99}
    return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})


async def _select(monkeypatch, selected_rule_ids):
    async def evaluate(**kwargs):
        return _answers(kwargs["questions"], selected_rule_ids)

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    rows = [catalog_discovery(entry) for entry in CATALOG] + [
        {"id": "app:jobs:cover-letter", "title": "Cover letters", "description": "Letter practice",
         "when_to_use": "Writing applications", "revision": "v1", "source": "app", "app_id": "jobs",
         "project_id": None, "load_mode": "auto_include"},
    ]
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Write a cover letter using what you know about me"}],
        topic_areas=["general_misc: General"], available_apps=["jobs"], selected_app_ids=["jobs"],
        available_skills=["jobs-search: Find jobs"], available_focus_modes=["jobs-write_application: Applications"],
        available_settings_and_memories={}, recent_skill_activity=[], conversation_summary=None,
        previous_category=None, is_first_message=False, available_rules=rows,
    )
    return split_selected_rule_snapshots(result["relevant_rules"], CATALOG)


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes
@pytest.mark.asyncio
async def test_selected_ask_first_memory_becomes_a_load_request(monkeypatch):
    memory_keys, guides = await _select(monkeypatch, {"career-profile", "app:jobs:cover-letter"})
    assert memory_keys == ["memory:career-profile"]
    assert [row["id"] for row in guides] == ["app:jobs:cover-letter"]


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes
@pytest.mark.asyncio
async def test_selected_auto_include_memory_is_requested_not_reloaded_as_a_guide(monkeypatch):
    memory_keys, guides = await _select(monkeypatch, {"eu-ai-updates"})
    assert memory_keys == ["memory:eu-ai-updates"]
    assert guides == []


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
def test_personal_rows_outside_the_catalog_are_never_requested():
    snapshots = [{"id": "invented", "revision": None, "source": "personal", "load_mode": "ask_first"},
                 {"id": "career-profile", "revision": None, "source": "personal", "load_mode": "ask_first"}]
    memory_keys, guides = split_selected_rule_snapshots(snapshots, CATALOG)
    assert memory_keys == ["memory:career-profile"]
    assert guides == []
