# contract-test-file: tooling
"""Tooling tests for the slides planner persona proof: template cards are design options, not the deck."""
import json

import slides_focus_persona_real_test as persona


def _messages() -> list[dict]:
    return [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "What is the goal and who is your audience?", "modelName": "Gemini 3.8 Flash"},
        {"role": "user", "content": "judges"},
        {"role": "assistant", "content": "Outline:\n1. a\n2. b\n3. c\n4. d\n5. e", "modelName": "Gemini 3.8 Flash"},
        {"role": "user", "content": "ok looks good"},
        {"role": "assistant", "content": "Pick a template", "modelName": "Gemini 3.8 Flash"},
        {"role": "user", "content": "bold pitch"},
        {"role": "assistant", "content": "Here is the deck. Want feedback?", "modelName": "Gemini 3.8 Flash"},
        {"role": "user", "content": "thanks"},
    ]


def test_template_cards_do_not_count_as_the_deck() -> None:
    decks = [
        {"message": 5, "source": "embed:4db45054", "template": True},
        {"message": 7, "source": "embed:12f59f76", "slides": 5, "with_notes": 5, "notes": ["Say hi"] * 5},
    ]
    checks = persona.deterministic_checks({"chat": {"activeFocusId": persona.FOCUS_ID}}, _messages(), decks)
    assert checks["every_slide_has_notes"] is True
    assert checks["deck_has_5_slides"] is True
    assert checks["deck_only_after_confirmed_outline"] is True


def test_template_markup_is_recognised_inside_stored_embed_json() -> None:
    body = json.dumps({"slides_markup": '<deck title="Bold pitch" template="builtin:plain" kind="template">'})
    assert persona.TEMPLATE_DECK.search(body)
    assert not persona.TEMPLATE_DECK.search(json.dumps({"slides_markup": '<deck title="Pitch" template="builtin:bold-pitch">'}))
    assert persona.TEMPLATE_DECK.search('<deck kind="template" template="builtin:calm-talk"></deck>')
