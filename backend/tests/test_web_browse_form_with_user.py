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
def test_browse_use_older_than_three_assistant_turns_no_longer_forces_browse():
    history = [{"role": "assistant", "content": BROWSE_REF}]
    for n in range(3):
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
