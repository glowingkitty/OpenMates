"""Pure wellbeing level math: a rolling per-chat history plus the current turn.

The level is computed per request and never stored. The history is the
client-held list of the last few turns; the thresholds are tuned by a benchmark.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.apps.ai.processing.wellbeing_questions import WELLBEING_SIGNALS

MAX_HISTORY = 8
HALF_LIFE_TURNS = 3.0
# Level thresholds on the combined (smoothed history and current maximum) score.
T1 = 0.35  # elevated: gentle check-in
T2 = 0.5   # high: support first, helpline card
T3 = 0.2   # acute: plan and intent signals both at or above this, or danger from others, this turn
DRIFT_GAIN = 1.5
DANGER_ACUTE = 0.7  # danger from others at or above this is acute on its own
PLAN_ALONE = 0.4  # a clear plan or means signal is acute even when intent was not scored high
INJURY_ACUTE = 0.8  # a fresh self-injury or medical danger this turn ...
INJURY_SELF_HARM = 0.5  # ... together with self-harm at or above this is acute
QUIET_TURNS = 6  # consecutive calm turns that clear the history
MIN_RECORDED = 0.2  # entries with no signal at or above this are dropped from the history
CORE_SIGNALS = ("suicidal", "self_harm", "plan_or_timeline", "method_or_means", "hopelessness_isolation")
# Hopelessness, isolation and grief alone never lift past level 1; level 2 needs one of these.
ACTIVE_RISK_SIGNALS = (
    "suicidal", "method_or_means", "plan_or_timeline", "self_harm", "self_injury_now",
    "eating_disorder", "reality_loss", "mania", "danger_from_others",
)
SUPPORT_SIGNALS = ("eating_disorder", "reality_loss", "mania", "danger_from_others")


@dataclass(frozen=True)
class WellbeingAssessment:
    level: int
    acute: bool
    dominant_signal: str | None
    updated_history: list[dict[str, Any]] = field(default_factory=list)


def sanitize_scores(raw: Any) -> dict[str, float] | None:
    """Return known signals as floats in 0..1, or None when the mapping is malformed."""
    if not isinstance(raw, Mapping):
        return None
    scores: dict[str, float] = {}
    for key, value in raw.items():
        if key not in WELLBEING_SIGNALS or type(value) not in {int, float}:
            return None
        if not math.isfinite(value) or not 0 <= value <= 1:
            return None
        scores[key] = round(float(value), 2)
    return scores


def sanitize_history(raw: Any) -> list[dict[str, Any]] | None:
    """Validate a client history; None means malformed (the caller logs and uses an empty one)."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_HISTORY:
        return None
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping) or type(item.get("t")) is not int or item["t"] < 0:
            return None
        scores = sanitize_scores(item.get("s"))
        if scores is None:
            return None
        entries.append({"t": item["t"], "s": scores})
    return entries


def _smoothed(history: list[dict[str, Any]]) -> dict[str, float]:
    decay = 0.5 ** (1.0 / HALF_LIFE_TURNS)
    smoothed: dict[str, float] = {}
    for entry in history:  # oldest first, so the newest dominates
        for signal in WELLBEING_SIGNALS:
            smoothed[signal] = smoothed.get(signal, 0.0) * decay + entry["s"].get(signal, 0.0) * (1 - decay)
    return smoothed


def compute_level(
    history: list[dict[str, Any]], current: Mapping[str, float], now: int | None = None,
) -> WellbeingAssessment:
    """Combine the validated history and this turn's scores into a level 0..3."""
    now = int(time.time()) if now is None else now
    scores = {signal: float(current.get(signal, 0.0)) for signal in WELLBEING_SIGNALS}
    smoothed = _smoothed(history)
    # Persistent signals count for more than one turn: the smoothed history is
    # weighted by DRIFT_GAIN so steady mid-level scores climb into the next band.
    combined = {signal: min(1.0, max(scores[signal], smoothed.get(signal, 0.0) * DRIFT_GAIN))
                for signal in WELLBEING_SIGNALS}
    acute = (
        scores["plan_or_timeline"] >= T3 and max(scores["suicidal"], scores["self_harm"]) >= T3
    ) or max(scores["plan_or_timeline"], scores["method_or_means"]) >= PLAN_ALONE or (
        scores["danger_from_others"] >= DANGER_ACUTE
    ) or (
        scores["self_injury_now"] >= INJURY_ACUTE and scores["self_harm"] >= INJURY_SELF_HARM
    )
    peak = max(combined.values())
    dominant = max(combined, key=combined.get) if peak >= T1 else None
    if acute:
        level = 3
    elif max(combined[signal] for signal in ACTIVE_RISK_SIGNALS) >= T2:
        level = 2
    elif peak >= T1:
        level = 1
    else:
        level = 0
    recorded = [*history, {"t": now, "s": {s: round(v, 2) for s, v in scores.items() if v >= 0.05}}]
    recorded = recorded[-MAX_HISTORY:]
    # A calm stretch clears the history so it does not linger on the chat.
    recent = recorded[-QUIET_TURNS:]
    if len(recent) == QUIET_TURNS and all(max(e["s"].values(), default=0.0) < MIN_RECORDED for e in recent):
        recorded = []
    elif not history and max(scores.values()) < MIN_RECORDED:
        recorded = []
    return WellbeingAssessment(level=level, acute=acute, dominant_signal=dominant, updated_history=recorded)
