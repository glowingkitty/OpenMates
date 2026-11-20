"""Specialised app skills are named before general web search for the request (TASK-2134)."""

# contract-test-file: infrastructure

from __future__ import annotations

from backend.apps.ai.processing.specialised_skill_preference import (
    empty_specialised_result_note,
    specialised_first_instruction,
)

OFFERED = {"events-search", "web-search", "web-browse", "news-search", "images-search", "videos-search"}


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_conference_question_names_events_search_before_web_search() -> None:
    instruction = specialised_first_instruction(
        {"events-search", "web-search", "web-browse"}, OFFERED, explicit_request=False,
    )
    assert instruction is not None
    assert "`events-search`" in instruction
    assert "call it first instead of `web-browse` or `web-search`" in instruction
    assert "fallback" in instruction
    # Baseline media and general news are never named as specialised.
    for general in ("news-search", "images-search", "videos-search"):
        assert f"`{general}`" not in instruction.split("instead of")[0]


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_no_instruction_without_both_a_specialised_skill_and_web_search() -> None:
    # Only general retrieval selected: web search is the right tool.
    assert specialised_first_instruction({"web-search", "news-search"}, OFFERED, explicit_request=False) is None
    # A specialised skill without web search on offer needs no preference.
    assert specialised_first_instruction({"events-search"}, {"events-search"}, explicit_request=False) is None
    # Skills added only as baseline or companions are not stage two's choice.
    assert specialised_first_instruction({"web-search"}, OFFERED, explicit_request=False) is None


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_explicit_skill_requests_keep_their_own_instruction() -> None:
    assert specialised_first_instruction(
        {"events-search", "web-search"}, OFFERED, explicit_request=True,
    ) is None


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_empty_specialised_result_names_web_search_as_the_fallback() -> None:
    note = empty_specialised_result_note("events-search", OFFERED, [{"id": "1", "results": []}])
    assert note is not None and "`web-search`" in note and "instead of from memory" in note
    assert empty_specialised_result_note("events-search", OFFERED, []) == note


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.conditional-context
def test_no_fallback_note_when_results_exist_or_web_search_is_not_offered() -> None:
    assert empty_specialised_result_note("events-search", OFFERED, [{"id": "1", "results": [{"title": "x"}]}]) is None
    assert empty_specialised_result_note("events-search", {"events-search"}, [{"id": "1", "results": []}]) is None
    # General retrieval never points to itself, and a failed request has its own error path.
    assert empty_specialised_result_note("web-search", OFFERED, [{"id": "1", "results": []}]) is None
    assert empty_specialised_result_note("news-search", OFFERED, [{"id": "1", "results": []}]) is None
    assert empty_specialised_result_note(
        "events-search", OFFERED, [{"id": "1", "results": [], "error": "unavailable"}]) is None
