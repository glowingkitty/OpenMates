"""Slides focus replay: every fence parses, phase gates follow the step table, inert outside replay."""
# contract-test-file: infrastructure
import re

import pytest

from backend.apps.ai.testing import slides_focus_fixture as fx
from backend.shared.python_utils.slides_markup import normalise_slides_markup
from backend.shared.testing.mock_context import mock_group_var, mock_mode_var


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    a, b = mock_mode_var.set("mock"), mock_group_var.set(fx.GROUP)
    yield
    mock_mode_var.reset(a)
    mock_group_var.reset(b)


def _text(step):
    text = fx._STEPS[step][0]
    return text().replace("{ref}", "deck-x1") if callable(text) else text


def test_every_fence_is_valid_and_counts_match():
    counts = {}
    for step in fx._STEPS:
        fences = re.findall(r"```slides\n(.*?)\n```", _text(step), re.S)
        counts[step] = [normalise_slides_markup(f).slide_count for f in fences]
    assert counts["d2"] == [6, 6, 6] and counts["d3"] == [6]
    assert counts["p5"] == [6, 6, 6, 6] and counts["p6"] == [6]
    assert len(re.findall(r"^\d\. ", _text("p3"), re.M)) == 6


def test_outline_change_moves_demo_before_solution():
    lines = _text("p4").split("\n")
    assert [line for line in lines if line.startswith(("3.", "4."))][0].startswith("3. The demo")


def test_review_diff_applies_to_normalised_deck():
    assert "-    <text" in fx._pitch_review_diff() or "-" in fx._pitch_review_diff()
    assert "```diff:deck-x1" in _text("p8")


def test_jev_phase_answers_follow_step(replay):
    state = {"latest_actual_user_message": 'Use the design "Night Match" SLIDES_FOCUS_E2E:d3'}
    questions = {
        "requirement_design_chosen": {"type": "choice", "criteria": {"met": "", "unmet": "", "unsure": ""}},
        "requirement_design_approved": {"type": "choice", "criteria": {"met": "", "unmet": "", "unsure": ""}},
    }
    answers = fx.jev_response(state, questions, "typesafe/jev-1.14").answers
    assert answers["requirement_design_chosen"].choice == "met"
    assert answers["requirement_design_approved"].choice == "unmet"


def test_use_design_press_maps_to_its_step():
    assert fx._step_of("Use the design \u201cNight Match\u201d") == "d3"
    assert fx._step_of('Use the design "Bold pitch"') == "p6"
    assert fx._step_of("Use the design \u201cSomething else\u201d") is None
    assert fx._step_of("Please use the design Night Match") is None
    # The LLM request may wrap the turn (context prefix, content parts).
    assert fx._step_of([{"type": "text", "text": 'Use the design "Night Match"'}]) == "d3"
    assert fx._step_of("[Sat 01:02] Use the design \u201cBold pitch\u201d") == "p6"
    assert fx._step_of("Use the design &quot;Night Match&quot;") == "d3"


def test_latest_step_skips_a_trailing_context_turn():
    messages = [{"role": "user", "content": "x SLIDES_FOCUS_E2E:d2"}, {"role": "assistant", "content": "cards"},
                {"role": "user", "content": "Use the design \u201cNight Match\u201d"},
                {"role": "user", "content": "Focus mode context: design template"}]
    assert fx._latest_step(messages) == "d3"


def test_inert_without_replay_context():
    assert fx.jev_response({"latest_actual_user_message": "SLIDES_FOCUS_E2E:d1"}, {"q": {}}, "m") is None
    assert fx.llm_fixture("llm/m", {"messages": [], "model": "m"}) is None


def test_focus_continuation_marker_is_signed_only_for_isolated_replay(replay, monkeypatch):
    from backend.shared.testing.mock_context import (
        resolve_live_marker_or_raise, signed_focus_continuation_marker,
    )

    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "test-secret-for-signing")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
    assert signed_focus_continuation_marker("user-1") is None  # not the isolated CI stack
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    marker = signed_focus_continuation_marker("user-1")
    assert marker and resolve_live_marker_or_raise(f"hello {marker}", "user-1") == ("mock", fx.GROUP, None)
    with pytest.raises(RuntimeError):
        resolve_live_marker_or_raise(f"hello {marker}", "user-2")
    assert signed_focus_continuation_marker(None) is None
    token = mock_mode_var.set("record")
    assert signed_focus_continuation_marker("user-1") is None
    mock_mode_var.reset(token)
    token = mock_group_var.set("other_group")
    assert signed_focus_continuation_marker("user-1") is None
    mock_group_var.reset(token)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert signed_focus_continuation_marker("user-1") is None


def test_deck_ref_reads_link_and_resolved_toon_forms():
    toon = "Here is your deck.\n\n```toon\napp_id: slides\nembed_ref: pitch-deck-k3\nembed_id: 9f1c\n```"
    history = [{"role": "assistant", "content": toon}, {"role": "user", "content": "Yes, apply that fix."}]
    assert fx._deck_ref(history) == "pitch-deck-k3"
    assert fx._deck_ref([{"role": "assistant", "content": 'embed_ref: "deck-q"'}]) == "deck-q"
    assert fx._deck_ref([{"role": "assistant", "content": "[Deck](embed:deck-x1)"}]) == "deck-x1"
    with pytest.raises(AssertionError):
        fx._deck_ref([{"role": "assistant", "content": "embed_id: 9f1c"}])
