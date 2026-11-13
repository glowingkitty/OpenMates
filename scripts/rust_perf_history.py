#!/usr/bin/env python3
"""Validation and append helpers for docs/migration/rust/performance-history.yml.

The history is an append-only, hand/agent-curated list of web Rust-vs-TypeScript
measurements. Existing entries are never edited; new ones are appended with
scripts/record_perf_measurement.py. The approved gate lives in
.claude/rules/cli-sdk.md ("Web Rust performance gate").

Architecture: docs/migration/rust/overview.yml
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HISTORY = Path("docs/migration/rust/performance-history.yml")
SCHEMA_VERSION = 1

FLOWS = (
    "chatRendered", "embedReady", "uiInteractive", "send", "sendToAdmit",
    "search", "apps", "cpu", "rss", "reloadMemory", "wasmInstances",
    # Cross-SDK API-key operations (tests/sdk-conformance/benchmark_sdk_speed.py).
    "sdkWall", "sdkCpu",
)
VALUE_KINDS = ("ratio", "delta_ms", "delta_mib", "delta_mib_per_reload", "count")
VERDICTS = ("rust_not_worse", "rust_worse", "inconclusive", "unverified", "invalid_measurement")
VERDICT_BASES = ("reported", "derived", "none")
CONFIDENCE = ("traced", "uncertain")
# Upper CI bound (ratio) at or below which a ratio is within the gate without
# needing absolute milliseconds: wall max(+10%, +50 ms), CPU +15%.
RATIO_LIMIT = {"cpu": 1.15, "sdkCpu": 1.15}
DEFAULT_RATIO_LIMIT = 1.10
REQUIRED = (
    "id", "date", "flow", "metric", "value_kind", "value", "ci95", "n_pairs",
    "verdict", "verdict_basis", "ci_job", "source_commit", "evidence", "confidence", "notes",
)
OPTIONAL = ("ts_value", "range")
HEX_JOB = re.compile(r"^[0-9a-f]{8,64}$")
HEX_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([A-Za-z]+)-(\d{2})$")


def load(path: Path | None = None) -> dict:
    return yaml.safe_load(((path or ROOT / HISTORY)).read_text(encoding="utf-8"))


def derive_verdict(flow: str, value_kind: str, ci95: list | None) -> str:
    """Conservative verdict from a ratio CI alone: never claims rust_worse."""
    if value_kind != "ratio" or not ci95:
        return "unverified"
    limit = RATIO_LIMIT.get(flow, DEFAULT_RATIO_LIMIT)
    return "rust_not_worse" if ci95[1] <= limit else "inconclusive"


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_entry(entry: dict) -> list[str]:
    where = f"entry {entry.get('id', '?')}"
    errors = [f"{where}: missing field {k}" for k in REQUIRED if k not in entry]
    errors += [f"{where}: unknown field {k}" for k in entry if k not in REQUIRED + OPTIONAL]
    if errors:
        return errors
    match = ID_RE.match(str(entry["id"]))
    if not match or match.group(1) != str(entry["date"]) or match.group(2) != entry["flow"]:
        errors.append(f"{where}: id must be <date>-<flow>-<NN>")
    try:
        date.fromisoformat(str(entry["date"]))
    except ValueError:
        errors.append(f"{where}: date must be ISO YYYY-MM-DD")
    if entry["flow"] not in FLOWS:
        errors.append(f"{where}: flow must be one of {FLOWS}")
    if entry["value_kind"] not in VALUE_KINDS:
        errors.append(f"{where}: value_kind must be one of {VALUE_KINDS}")
    if entry["value"] is not None and not _number(entry["value"]):
        errors.append(f"{where}: value must be a number or null")
    if "ts_value" in entry and entry["ts_value"] is not None and not _number(entry["ts_value"]):
        errors.append(f"{where}: ts_value must be a number or null")
    for key in ("ci95", "range"):
        pair = entry.get(key)
        if pair is not None and not (isinstance(pair, list) and len(pair) == 2 and all(_number(x) for x in pair) and pair[0] <= pair[1]):
            errors.append(f"{where}: {key} must be null or [low, high]")
    if entry["ci95"] is not None and entry["value"] is not None and not entry["ci95"][0] <= entry["value"] <= entry["ci95"][1]:
        # The point estimate may be the median of pairs rather than the CI centre,
        # but it must stay inside the interval.
        errors.append(f"{where}: value lies outside ci95")
    if entry["n_pairs"] is not None and not (isinstance(entry["n_pairs"], int) and entry["n_pairs"] > 0):
        errors.append(f"{where}: n_pairs must be a positive integer or null")
    if entry["verdict"] not in VERDICTS:
        errors.append(f"{where}: verdict must be one of {VERDICTS}")
    if entry["verdict_basis"] not in VERDICT_BASES:
        errors.append(f"{where}: verdict_basis must be one of {VERDICT_BASES}")
    elif entry["verdict_basis"] == "derived" and entry["verdict"] != derive_verdict(entry["flow"], entry["value_kind"], entry["ci95"]):
        errors.append(f"{where}: derived verdict does not match the gate rule (expected {derive_verdict(entry['flow'], entry['value_kind'], entry['ci95'])})")
    if entry["verdict_basis"] == "none" and entry["verdict"] not in ("unverified", "invalid_measurement"):
        errors.append(f"{where}: verdict_basis none only allows unverified or invalid_measurement")
    for key, pattern in (("ci_job", HEX_JOB), ("source_commit", HEX_COMMIT)):
        if entry[key] is not None and not pattern.match(str(entry[key])):
            errors.append(f"{where}: {key} must be a lowercase hex id or null")
    if entry["confidence"] not in CONFIDENCE:
        errors.append(f"{where}: confidence must be one of {CONFIDENCE}")
    if entry["confidence"] == "traced" and not (entry["ci_job"] or entry["source_commit"]):
        errors.append(f"{where}: a traced entry needs ci_job or source_commit")
    for key in ("metric", "evidence", "notes"):
        if not isinstance(entry[key], str) or not entry[key].strip():
            errors.append(f"{where}: {key} must be a non-empty string")
    return errors


def validate(data: dict) -> list[str]:
    errors = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("gate", "measurements"):
        if key not in data:
            errors.append(f"missing top-level key {key}")
    entries = data.get("measurements") or []
    seen: set[str] = set()
    previous = ""
    for entry in entries:
        errors += validate_entry(entry)
        if entry.get("id") in seen:
            errors.append(f"duplicate id {entry.get('id')}")
        seen.add(entry.get("id"))
        if str(entry.get("date", "")) < previous:
            errors.append(f"entry {entry.get('id')}: dates must be non-decreasing (append-only, oldest first)")
        previous = max(previous, str(entry.get("date", "")))
    return errors


def is_append_only(old: dict, new: dict) -> bool:
    """True when `new` keeps every entry of `old` unchanged and in order."""
    before, after = old.get("measurements") or [], new.get("measurements") or []
    return len(after) >= len(before) and after[: len(before)] == before


def latest_by_flow(data: dict) -> dict[str, dict]:
    """Last gate-relevant entry per flow (invalid and unverified entries are skipped)."""
    latest: dict[str, dict] = {}
    for entry in data["measurements"]:
        if entry["verdict"] in ("invalid_measurement", "unverified"):
            continue
        latest[entry["flow"]] = entry
    return latest


def next_id(data: dict, day: str, flow: str) -> str:
    count = sum(1 for e in data["measurements"] if e["date"] == day and e["flow"] == flow)
    return f"{day}-{flow}-{count + 1:02d}"


class _EntryDumper(yaml.SafeDumper):
    """Block mappings, but short numeric lists such as ci95 on one line."""


_EntryDumper.add_representer(list, lambda dumper, data: dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=all(not isinstance(x, (dict, list)) for x in data)))


def dump_entry(entry: dict) -> str:
    text = yaml.dump([entry], Dumper=_EntryDumper, sort_keys=False, width=100, allow_unicode=True)
    return "".join(f"  {line}\n" if line else "\n" for line in text.splitlines())
