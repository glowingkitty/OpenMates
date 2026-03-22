#!/usr/bin/env python3
"""
Purpose: Compare Berlin concert listings across Bachtrack, Classictic, Elbphilharmonie.
Architecture: Standalone comparison helper for reverse-engineered source scripts.
Architecture Doc: docs/architecture/README.md
Tests: N/A (manual CLI verification script)

This script executes the three source scripts and computes overlap and field coverage.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent

SOURCE_SCRIPTS = {
    "bachtrack": SCRIPT_DIR / "test_bachtrack_api.py",
    "classictic": SCRIPT_DIR / "test_classictic_api.py",
    "berlin_philharmonic": SCRIPT_DIR / "test_berlin_philharmonic_api.py",
}


def normalize_title(title: str) -> str:
    lowered = title.lower().strip()
    alnum = re.sub(r"[^a-z0-9\s]", " ", lowered)
    squashed = re.sub(r"\s+", " ", alnum).strip()
    return squashed


def run_source_script(source: str, city_filter: str) -> dict[str, Any]:
    script_path = SOURCE_SCRIPTS[source]
    command = [sys.executable, str(script_path), "--json"]
    if source == "bachtrack":
        command.extend(["--city", city_filter, "--category", "all"])
    if source == "classictic":
        command.extend(["--category", "concerts"])

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{source} script failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def pair_overlap(a_events: list[dict[str, Any]], b_events: list[dict[str, Any]]) -> dict[str, Any]:
    a_titles: dict[str, dict[str, Any]] = {}
    b_titles: dict[str, dict[str, Any]] = {}
    for event in a_events:
        key = normalize_title(event.get("title", ""))
        if key:
            a_titles.setdefault(key, event)
    for event in b_events:
        key = normalize_title(event.get("title", ""))
        if key:
            b_titles.setdefault(key, event)

    overlap_keys = sorted(set(a_titles).intersection(b_titles))
    return {
        "count": len(overlap_keys),
        "sample_titles": [a_titles[key]["title"] for key in overlap_keys[:15]],
    }


def compute_field_coverage(events: list[dict[str, Any]]) -> dict[str, int]:
    fields = ["title", "date_time", "date_text", "venue", "city", "detail_url", "booking_url", "source_event_id"]
    coverage: dict[str, int] = {}
    for field in fields:
        coverage[field] = sum(1 for event in events if event.get(field))
    return coverage


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Berlin concert results across scraped sources")
    parser.add_argument("--city", default="berlin", help="City keyword/slug to pass through (default: berlin)")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()

    source_payloads = {
        source: run_source_script(source=source, city_filter=args.city)
        for source in SOURCE_SCRIPTS
    }

    source_events = {source: payload.get("events", []) for source, payload in source_payloads.items()}
    source_counts = {source: len(events) for source, events in source_events.items()}

    overlap = {
        "bachtrack_vs_classictic": pair_overlap(source_events["bachtrack"], source_events["classictic"]),
        "bachtrack_vs_berlin_philharmonic": pair_overlap(
            source_events["bachtrack"],
            source_events["berlin_philharmonic"],
        ),
        "classictic_vs_berlin_philharmonic": pair_overlap(
            source_events["classictic"],
            source_events["berlin_philharmonic"],
        ),
    }

    booking_availability = {
        source: {
            "with_booking_url": sum(1 for event in events if event.get("booking_url")),
            "total": len(events),
        }
        for source, events in source_events.items()
    }

    field_coverage = {
        source: compute_field_coverage(events)
        for source, events in source_events.items()
    }

    report = {
        "city": args.city,
        "results_per_platform": source_counts,
        "overlap": overlap,
        "booking_link_coverage": booking_availability,
        "field_coverage": field_coverage,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return

    print(f"City: {args.city}")
    print("Results per platform:")
    for source, count in source_counts.items():
        print(f"- {source}: {count}")

    print("\nOverlap (title-normalized exact match):")
    for pair, stats in overlap.items():
        print(f"- {pair}: {stats['count']}")
        if stats["sample_titles"]:
            print(f"  sample: {', '.join(stats['sample_titles'][:5])}")

    print("\nBooking link coverage:")
    for source, stats in booking_availability.items():
        print(f"- {source}: {stats['with_booking_url']}/{stats['total']} with booking URL")


if __name__ == "__main__":
    main()
