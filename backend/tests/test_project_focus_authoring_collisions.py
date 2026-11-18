"""Collision detection between a drafted Project Focus and the Project base focus."""
import json

import pytest

from backend.core.api.app.services.project_authoring_service import (
    _decode_focus_author_result,
    focus_author_provider_instructions,
    focus_author_provider_schema,
)

DOCUMENT = {"name": "Add provider", "description": "Adds a provider.", "when_to_use": "Provider work.",
            "instructions": "Install the provider SDK right away."}
BASE = "Always ask before adding dependencies."


def _source(collisions=None, *, include=True) -> str:
    envelope = {"status": "authored", "document_json": json.dumps(DOCUMENT), "question": None}
    if include:
        envelope["collisions"] = collisions
    return json.dumps(envelope)


# contract-test: supporting surface=rest_api assertions=focus-modes.conflict-detection
def test_collisions_are_parsed_and_checked() -> None:
    items = [{"topic": "Dependencies", "winner": "project", "touches_project_constraint": True},
             {"topic": "Output format", "winner": "focus", "touches_project_constraint": False}]
    result = _decode_focus_author_result(_source(items), base_instruction=BASE)
    assert result.collision_check == "checked"
    assert [c.topic for c in result.collisions] == ["Dependencies", "Output format"]


# contract-test: supporting surface=rest_api assertions=focus-modes.conflict-detection
def test_explicit_empty_list_with_base_is_checked() -> None:
    result = _decode_focus_author_result(_source([]), base_instruction=BASE)
    assert (result.collision_check, result.collisions) == ("checked", [])


# contract-test: supporting surface=rest_api assertions=focus-modes.conflict-detection
@pytest.mark.parametrize("base", [None, "", "   "])
def test_missing_base_is_not_checked(base) -> None:
    result = _decode_focus_author_result(_source([]), base_instruction=base)
    assert result.collision_check == "not_checked" and result.collisions == []


# contract-test: supporting surface=rest_api assertions=focus-modes.conflict-detection
@pytest.mark.parametrize("garbled", [
    None, "none", [{"topic": "x"}], [{"topic": "", "winner": "focus", "touches_project_constraint": False}],
    [{"topic": "x" * 201, "winner": "focus", "touches_project_constraint": False}],
    [{"topic": "x", "winner": "both", "touches_project_constraint": False}],
    [{"topic": "x", "winner": "project", "touches_project_constraint": False}] * 13,
])
def test_garbled_list_is_not_checked(garbled) -> None:
    result = _decode_focus_author_result(_source(garbled), base_instruction=BASE)
    assert result.collision_check == "not_checked" and result.collisions == []


# contract-test: supporting surface=rest_api assertions=focus-modes.conflict-detection
def test_omitted_list_is_not_checked() -> None:
    result = _decode_focus_author_result(_source(include=False), base_instruction=BASE)
    assert result.collision_check == "not_checked"


# contract-test: supporting surface=rest_api assertions=focus-modes.conflict-detection
def test_constraint_collision_must_have_project_winner() -> None:
    bad = [{"topic": "Dependencies", "winner": "focus", "touches_project_constraint": True}]
    assert _decode_focus_author_result(_source(bad), base_instruction=BASE).collision_check == "not_checked"


# contract-test: supporting surface=rest_api assertions=focus-modes.conflict-detection
def test_provider_contract_states_precedence_and_schema() -> None:
    assert "collisions" in focus_author_provider_schema()["properties"]
    text = focus_author_provider_instructions()
    assert "never overridden" in text and "winner project" in text
