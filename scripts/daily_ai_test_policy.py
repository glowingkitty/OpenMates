#!/usr/bin/env python3
"""
Canonical daily AI test policy loader.

Keeps expensive manual specs out of automatic discovery and selects the small
reviewed real-inference canary set without coupling ordinary E2E discovery to
AI-specific filenames. Architecture: contracts/architecture/daily-ai-test-inference/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from scripts import daily_ai_cache_backfill


MANIFEST_PATH = Path(__file__).with_name("daily_ai_test_manifest.json")
DEFAULT_SPEC_DIR = Path(__file__).resolve().parents[1] / "frontend" / "apps" / "web_app" / "tests"
MANUAL_EXPENSIVE = "manual_expensive"
BACKFILL_PENDING = "backfill_pending"
REPLAY = "replay"
_AI_ACTION_MARKERS = ("sendMessage(", "'chats', 'new'", "custom-send-message")
_REPLAY_MARKERS = ("withMockMarker", "withLiveMockMarker", "testMockMarker")


@dataclass(frozen=True)
class DailyAISpecPlan:
    """The daily AI additions selected from the reviewed manifest."""

    fixed: tuple[str, ...]
    rotating: tuple[str, ...]

    @property
    def selected(self) -> tuple[str, ...]:
        return self.fixed + self.rotating


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    """Load and validate the small JSON policy manifest."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid daily AI test manifest: {exc}") from exc
    if manifest.get("schema_version") not in {1, 2}:
        raise RuntimeError("Daily AI test manifest must use schema_version 1 or 2")
    if not isinstance(manifest.get("specs"), dict):
        raise RuntimeError("Daily AI test manifest specs must be an object")
    canaries = manifest.get("daily_canaries")
    if not isinstance(canaries, dict) or not all(isinstance(canaries.get(key), list) for key in ("fixed", "rotating")):
        raise RuntimeError("Daily AI test manifest daily_canaries must define fixed and rotating lists")
    # Schema 1 used string classifications. Normalize it in memory so callers
    # can safely consume structured classifications during the transition.
    if manifest["schema_version"] == 1:
        manifest = {
            **manifest,
            "schema_version": 2,
            "specs": {
                spec: {"classification": classification}
                for spec, classification in manifest["specs"].items()
            },
        }
    for spec, entry in manifest["specs"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("classification"), str):
            raise RuntimeError(f"Daily AI spec {spec} requires a structured classification")
        if entry["classification"] == BACKFILL_PENDING and not isinstance(entry.get("cache_group"), str):
            raise RuntimeError(f"Backfill-pending spec {spec} requires cache_group")
    return manifest


def excluded_specs(manifest: dict | None = None) -> frozenset[str]:
    """Return manually invoked specs excluded from ordinary automatic discovery."""
    manifest = manifest or load_manifest()
    canaries = manifest["daily_canaries"]
    manual_specs = [
        spec
        for spec, entry in manifest["specs"].items()
        if entry["classification"] != REPLAY
    ]
    return frozenset([*manual_specs, *canaries["fixed"], *canaries["rotating"]])


def discover_specs(
    spec_names: Iterable[str],
    manifest: dict | None = None,
    spec_dir: Path = DEFAULT_SPEC_DIR,
) -> list[str]:
    """Keep non-AI and explicit replay specs; reject unmarked AI from schedules."""
    excluded = excluded_specs(manifest)
    discovered: list[str] = []
    for spec_name in spec_names:
        if spec_name in excluded:
            continue
        source_path = spec_dir / spec_name
        try:
            source = source_path.read_text(encoding="utf-8")
        except OSError:
            source = ""
        drives_ai = any(marker in source for marker in _AI_ACTION_MARKERS)
        has_replay = any(marker in source for marker in _REPLAY_MARKERS)
        if drives_ai and not has_replay:
            raise RuntimeError(
                f"Unclassified AI spec cannot enter scheduled discovery: {spec_name}"
            )
        discovered.append(spec_name)
    return sorted(discovered)


def daily_plan(
    available_specs: Iterable[str],
    utc_date: date,
    *,
    scheduled: bool,
    record_mode: bool,
    manifest: dict | None = None,
) -> DailyAISpecPlan:
    """Select one fixed and one UTC-date-rotated canary when reviewed entries exist."""
    if scheduled and record_mode:
        raise ValueError("Scheduled daily AI runs cannot use record mode")

    manifest = manifest or load_manifest()
    available = set(available_specs)
    canaries = manifest["daily_canaries"]
    if len(canaries["fixed"]) != 1:
        raise ValueError("Daily AI policy requires exactly one fixed canary")
    if not canaries["rotating"]:
        raise ValueError("Daily AI policy requires at least one rotating canary")
    missing = [
        spec
        for spec in [*canaries["fixed"], *canaries["rotating"]]
        if spec not in available
    ]
    if missing:
        raise ValueError(f"Daily AI canary specs are missing: {', '.join(sorted(missing))}")
    fixed = (canaries["fixed"][0],)
    rotating_candidates = sorted(spec for spec in canaries["rotating"] if spec in available)
    rotating = (
        (rotating_candidates[utc_date.toordinal() % len(rotating_candidates)],)
        if rotating_candidates
        else ()
    )
    return DailyAISpecPlan(fixed=fixed, rotating=rotating)


def daily_backfill_plan(utc_date: date, manifest: dict | None = None) -> daily_ai_cache_backfill.BackfillPlan | None:
    """Select exactly one deterministic pending cache backfill for a daily run."""
    manifest = manifest or load_manifest()
    entries = [
        {"spec": spec, **entry}
        for spec, entry in manifest["specs"].items()
        if entry["classification"] == BACKFILL_PENDING
    ]
    return daily_ai_cache_backfill.select_backfill_plan(entries, utc_date.isoformat())
