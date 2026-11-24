"""Fill a web form together with the user: routing, result form view, URLs.

Specification: feature.app-skill.web-browse (form-with-user).
"""

from __future__ import annotations

import pytest

from backend.apps.ai.processing.browse_routing import (
    asks_to_work_through_linked_page,
    resolve_browse_intent,
)
from backend.core.api.app.services.web_browse_evidence import form_view
from backend.core.api.app.services.web_browse_service import user_given_url
from backend.shared.providers.browser_planner import PlanInvalid, validate_plan
from backend.shared.python_utils.web_browse_llm_view import (
    browse_embed_for_model,
    browse_result_for_model,
)

SKILLS = ["web-search", "web-read", "web-browse"]
FORM_URL = "https://forms.example.org/matching-form?event=founder-matching"
BROWSE_REF = '```json\n{"type":"app_skill_use","embed_id":"e1","app_id":"web","skill_id":"browse"}\n```'


@pytest.mark.parametrize(
    "text",
    [
        f"Can we fill out this form together? I'm unsure about some of the questions: {FORM_URL}",
        f"Please help me fill in the application at {FORM_URL}",
        f"Walk me through this form {FORM_URL}",
        f"Sign me up here: {FORM_URL}",
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_a_linked_form_to_work_through_selects_browse(text):
    assert asks_to_work_through_linked_page(text)
    assert resolve_browse_intent([{"role": "user", "content": text}], SKILLS) == ["web-browse"]


@pytest.mark.parametrize(
    "text",
    [
        f"What is this page about? {FORM_URL}",
        "How do I fill out a tax form?",
        f"Summarize {FORM_URL}",
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_reading_or_form_talk_without_a_link_does_not_force_browse(text):
    assert resolve_browse_intent([{"role": "user", "content": text}], SKILLS) == []


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_an_answer_inside_a_running_browse_session_keeps_browse():
    history = [
        {"role": "user", "content": f"Can we fill out this form together? {FORM_URL}"},
        {"role": "assistant", "content": f"Opening it.\n\n{BROWSE_REF}\n\nFirst question: your email?"},
        {"role": "user", "content": "alex.demo@example.org"},
    ]
    assert resolve_browse_intent(history, SKILLS) == ["web-browse"]
    assert resolve_browse_intent(history, ["web-search"]) == []


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_several_form_turns_without_a_browse_call_keep_browse():
    # Real form run: first name and last name were typed by the user through take
    # control and the profile links were left empty, three replies in a row with
    # no Browse call; the next answer must still reach the browser.
    history = [{"role": "assistant", "content": f"Filled.\n\n{BROWSE_REF}\n\nFirst name?"}]
    for answer in ("Alex", "Rivera", "Leave the links empty."):
        history += [{"role": "user", "content": answer}, {"role": "assistant", "content": "Please type it yourself. Next field?"}]
    history.append({"role": "user", "content": "Go with your suggestion."})
    assert resolve_browse_intent(history, SKILLS) == ["web-browse"]


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_browse_use_older_than_twelve_assistant_turns_no_longer_forces_browse():
    history = [{"role": "assistant", "content": BROWSE_REF}]
    for n in range(12):
        history += [{"role": "user", "content": f"q{n}"}, {"role": "assistant", "content": "plain"}]
    history.append({"role": "user", "content": "thanks"})
    assert resolve_browse_intent(history, SKILLS) == []


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_form_view_lists_fields_choices_and_form_navigation_in_page_order():
    observation = {
        "controls": [
            {"id": "0", "kind": "click", "role": "a", "label": "Home", "href": "https://example.org/"},
            {"id": "1", "kind": "type", "role": "input", "label": "Email", "value": "alex@example.org",
             "required": True},
            {"id": "2", "kind": "click", "role": "input", "label": "I have an idea", "checked": False,
             "group": "Do you have a startup idea?"},
            {"id": "3", "kind": "click", "role": "input", "label": "Join an idea", "checked": True,
             "group": "Do you have a startup idea?"},
            {"id": "4", "kind": "select", "role": "select", "label": "Industry", "value": "",
             "options": [{"label": "Health", "value": "h"}, {"label": "Climate", "value": "c"}]},
            {"id": "5", "kind": "click", "role": "button", "label": "Next"},
            {"id": "6", "kind": "click", "role": "button", "label": "Share on social"},
        ]
    }
    assert form_view(observation) == [
        {"label": "Email", "kind": "type", "value": "alex@example.org", "required": True},
        {"label": "I have an idea", "kind": "choice", "question": "Do you have a startup idea?",
         "checked": False},
        {"label": "Join an idea", "kind": "choice", "question": "Do you have a startup idea?",
         "checked": True},
        {"label": "Industry", "kind": "select", "options": ["Health", "Climate"]},
        {"label": "Next", "kind": "button"},
    ]


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_result_shows_the_users_own_start_url_instead_of_its_redacted_observation():
    redacted = "https://forms.example.org/matching-form?event=%5Bredacted%5D"
    assert user_given_url(redacted, FORM_URL) == FORM_URL
    other = "https://forms.example.org/thanks?ref=%5Bredacted%5D"
    assert user_given_url(other, FORM_URL) == other
    assert user_given_url(redacted, None) == redacted


@pytest.mark.parametrize(
    "url",
    [
        "https://forms.example.org/matching-form?event=[redacted]",
        "https://forms.example.org/matching-form?event=%5Bredacted%5D",
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_planner_cannot_navigate_to_a_redacted_url(url):
    with pytest.raises(PlanInvalid):
        validate_plan({"actions": [{"kind": "goto", "url": url}]}, {"controls": []})


EMAIL_FIELD = {"controls": [{"id": "c1", "kind": "type", "label": "Email address"}]}


@pytest.mark.parametrize("text", ["[EMAIL_1_org]", "Contact: [PHONE_567]", "[CARD_111]"])
# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_planner_never_types_a_privacy_placeholder(text):
    with pytest.raises(PlanInvalid):
        validate_plan({"actions": [{"kind": "type", "target": "c1", "text": text}]}, EMAIL_FIELD)


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_planner_types_an_ordinary_answer():
    plan = validate_plan(
        {"actions": [{"kind": "type", "target": "c1", "text": "alex.rivera.demo@example.org"}]}, EMAIL_FIELD
    )
    assert plan["actions"][0]["text"] == "alex.rivera.demo@example.org"


FORM = [{"label": "Email address", "kind": "type", "value": ""}]


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_answer_turn_gets_the_form_view_but_no_screenshot_or_metrics():
    payload = {
        "status": "needs_user",
        "data": None,
        "observations": {"form": FORM, "text": "unverified page text"},
        "screenshot_base64": "A" * 60000,
        "screenshot_ref": {"embed_id": "s1"},
        "metrics": {"steps": 3},
    }
    assert browse_result_for_model(payload) == {
        "status": "needs_user",
        "data": None,
        "observations": {"form": FORM},
    }


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_saved_browse_embed_reaches_history_without_screenshot_bytes():
    saved = {
        "app_id": "web",
        "skill_id": "browse",
        "embed_ref": "browse-form-abc",
        "results": [
            {
                "status": "completed",
                "data_json": "{}",
                "observations_form": FORM,
                "observations_text": "page text",
                "screenshot_base64": "A" * 60000,
                "screenshot_ref_embed_id": "s1",
                "metrics_steps": 3,
            }
        ],
    }
    view = browse_embed_for_model(saved)
    assert view["embed_ref"] == "browse-form-abc"
    assert view["results"] == [{"status": "completed", "data_json": "{}", "observations_form": FORM}]


# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_form_instruction_summary_follows_latest_observed_field_state():
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1] / "apps" / "web" / "app.yml"
    ).read_text()
    assert "only while the latest observation still shows it empty" in text
    assert "filled by the user" in text
