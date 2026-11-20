"""Fixed-goal scenarios for one-off AI test-user runs (`ai_test_users.py run --scenario <name>`).

A scenario persona must reach every goal: an unmet goal counts as a problem in the run summary
(daily personas explore, so their unfinished goals never do). Each flow runs `--repeat` times on
fresh accounts; `flow_verdicts` calls a flow working when every repeat reached all goals, flaky
when some did and broken when none did. All data in the goals is synthetic.
"""

from __future__ import annotations

import ai_test_users_report as reporting
from ai_test_users_personas import MACBOOK

FOSDEM_QUESTION = "What is the largest open source software conference in Europe and when does it happen?"

# Synthetic co-speaker details (example.org address, reserved-looking phone number).
TALK_PROPOSAL = (
    "Talk proposal draft: 'Private by default: building an AI assistant that never sees your secrets'. "
    "Abstract: we show how a chat app can detect personal data in the browser and send placeholders "
    "instead, and what we learned running it for a year. Speakers: me and my co-speaker Jonas Albrecht "
    "(jonas.albrecht@example.org, +49 151 23456789, Lindenstrasse 12, 10969 Berlin). "
    "Length: 25 minutes plus Q&A."
)

_BASE = {
    "language": "English",
    "device_label": "MacBook 1440x900",
    "device": MACBOOK,
    "required_goals": True,
}

INTRO_VIDEO: list[dict] = [
    {
        **_BASE,
        "flow": "a_fosdem_chat",
        "name": "Mara (34), open source developer, intro-video flow a",
        "description": "Recording the product intro video: asks one clear question and checks the answer closely.",
        "goals": [
            f'Start a new chat and type exactly: "{FOSDEM_QUESTION}" then send it and wait for the full answer.',
            "Check the answer names FOSDEM, explains what it is, where (Brussels) and when it happens, "
            "and shows at least one event embed card for FOSDEM in the chat.",
            "Open the FOSDEM event embed in fullscreen, check it shows the event details, then close it.",
        ],
        "areas": ["chat answer", "events app", "embeds and fullscreen"],
    },
    {
        **_BASE,
        "flow": "b_privacy_placeholders",
        "name": "Mara (34), open source developer, intro-video flow b",
        "description": "Recording the privacy part of the intro video: pastes a draft with a co-speaker's contact details.",
        "goals": [
            "Start a new chat and type this message, then wait before sending until the composer has marked "
            f'personal data: "Please help me polish this talk proposal. {TALK_PROPOSAL}"',
            "Before sending, check the composer marks the co-speaker's name, email, phone number and address as "
            "personal data. Send the message and wait for the full answer.",
            "Check the personal details turned into placeholders in what was sent (not sent as raw text), and that "
            "the answer is a polished proposal that keeps the co-speaker's details as placeholders or restored "
            "values, never mixed up or invented.",
        ],
        "areas": ["privacy", "personal data placeholders", "chat answer"],
    },
    {
        **_BASE,
        "flow": "c_model_picker_export",
        "name": "Mara (34), open source developer, intro-video flow c",
        "description": "Recording the model choice and export part of the intro video.",
        "downloads": True,
        "goals": [
            "Start a new chat, open the model picker in the message composer, look at the available models and "
            "pick a different model than the default one.",
            "Ask: \"Give me three tips for a first-time FOSDEM visitor.\" and wait for the full answer; check the "
            "answer says or shows which model answered and that it is the model you picked.",
            "Export this chat (chat menu or chat options, Export or Download) and check the export finishes "
            "(a download event appears in the transcript, or the app confirms the export).",
        ],
        "areas": ["model picker", "chat export", "chat answer"],
    },
    {
        **_BASE,
        "flow": "d_workflow",
        "name": "Mara (34), open source developer, intro-video flow d",
        "description": "Recording the workflows part of the intro video: creates and tests one simple workflow.",
        "goals": [
            "Open Workflows and create a simple new workflow: every Monday at 9:00, search the web for news about "
            "FOSDEM and send me a short summary. Save it.",
            "Test the workflow once (Run now, Test or a similar button) and wait for its result.",
            "Check the run finishes and shows a short FOSDEM news summary, and that the workflow appears in your "
            "list of workflows with its schedule.",
        ],
        "areas": ["workflows", "workflow run"],
    },
    {
        **_BASE,
        "flow": "e_dictation_voice_video",
        "name": "Mara (34), open source developer, intro-video flow e",
        "description": "Recording the voice part of the intro video: dictation, then a voice call, then a video call.",
        "voice_text": FOSDEM_QUESTION,
        "camera": True,
        "goals": [
            "Start a new chat and use the microphone/dictation button in the composer to dictate the question (the "
            "microphone plays it). Check the transcribed text appears in the composer, then send it and wait for "
            "the answer.",
            "Switch this chat to a voice call (call button). Wait until the call is live (a running timer in the "
            "call bar), stay about 30 seconds and check the assistant answers by voice or with live text.",
            "While the call is live, turn the camera on with the Video call (camera) button in the call bar. Check "
            "your camera picture appears and the assistant still responds, then hang up and check the chat shows "
            "the call.",
        ],
        "areas": ["dictation", "voice call", "video call"],
    },
]

SCENARIOS: dict[str, list[dict]] = {"intro-video": INTRO_VIDEO}


def personas_for(name: str, repeat: int = 1, flows: str = "") -> list[dict]:
    """The scenario's flows, each `repeat` times, with unique ids (`<flow>-<n>`) for separate accounts.

    `flows` keeps only flows whose letter or name is listed (comma separated, e.g. "b,c,e")."""
    if name not in SCENARIOS:
        raise SystemExit(f"unknown scenario {name}; known: {', '.join(SCENARIOS)}")
    wanted = {f.strip() for f in flows.split(",") if f.strip()}
    chosen = [f for f in SCENARIOS[name] if not wanted or f["flow"] in wanted or f["flow"].split("_", 1)[0] in wanted]
    if not chosen:
        raise SystemExit(f"no flow of {name} matches {flows}")
    return [{**flow, "id": f"{flow['flow']}-{n}"} for n in range(1, max(1, repeat) + 1) for flow in chosen]


def goals_met(result: dict) -> bool:
    outcomes = result.get("goal_outcomes") or []
    return bool(outcomes) and all(o.get("achieved") is True for o in outcomes)


def flow_verdicts(results: list[dict]) -> dict[str, dict]:
    """Per flow: working (every repeat reached all goals), flaky (some did) or broken (none did)."""
    verdicts: dict[str, dict] = {}
    for result in results:
        flow = str(result.get("persona", "")).rsplit("-", 1)[0]
        entry = verdicts.setdefault(flow, {"runs": 0, "passed": 0, "unmet": [], "videos": []})
        entry["runs"] += 1
        entry["videos"].append(reporting.video_link(result) or "no video")
        if goals_met(result):
            entry["passed"] += 1
        else:
            entry["unmet"] += [o.get("why", "") for o in result.get("goal_outcomes") or [] if o.get("achieved") is not True]
            if not result.get("goal_outcomes"):
                entry["unmet"].append(f"no verdict ({result.get('status')})")
    for entry in verdicts.values():
        entry["verdict"] = ("working" if entry["passed"] == entry["runs"] else
                            "broken" if entry["passed"] == 0 else "flaky")
    return verdicts


def summary_text(name: str, target: str, run_date: str, verdicts: dict[str, dict], problems: list[str]) -> str:
    """One push: ✅ when every flow works and nothing else failed, else ❌ with each flow's verdict and the
    session videos of its runs."""
    clean = not problems and all(v["verdict"] == "working" for v in verdicts.values())
    flows = ", ".join(f"{flow.split('_', 1)[0]} {v['verdict']} ({' '.join(v.get('videos') or []) or 'no video'})"
                      for flow, v in sorted(verdicts.items()))
    text = f"{'✅' if clean else '❌'} AI test users {name} run on {target} {run_date}: {flows}."
    broken = [f"{flow}: {v['unmet'][0][:90]}" for flow, v in sorted(verdicts.items()) if v["unmet"]]
    if broken:
        text += " Unmet: " + "; ".join(broken[:3]) + "."
    return text
