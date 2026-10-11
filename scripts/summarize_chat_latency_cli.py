#!/usr/bin/env python3
"""Summarize retained real terminal chat captures without exporting chat text.

Reads the real PTY transcript and timing sidecars from cli_video_capture.py.
Excludes the helper's filmed command-typing interval from CLI latency.
Reports typing, first answer text, and terminal completion timing.
Keeps generated answer content and account details out of summary output.
The small live sample is descriptive, not a population percentile estimate.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import statistics

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
DIVIDER = "─" * 10


def measure(folder: Path) -> dict:
    raw = (folder / "transcript.txt").read_bytes()
    body = raw[raw.find(b"\n") + 1 :]
    timeline = []
    offset = 0
    elapsed = 0.0
    for line in (folder / "events.jsonl").read_text().splitlines():
        delta, length = line.split()
        length = int(length)
        elapsed += float(delta)
        chunk = body[offset : offset + length].decode("utf-8", errors="replace")
        offset += length
        timeline.append((elapsed, ANSI.sub("", chunk)))
    command_end = typing = first_text = answer_done = process_done = None
    header_seen = False
    prefix = ""
    mate = None
    model = None
    for instant, chunk in timeline:
        if command_end is None:
            prefix += chunk
            if "\r\n" in prefix or "\n" in prefix:
                command_end = instant
            continue
        if typing is None and "is typing" in chunk:
            typing = instant
            match = re.search(r"([A-Za-z]+) is typing", chunk)
            mate = match.group(1) if match else None
        if "Gemini 3.8 Flash" in chunk:
            header_seen = True
            model = "Gemini 3.8 Flash"
            continue
        if header_seen and first_text is None:
            stripped = chunk.strip()
            if (
                stripped
                and DIVIDER not in stripped
                and not stripped.startswith("Science")
                and not stripped.startswith("Business")
                and not stripped.startswith("Technology")
                and re.search(r"[A-Za-z]{3}", stripped)
            ):
                first_text = instant
        elif first_text is not None and answer_done is None and DIVIDER in chunk:
            answer_done = instant
        if "Continue:" in chunk:
            process_done = instant
    if command_end is None or first_text is None:
        raise ValueError(f"missing command/answer markers: {folder.name}")
    if answer_done is None:
        answer_done = process_done
    if process_done is None:
        process_done = timeline[-1][0]
    return {
        "case": folder.name.split("cli-", 1)[-1],
        "status": "passed",
        "mate": mate,
        "model": model,
        "cli_start_to_typing_ms": round((typing - command_end) * 1000)
        if typing
        else None,
        "cli_start_to_first_text_ms": round((first_text - command_end) * 1000),
        "cli_start_to_answer_done_ms": round((answer_done - command_end) * 1000)
        if answer_done
        else None,
        "cli_start_to_command_done_ms": round((process_done - command_end) * 1000),
        "capture_video_sha256": json.loads((folder / "manifest.json").read_text()).get(
            "video_sha256"
        ),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("capture_root", type=Path)
    p.add_argument("phase", choices=("before", "after"))
    p.add_argument("--cohort", default="empty")
    args = p.parse_args()
    prefix = (
        f"{args.phase}-cli-"
        if args.cohort == "empty"
        else f"{args.phase}-{args.cohort}-cli-"
    )
    runs = [
        measure(x)
        for x in sorted(args.capture_root.glob(prefix + "*"))
        if (x / "manifest.json").exists()
    ]
    grouped = {}
    for label in ("simple", "complex"):
        group = [r for r in runs if r["case"].startswith(label)]
        grouped[label] = {
            "n": len(group),
            "median_first_text_ms": round(
                statistics.median(r["cli_start_to_first_text_ms"] for r in group)
            )
            if group
            else None,
        }
    print(
        json.dumps(
            {
                "phase": args.phase,
                "client": "cli",
                "cohort": args.cohort,
                "clock": "PTY command accepted after 30 ms/character filmed command typing",
                "runs": runs,
                "groups": grouped,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
