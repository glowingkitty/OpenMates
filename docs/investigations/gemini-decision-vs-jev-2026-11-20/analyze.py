"""Per-purpose table from benchmark rows (rows.jsonl or .jsonl.gz).

Usage: python3 analyze.py ROWS [ROWS ...]
A later file replaces the suites it contains, so a clean rerun of a rate-limited suite overrides the earlier rows.
"""

import collections
import gzip
import json
import math
import sys

PURPOSE = {
    "preprocess_routing": "routing (preprocess)",
    "app_focus_routing": "routing (app/focus)",
    "voice_turn": "voice end-of-turn",
    "browse_control": "web browsing",
    "prompt_injection": "safety (prompt injection)",
    "postprocess_judge": "postprocessing",
}
RELEVANCE = {"rel-search": "search relevance", "rel-shop": "shopping relevance", "rel-photo": "photo relevance"}


def purpose(row: dict) -> str:
    if row["suite"] == "relevance_judges":
        return next(name for prefix, name in RELEVANCE.items() if row["case"].startswith(prefix))
    return PURPOSE.get(row["suite"], row["suite"])


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * q) - 1)]


def read_rows(path: str) -> list[dict]:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load(paths: list[str]) -> list[dict]:
    by_suite: dict[str, list[dict]] = {}
    for path in paths:
        rows = read_rows(path)
        for suite in {row["suite"] for row in rows}:
            by_suite[suite] = [row for row in rows if row["suite"] == suite]
    return [row for suite_rows in by_suite.values() for row in suite_rows]


def main(paths: list[str]) -> None:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for row in load(paths):
        groups[purpose(row)].append(row)
    print("| purpose | model | calls | valid | 429 | blocked | p50 ms | p95 ms | question accuracy (valid) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for name, rows in sorted(groups.items()):
        for engine in ("jev", "gemini"):
            engine_rows = [row for row in rows if row["engine"] == engine]
            valid = [row for row in engine_rows if row["ok"]]
            answers = [q["correct"] for row in valid for q in row["questions"].values()]
            latencies = [row["ms"] for row in valid]
            limited = sum(row.get("error") == "rate_limited" for row in engine_rows)
            blocked = sum(bool(row.get("blocked")) for row in engine_rows)
            accuracy = sum(answers) / len(answers) if answers else float("nan")
            print(f"| {name} | {engine} | {len(engine_rows)} | {len(valid)} | {limited} | {blocked} | "
                  f"{percentile(latencies, 0.5):.0f} | {percentile(latencies, 0.95):.0f} | {accuracy:.3f} |")


if __name__ == "__main__":
    main(sys.argv[1:])
