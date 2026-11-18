"""Wellbeing signal questions answered inside the existing preprocessing decision call.

Each signal is a 0..1 likelihood about the USER's own current state, judged from the
conversation so far. Shared by preprocessing and by the tuning benchmark.
"""

from __future__ import annotations

from typing import Any

WELLBEING_SIGNALS: tuple[str, ...] = (
    "suicidal", "method_or_means", "plan_or_timeline", "self_harm", "self_injury_now", "hopelessness_isolation",
    "eating_disorder", "reality_loss", "mania", "danger_from_others",
)
QUESTION_PREFIX = "wellbeing_"

_HARD_NEGATIVES = (
    " Score 0 for fiction, roleplay, song lyrics, research, school work, gaming, idioms, "
    "dark humour and worry about another person."
)
_INSTRUCTIONS: dict[str, str] = {
    "suicidal": "How strongly does the user express thoughts of ending their own life or not wanting to live? Count indirect wording too, such as saying goodbye, giving belongings away, putting affairs in order, or saying a day is 'the day' or that they will not be around.",
    "method_or_means": "Does the user mention a concrete method or means to end their own life or seriously hurt themselves, or access to it? Count vague wording such as having 'got what I need' or 'got something' for it.",
    "plan_or_timeline": "Does the user describe a concrete plan, preparation or time frame for ending their own life or seriously hurting themselves? Count a named day or occasion, giving things away, or something being arranged for 'tonight', 'Friday' or 'the weekend'.",
    "self_harm": "Does the user say they are hurting themselves or urgently want to hurt themselves, including having just injured themselves?",
    "self_injury_now": "Has the user just hurt themselves on purpose, or are they in physical danger right now from their own act, such as fresh wounds, bleeding, having taken too much of something, or feeling faint, dizzy or unwell afterwards? Score 0 for old injuries, accidents and urges that have not been acted on.",
    "hopelessness_isolation": "Does the user express lasting hopelessness, worthlessness, being a burden or being completely alone?",
    "eating_disorder": "Does the user describe their own disordered eating, purging, starving or compulsive body control?",
    "reality_loss": "Does the user describe their own beliefs or experiences that suggest a break from reality, such as persecution or voices, held with certainty?",
    "mania": "Does the user show signs of their own manic state, such as days without sleep with surging energy, grandiose plans and racing thoughts?",
    "danger_from_others": "Is the user currently in danger from another person, such as abuse, violence or coercion?",
}


def wellbeing_question_ids() -> dict[str, str]:
    """Map each signal to its decision question id."""
    return {signal: f"{QUESTION_PREFIX}{signal}" for signal in WELLBEING_SIGNALS}


def wellbeing_questions() -> dict[str, dict[str, Any]]:
    """Return the typesafe likelihood question definitions keyed by question id."""
    return {
        f"{QUESTION_PREFIX}{signal}": {
            "type": "noul",
            "instructions": _INSTRUCTIONS[signal] + _HARD_NEGATIVES,
        }
        for signal in WELLBEING_SIGNALS
    }
