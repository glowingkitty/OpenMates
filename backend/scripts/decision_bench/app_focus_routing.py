"""App preselection and Focus activation (jev_preprocessing stage one and Focus selection).

Questions come from the production builders: ``_app_catalogue`` over the real
app.yml metadata (loaded offline like the cached discovery does) and
``_add_multi_select_questions`` for the app_N questions (stage one, cut-off
APP_SELECTION_THRESHOLD) and the focus_N questions (stage two, 0.75). Expected
answers name apps/focuses; they are checked against the built catalogue.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any

import yaml

from backend.apps.ai.processing.jev_preprocessing import (
    APP_SELECTION_THRESHOLD, _add_multi_select_questions, _app_catalogue, _app_id, _messages,
    _latest_user_text,
)
from backend.apps.ai.processing.preprocessor import _skill_routing_candidate
from backend.shared.python_schemas.app_metadata_schemas import AppYAML

SUITE = "app_focus_routing"
FOCUS_THRESHOLD = 0.75
APP_INSTRUCTION = ("Would this app's skills, Focus guidance, shipped Memory guides or user settings materially help "
                   "the latest request? Select the specialized app when its capability supports the requested task; "
                   "general web search must not substitute for that capability. Select every relevant app.")
FOCUS_INSTRUCTION = "Does this specialized focus mode clearly match the latest request? Normal chat should be false."
APPS_DIR = Path(__file__).resolve().parents[2] / "apps"


def load_apps() -> dict[str, Any]:
    """Parse every app.yml offline; the icon path is irrelevant to routing."""
    apps = {}
    for path in sorted(glob.glob(str(APPS_DIR / "*" / "app.yml"))):
        data = yaml.safe_load(open(path)) or {}
        if not str(data.get("icon_image", "")).endswith(".svg"):
            data["icon_image"] = "icon.svg"
        apps[os.path.basename(os.path.dirname(path))] = AppYAML(**data)
    return apps


def catalogue_inputs(apps: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    skills = [_skill_routing_candidate(a, s) for a, m in apps.items() for s in (m.skills or [])
              if (a, s.id) not in {("ai", "ask"), ("projects", "search")}]
    focuses = [f"{a}-{f.id}: {f.preprocessor_hint.strip()}" if f.preprocessor_hint else f"{a}-{f.id}"
               for a, m in apps.items() for f in (m.focuses or [])]
    return list(apps), skills, focuses


def history(*turns: str) -> list[dict[str, str]]:
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": text} for i, text in enumerate(turns)]


def base_state(msgs: list[dict[str, str]]) -> dict[str, Any]:
    return {"messages": _messages(msgs), "previous_category": None, "is_first_message": len(msgs) == 1,
            "recent_content_free_skill_activity": []}


def app_case(apps, skills, focuses, cid, turns, true_apps, false_apps):
    msgs = history(*turns)
    catalogue = _app_catalogue(apps, skills, focuses, None, request_text=_latest_user_text(msgs))
    questions: dict[str, dict] = {}
    key_map = _add_multi_select_questions(questions, "app", catalogue, APP_INSTRUCTION)
    by_app = {app: qid for qid, app in key_map.items()}
    expected = {}
    for app, value in [(a, True) for a in true_apps] + [(a, False) for a in false_apps]:
        assert app in by_app, f"{cid}: unknown app {app}"
        expected[by_app[app]] = value
    return {"id": cid, "suite": SUITE, "state": base_state(msgs), "questions": questions, "expected": expected,
            "rules": {q: {"at": APP_SELECTION_THRESHOLD} for q in expected}, "meta": {"stage": "app"}}


def focus_case(focuses, cid, turns, scope_apps, true_focus, false_focus):
    msgs = history(*turns)
    scoped = [f for f in focuses if _app_id(f.partition(": ")[0], set(scope_apps))]
    questions: dict[str, dict] = {}
    key_map = _add_multi_select_questions(questions, "focus", scoped, FOCUS_INSTRUCTION)
    by_focus = {fid: qid for qid, fid in key_map.items()}
    names = set(true_focus) | (set(false_focus) or set(by_focus) - set(true_focus))
    expected = {}
    for fid in names:
        assert fid in by_focus, f"{cid}: unknown focus {fid}"
        expected[by_focus[fid]] = fid in true_focus
    state = base_state(msgs) | {"effective_focus": {}}
    return {"id": cid, "suite": SUITE, "state": state, "questions": questions, "expected": expected,
            "rules": {q: {"at": FOCUS_THRESHOLD} for q in expected}, "meta": {"stage": "focus"}}


APP_ROWS = [
    ("weather-1", ["Will it rain in Hamburg tomorrow afternoon?"], ["weather"], ["travel", "music", "jobs"]),
    ("weather-de", ["Brauche ich morgen in Wien einen Regenschirm?"], ["weather"], ["music", "shopping"]),
    ("travel-1", ["Find me a train from Berlin to Prague next Friday."], ["travel"], ["weather", "code", "music"]),
    ("travel-2", ["Which hotel near the Louvre costs under 150 euros a night?"], ["travel"], ["code", "math"]),
    ("shopping-1", ["Where can I buy a cheap standing desk, 140 cm wide?"], ["shopping"], ["travel", "code"]),
    ("maps-1", ["Where is the nearest pharmacy to Alexanderplatz?"], ["maps"], ["music", "math"]),
    ("math-1", ["Calculate the compound interest on 5000 euros at 3.2% over 12 years."], ["math"], ["travel", "weather"]),
    ("code-1", ["Look up the docs for the Python requests library Session object."], ["code"], ["weather", "travel"]),
    ("code-2", ["Here is my repo, why does the test suite fail on Windows only?"], ["code"], ["weather", "shopping"]),
    ("image-gen", ["Generate a picture of a lighthouse at sunrise in watercolor style."], ["images"], ["math", "jobs"]),
    ("music-1", ["Compose a short upbeat jingle for my bakery."], ["music"], ["math", "weather"]),
    ("reminder-1", ["Remind me tomorrow at 9 to call the dentist."], ["reminder"], ["travel", "music"]),
    ("calendar-1", ["Add a dentist appointment to my calendar on Monday at 10."], ["calendar"], ["weather", "music"]),
    ("jobs-1", ["Search for remote data analyst jobs in Germany."], ["jobs"], ["travel", "music"]),
    ("news-fr", ["Quelles sont les dernières nouvelles sur les élections européennes ?"], ["news"], ["music", "math"]),
    ("pdf-1", ["Summarize the attached contract.pdf for me."], ["pdf"], ["weather", "music"]),
    ("recipe-1", ["Give me a vegetarian dinner recipe with chickpeas."], ["nutrition"], ["code", "math"]),
    ("diagram-1", ["Explain how our checkout microservices talk to each other, they use a queue and two databases."],
     ["diagrams", "mindmaps"], ["weather", "shopping"]),
    ("followup-weather", ["Will it rain in Hamburg tomorrow?", "Light rain is expected in the afternoon.", "And in Munich?"],
     ["weather"], ["music", "jobs"]),
    ("neg-chat", ["Thanks, that was really helpful!"], [], ["weather", "travel", "code", "music", "shopping"]),
    ("neg-fact", ["Why is the sky blue?"], [], ["weather", "travel", "shopping", "music"]),
]

FOCUS_ROWS = [
    ("focus-cv", ["Help me write a CV for a nursing job."], ["jobs"], ["jobs-create_cv"], ["jobs-career_insights", "jobs-prepare_interview"]),
    ("focus-cover", ["Help me write a cover letter for a software engineer position."], ["jobs"], ["jobs-write_application"], ["jobs-prepare_interview"]),
    ("focus-interview", ["I have a job interview Thursday, can we practice questions?"], ["jobs"], ["jobs-prepare_interview"], ["jobs-create_cv"]),
    ("focus-brand", ["I need a name for my new coffee brand."], ["business"], ["business-find_brand_name"], ["business-write_press_release"]),
    ("focus-press", ["Write a press release announcing our new product launch."], ["business"], ["business-write_press_release"], ["business-find_brand_name"]),
    ("focus-refactor", ["Please refactor this messy class into smaller functions."], ["code"], ["code-refactor_code"], ["code-test_git_repo", "code-analyze_logs"]),
    ("focus-logs", ["Here are the server logs, find out what caused the 500 errors."], ["code"], ["code-analyze_logs"], ["code-refactor_code"]),
    ("focus-study", ["Quiz me on the French Revolution to test what I know."], ["study"], ["study-test_knowledge"], ["study-what_to_study"]),
    ("focus-crisis", ["I feel completely overwhelmed and I do not see a way out."], ["life_coaching"], ["life_coaching-crisis_support"], []),
    ("focus-plants", ["My monstera has yellow leaves, how often should I water it?"], ["plants"], ["plants-plant_care_guide"], []),
    ("focus-neg-code", ["What does the git rebase command do?"], ["code"], [], []),
    ("focus-neg-jobs", ["What is the capital of Australia?"], ["jobs"], [], []),
    ("focus-neg-study", ["Thanks, that makes sense."], ["study"], [], []),
]


def cases(private_dir: Path | None) -> list[dict]:
    apps_meta = load_apps()
    apps, skills, focuses = catalogue_inputs(apps_meta)
    out = [app_case(apps, skills, focuses, f"afr-{cid}", turns, yes, no) for cid, turns, yes, no in APP_ROWS]
    out += [focus_case(focuses, f"afr-{cid}", turns, scope, yes, no) for cid, turns, scope, yes, no in FOCUS_ROWS]
    return out
