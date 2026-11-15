"""Signed LIVE_MOCK replay for the two Slides focus modes (design a template, plan a presentation).

The real pipeline runs: focus activation by `@focus:slides:<id>`, the Jev phase gates
(`focus_phases.evaluate_boundary`), the stream consumer and the embed service. Only the
Jev decision provider and the model provider are replaced. Every user message of the
spec carries a `SLIDES_FOCUS_E2E:<step>` token; the step selects the assistant text
(which holds real slides fences, never an embed) and the phase gate answers. The real
"Use this design" press sends only the app's own text plus the group marker in the
`test_mock_marker` field, so its step comes from the design it names (`_DESIGN_USE_STEPS`).
Production and non-replay contexts stay inert.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from typing import Any, Mapping

from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.python_utils.slides_markup import normalise_slides_markup
from backend.shared.testing.mock_context import get_mock_group, mock_mode_var

GROUP = "slides_focus"
TOKEN = re.compile(r"SLIDES_FOCUS_E2E:([a-z0-9_]+)")
# Text the "Use this design" press sends (slidesTemplateUse.ts). The quotes may arrive straight,
# typographic, escaped or as HTML entities, so only the design name after the phrase counts.
_DESIGN_USE_STEPS = {"Night Match": "d3", "Bold pitch": "p6"}
_DESIGN_USE = re.compile(r"Use the design.{1,10}?(" + "|".join(map(re.escape, _DESIGN_USE_STEPS)) + ")")
# A deck shows as `embed:<ref>` in a link or, in resolved history, as the TOON field
# `embed_ref: <ref>` (embed_service.resolve_embed_references_in_content).
_EMBED_REF = re.compile(r"embed(?::|_ref:\s*\"?)([A-Za-z0-9._-]+)")

# Requirement ids of both focus modes, grouped in the order they are met.
_DESIGNER_MET = ("purpose_known", "summary_confirmed", "three_designs_shown", "design_chosen",
                 "changes_applied", "design_approved", "save_explained", "deck_offered")
_PLANNER_MET = ("basics_known", "basics_confirmed", "arc_proposed", "arc_confirmed", "outline_shown",
                "outline_confirmed", "template_options_shown", "template_chosen", "deck_created",
                "findings_reported", "accepted_fixes_applied")


def _template(title: str, theme: Mapping[str, str], mood: str) -> str:
    """A small valid template: theme line plus the six layouts with explicit positions."""
    t = " ".join(f'{key}="{value}"' for key, value in theme.items())
    return (
        f'<deck title="{title}" aspect="16:9" template="builtin:plain" kind="template">\n'
        f'  <theme {t}/>\n'
        '  <slide id="s1" layout="title">\n'
        '    <shape kind="rect" fill="accent" x="0" y="0" w="1920" h="120"/>\n'
        f'    <text role="title" x="160" y="380" w="1600" h="200" size="96" color="foreground">{title}</text>\n'
        f'    <text role="subtitle" x="160" y="600" w="1600" h="80" size="40" color="muted">{mood}</text>\n'
        '  </slide>\n'
        '  <slide id="s2" layout="section">\n'
        '    <shape kind="rect" fill="accent-2" x="160" y="420" w="240" h="16"/>\n'
        '    <text role="title" x="160" y="460" w="1600" h="160" size="80" color="foreground">Our season</text>\n'
        '  </slide>\n'
        '  <slide id="s3" layout="content">\n'
        '    <text role="title" x="160" y="100" w="1600" h="140" size="64" color="foreground">Training days</text>\n'
        '    <text role="body" x="160" y="280" w="1600" h="500" size="40" color="foreground">'
        '<ul><li>Tuesday and Thursday</li><li>Matches on Saturday</li><li>Everyone plays</li></ul></text>\n'
        '  </slide>\n'
        '  <slide id="s4" layout="image">\n'
        '    <shape kind="rect" fill="surface" x="160" y="160" w="900" h="700"/>\n'
        '    <text role="caption" x="1120" y="400" w="640" h="200" size="36" color="foreground">Team photo goes here</text>\n'
        '  </slide>\n'
        '  <slide id="s5" layout="quote">\n'
        '    <text role="quote" x="240" y="340" w="1440" h="300" size="56" color="accent">Play fair, play together.</text>\n'
        '  </slide>\n'
        '  <slide id="s6" layout="closing">\n'
        '    <text role="title" x="160" y="400" w="1600" h="160" size="80" color="foreground">See you on the pitch</text>\n'
        '  </slide>\n'
        '</deck>'
    )


CLUB_GREEN = {"heading": "Trebuchet MS", "body": "Verdana", "background": "#f4faf5", "foreground": "#12301c",
              "accent": "#1f9d55", "accent-2": "#f2c94c", "muted": "#5b7a65", "surface": "#ffffff"}
NIGHT_MATCH = {"heading": "Arial", "body": "Helvetica", "background": "#0f2a1a", "foreground": "#ffffff",
               "accent": "#2ecc71", "accent-2": "#ffffff", "muted": "#a8c8b4", "surface": "#18402a"}
SUMMER_SPRINT = {"heading": "Georgia", "body": "Trebuchet MS", "background": "#ffffff", "foreground": "#14532d",
                 "accent": "#22c55e", "accent-2": "#facc15", "muted": "#4b7a5c", "surface": "#ecfdf3"}
# The refined design keeps Night Match's colours with a lighter accent for contrast.
NIGHT_MATCH_REFINED = {**NIGHT_MATCH, "accent": "#4ade80", "muted": "#c4dccd"}

DESIGN_TITLES = ("Club Green", "Night Match", "Summer Sprint")
REFINED_TITLE = "Night Match"


def _fence(markup: str) -> str:
    return f"```slides\n{markup}\n```\n\n"


def _deck(title: str, template: str, theme: Mapping[str, str] | None, slides: list[tuple[str, str, str]]) -> str:
    theme_line = ("  <theme " + " ".join(f'{k}="{v}"' for k, v in theme.items()) + "/>\n") if theme else ""
    body = ""
    for index, (layout, heading, notes) in enumerate(slides, 1):
        body += (f'  <slide id="s{index}" layout="{layout}">\n'
                 f'    <text role="title" x="120" y="120" w="1680" h="200" size="72">{heading}</text>\n'
                 f'    <notes>{notes}</notes>\n  </slide>\n')
    return f'<deck title="{title}" aspect="16:9" template="{template}">\n{theme_line}{body}</deck>'


PITCH_OUTLINE = ("Hackathon pitch", "The problem: teams lose hours on manual status reports",
                 "The solution: a small assistant that reads your tools", "The demo: one click builds the report",
                 "The impact: five hours saved per team each week", "The ask: pilot it with two teams")
PITCH_SLIDES = [
    ("title", "Status reports in one click", "Greet the jury and say the one-line idea. About 20 seconds."),
    ("content", "Teams lose hours on status reports", "Tell the story of last week's report. About 40 seconds."),
    ("content", "Demo: the report builds itself", "Run the live demo, keep it under a minute. About 60 seconds."),
    ("content", "A small assistant reads your tools", "Explain in two sentences how it works. About 40 seconds."),
    ("content", "Five hours saved each week", "Show the number and where it comes from. About 30 seconds."),
    ("closing", "Pilot it with two teams", "State the ask and thank the jury. About 30 seconds."),
]
PITCH_DECK = _deck("Hackathon pitch", "builtin:bold-pitch", None, PITCH_SLIDES)


def _pitch_review_diff() -> str:
    """A unified diff against the normalised pitch deck, shortening one slide title."""
    before = normalise_slides_markup(PITCH_DECK).markup
    after = before.replace("Teams lose hours on status reports", "Status reports cost hours", 1)
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "a", "b", n=2))


def _outline(demo_before_solution: bool) -> str:
    items = list(PITCH_OUTLINE[1:])
    if demo_before_solution:
        items[1], items[2] = items[2], items[1]
    return "\n".join(f"{i}. {text}" for i, text in enumerate(["Status reports in one click", *items], 1))


def _builtin_cards() -> str:
    return "".join(_fence(f'<deck kind="template" template="builtin:{name}"></deck>')
                   for name in ("bold-pitch", "clean-business", "calm-talk", "friendly-classroom"))


# step -> (assistant text, requirement ids met at this step, assistant still waits for the user).
# The text may be a callable taking the chat history refs.
_STEPS: dict[str, tuple[Any, int, bool]] = {
    "d1": ("Happy to design your club template. Three quick questions. 1) Who watches your slides, parents, "
           "players or sponsors? (I would guess parents and players.) 2) Besides green and white, any accent "
           "colour? (A warm yellow works well.) 3) Do you have a logo or fonts to match? (If not, I will pick friendly ones.)",
           0, True),
    "d2": ("Summary: a friendly template for the youth sports club, for parents and players, in green and white, "
           "without a logo. Here are three clearly different designs.\n\n"
           + _fence(_template("Club Green", CLUB_GREEN, "Calm and light"))
           + _fence(_template("Night Match", NIGHT_MATCH, "Bold and dark"))
           + _fence(_template("Summer Sprint", SUMMER_SPRINT, "Playful and bright"))
           + "Club Green is calm and light, Night Match is bold and dark, Summer Sprint is playful. Press Use this "
           "design on a card or name the one you like. I recommend Night Match for evening events.",
           2, True),
    "d3": ("Night Match is a strong choice. I made the accent green lighter so text stays readable on the dark "
           "background; here is the refined template with all six layouts.\n\n"
           + _fence(_template(REFINED_TITLE, NIGHT_MATCH_REFINED, "Bold and dark, refined"))
           + "Do you want to change colours or fonts, or is it ready to save?",
           4, True),
    "d4": ("Great, the design is final. Press Save on the template card and it lands in your Personal library. "
           "Shall I create a first deck with it? Tell me what it is about.",
           8, True),
    "d5": ("Here is your first deck with the Night Match look.\n\n"
           + _fence(_deck("Summer camp", "builtin:plain", NIGHT_MATCH_REFINED, [
               ("title", "Summer camp 2027", "Welcome the parents and say the dates. About 30 seconds."),
               ("content", "A week of football and friends", "Describe a typical day. About 60 seconds."),
               ("closing", "Sign up before June", "Explain how to register. About 30 seconds.")]))
           + "The deck uses your saved design.", 8, False),
    "p1": ("Let us build it together. Three simple questions. 1) What should the jury think afterwards? (That the "
           "idea is worth a pilot.) 2) How long do you have, and is it on stage or online? (Five minutes on stage is "
           "typical.) 3) Who is in the jury? (Mostly engineers and one manager.)", 0, True),
    "p2": ("Summary: goal is to win the jury for a pilot, five minutes on stage, jury of engineers and one manager. "
           "A pitch story fits best: problem, demo, solution, impact, ask. It keeps the jury focused on the result.",
           2, True),
    "p3": ("Here is the outline, about one slide per minute:\n\n" + _outline(False)
           + "\n\nConfirm it or tell me what to change.", 4, True),
    "p4": ("Yes, showing the demo earlier keeps attention high. Updated outline:\n\n" + _outline(True)
           + "\n\nShall I use this outline?", 4, True),
    "p5": ("Now the look. Four built-in designs fit a pitch; I recommend Bold pitch for a hackathon.\n\n"
           + _builtin_cards()
           + "Bold pitch is high contrast, Clean business is calm, Calm talk is quiet, Friendly classroom is playful.",
           6, True),
    "p6": ("Here is your deck with six slides, one per outline message, and speaker notes on every slide.\n\n"
           + _fence(PITCH_DECK) + "Shall I review it against best practices?", 8, True),
    "p7": ("Review: slide 2 has a long title (text density), the demo slide could use a screenshot instead of text, "
           "and the timing fits five minutes. The close works well. I propose shortening the slide 2 title. "
           "Shall I apply it?", 9, True),
    "p8": (lambda: "I shortened the slide 2 title.\n\n```diff:{ref}\n" + _pitch_review_diff() + "```\n\n"
           "Practise the demo twice with a timer.", 11, False),
}


def active() -> bool:
    """Require the already authenticated request-scoped replay context."""
    return (mock_mode_var.get() == "mock" and get_mock_group() == GROUP
            and os.getenv("MOCK_EXTERNAL_APIS") == "true"
            and os.getenv("SERVER_ENVIRONMENT", "production").strip().lower() not in {"production", "prod"})


def _step_of(text: Any) -> str | None:
    found = TOKEN.findall(str(text or ""))
    if found:
        return found[-1] if found[-1] in _STEPS else None
    used = _DESIGN_USE.search(str(text or ""))
    return _DESIGN_USE_STEPS.get(used.group(1)) if used else None


def _state_step(state: Any) -> str | None:
    if not isinstance(state, Mapping):
        return None
    if "latest_actual_user_message" in state:
        return _step_of(state.get("latest_actual_user_message"))
    for message in reversed(state.get("messages") or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return _step_of(message.get("content"))
    return _step_of(state.get("user_message") or state.get("latest_user_message"))


def _met_ids(step: str) -> set[str]:
    count = _STEPS[step][1]
    return set((_PLANNER_MET if step.startswith("p") else _DESIGNER_MET)[:count])


def jev_response(state: Any, questions: Mapping[str, Mapping[str, Any]], model: str) -> DecisionResponse | None:
    """Answer the real Jev question batch (routing or phase gate) for this exact step."""
    step = _state_step(state)
    if not active() or step is None or not questions:
        return None
    met, waiting = _met_ids(step), _STEPS[step][2]
    preferred = {"complexity": "medium", "task_area": "creative", "topic_shift": "noticeable_shift",
                 "temperature": "creative", "preview": "none", "language": "en", "icon": "slides",
                 "project_target": "none", "topic_area": "general_misc"}
    answers: dict[str, dict[str, Any]] = {}
    for question_id, question in questions.items():
        kind, criteria = question.get("type"), question.get("criteria")
        if kind == "noul":
            answers[question_id] = {"type": kind, "noul": 0.0}
            continue
        if kind != "choice" or not isinstance(criteria, Mapping) or not criteria:
            return None
        if question_id.startswith("requirement_"):
            chosen = "met" if question_id.removeprefix("requirement_") in met else "unmet"
        elif question_id == "awaiting_user":
            chosen = "yes" if waiting else "no"
        elif question_id == "rewind":
            chosen = "none"
        else:
            chosen = preferred.get(question_id)
            chosen = chosen if chosen in criteria else next(iter(criteria))
        answers[question_id] = {"type": kind, "choice": chosen, "confidence": 1.0,
                                "probabilities": {str(key): float(key == chosen) for key in criteria}}
    return DecisionResponse.model_validate({"provider": "slides_focus_fixture", "model": model,
        "answers": answers, "usage": {"input_tokens": 100, "output_tokens": len(answers)}})


def _packet(model: str, answer: str) -> dict[str, Any]:
    google = "gemini" in model
    usage = ({"prompt_token_count": 100, "candidates_token_count": 20, "total_token_count": 120}
             if google else {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
    return {"response": {"type": "mixed_stream", "chunks": [
        {"kind": "text", "value": answer},
        {"kind": "pydantic", "module": "backend.apps.ai.llm_providers.google_client" if google
         else "backend.apps.ai.llm_providers.openai_shared", "class": "GoogleUsageMetadata" if google
         else "OpenAIUsageMetadata", "value": usage}]}}


def _latest_step(messages: Any) -> str | None:
    """Step of the newest user turn that names one (a context turn may follow the user's)."""
    for message in reversed(messages if isinstance(messages, list) else []):
        if isinstance(message, dict) and message.get("role") == "user":
            step = _step_of(message.get("content"))
            if step is not None:
                return step
    return None


def _deck_ref(messages: list[Any]) -> str:
    """The deck's embed reference as the history shows it; fail closed when missing."""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            refs = _EMBED_REF.findall(str(message.get("content") or ""))
            if refs:
                return refs[-1]
    raise AssertionError("The review edit needs the deck embed reference in the history")


def llm_fixture(category: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Replay the metadata call and the streamed assistant text of the current step."""
    if not active():
        return None
    messages = kwargs.get("messages")
    step = _latest_step(messages)
    model = str(kwargs.get("model") or kwargs.get("model_id") or "")
    task_id = kwargs.get("task_id")
    if step is None or not isinstance(task_id, str) or not task_id:
        return None
    names = {fn.get("name") for tool in kwargs.get("tools") or [] if isinstance(tool, dict)
             if isinstance(fn := tool.get("function"), dict)}
    if (category == f"llm_non_stream/{model}" and names == {"generate_suggestions_and_metadata"}
            and kwargs.get("tool_choice") == "required"):
        args = {"follow_up_app_skill_suggestions": [], "follow_up_general_suggestions": [],
                "new_chat_app_skill_suggestions": [], "new_chat_general_suggestions": [],
                "chat_summary": "Worked on slides with a focus mode.", "chat_tags": ["slides"],
                "share_cta_text": "Slides", "updated_chat_title": "Slides focus mode",
                "daily_inspiration_topic_suggestions": [], "memory_recommendations": [],
                "workflow_recommendations": []}
        return {"response": {"type": "non_stream", "value": {"kind": "pydantic",
            "module": "backend.apps.ai.llm_providers.openai_shared", "class": "UnifiedOpenAIResponse",
            "value": {"task_id": task_id, "model_id": model, "success": True, "tool_calls_made": [{
                "tool_call_id": "slides-focus-metadata", "function_name": "generate_suggestions_and_metadata",
                "function_arguments_raw": json.dumps(args), "function_arguments_parsed": args,
                "parsing_error": None}]}}}}
    if category != f"llm/{model}" or kwargs.get("stream") is False:
        return None
    text = _STEPS[step][0]
    if callable(text):
        text = text().replace("{ref}", _deck_ref(messages))
    return _packet(model, text)
