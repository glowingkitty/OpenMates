#!/usr/bin/env python3
# git_stats.py — Structured git history analytics for OpenMates.
#
# Aggregates commit activity, code churn, and quality signals over a time window
# using conventional-commit prefixes (fix/feat/docs/...). Designed as a reusable
# replacement for ad-hoc git log pipelines when evaluating dev throughput and
# code-quality trends over weeks or months.
#
# Usage:
#   python3 scripts/git_stats.py                        # default: 6 months
#   python3 scripts/git_stats.py --since "12 weeks ago"
#   python3 scripts/git_stats.py --author glowingkitty --json
#   python3 scripts/git_stats.py --hotspots 25 --since "6 months ago"

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

CONVENTIONAL_TYPES = (
    "fix", "feat", "docs", "doc", "refactor", "test",
    "debug", "perf", "chore", "style", "ci", "build", "revert",
)

TYPE_NORMALISE = {"doc": "docs"}

REVERT_PATTERN = re.compile(r"^(revert[:\s]|rollback|undo)\b", re.IGNORECASE)


@dataclass
class WeekBucket:
    week: str
    commits: int = 0
    insertions: int = 0
    deletions: int = 0
    files_changed: int = 0
    types: Counter = field(default_factory=Counter)
    reverts: int = 0

    @property
    def net(self) -> int:
        return self.insertions - self.deletions

    @property
    def avg_lines_per_commit(self) -> float:
        return (self.insertions + self.deletions) / self.commits if self.commits else 0.0

    @property
    def avg_files_per_commit(self) -> float:
        return self.files_changed / self.commits if self.commits else 0.0

    def ratio(self, top: str, bottom: str) -> float:
        b = self.types.get(bottom, 0)
        return (self.types.get(top, 0) / b) if b else 0.0


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    )
    return result.stdout


def classify(subject: str) -> str | None:
    m = re.match(r"^([a-zA-Z]+)(\(|:|!)", subject)
    if not m:
        return None
    t = m.group(1).lower()
    t = TYPE_NORMALISE.get(t, t)
    return t if t in CONVENTIONAL_TYPES else "other"


def collect(since: str, author: str | None) -> tuple[dict[str, WeekBucket], Counter, list[str]]:
    """One pass through git log to populate per-week buckets + file churn."""
    fmt = "--pretty=format:COMMIT|%h|%ad|%s"
    # %G-W%V = ISO-year + ISO-week (avoids year-boundary mismatch that %Y-%V creates)
    cmd = ["log", "--no-merges", fmt, "--date=format:%G-W%V", "--numstat", f"--since={since}"]
    if author:
        cmd += [f"--author={author}"]

    raw = run_git(cmd)
    weeks: dict[str, WeekBucket] = {}
    churn: Counter = Counter()
    subjects: list[str] = []

    current_week: str | None = None

    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("COMMIT|"):
            _, _sha, week, subject = line.split("|", 3)
            current_week = week
            subjects.append(subject)

            bucket = weeks.setdefault(week, WeekBucket(week=week))
            bucket.commits += 1

            ctype = classify(subject)
            if ctype:
                bucket.types[ctype] += 1
            if REVERT_PATTERN.search(subject):
                bucket.reverts += 1
            continue

        # numstat line: "<ins>\t<del>\t<path>"
        parts = line.split("\t")
        if len(parts) != 3 or current_week is None:
            continue
        ins_s, del_s, path = parts
        if ins_s == "-" or del_s == "-":  # binary file
            continue
        try:
            ins, dels = int(ins_s), int(del_s)
        except ValueError:
            continue
        bucket = weeks[current_week]
        bucket.insertions += ins
        bucket.deletions += dels
        bucket.files_changed += 1
        churn[path] += 1

    return weeks, churn, subjects


def message_quality(subjects: list[str]) -> dict:
    if not subjects:
        return {"count": 0}
    lengths = [len(s) for s in subjects]
    short = sum(1 for n in lengths if n < 30)
    med = sum(1 for n in lengths if 30 <= n < 60)
    verbose = sum(1 for n in lengths if n >= 60)
    return {
        "count": len(subjects),
        "avg_subject_length": round(sum(lengths) / len(lengths), 1),
        "short_pct": round(short * 100 / len(subjects), 1),
        "medium_pct": round(med * 100 / len(subjects), 1),
        "long_pct": round(verbose * 100 / len(subjects), 1),
    }


def render_table(weeks: dict[str, WeekBucket]) -> str:
    sorted_weeks = sorted(weeks.values(), key=lambda b: b.week)
    header = (
        f"{'Week':<10} {'Commits':>8} {'Ins':>9} {'Del':>9} {'Net':>10} "
        f"{'Files/c':>8} {'Lines/c':>8} "
        f"{'Fix':>5} {'Feat':>5} {'Docs':>5} {'Test':>5} {'Refac':>6} "
        f"{'Fix/Feat':>9} {'Test/Feat':>10} {'Rev':>4}"
    )
    lines = [header, "-" * len(header)]
    tot = WeekBucket(week="TOTAL")
    tot.types = Counter()
    for b in sorted_weeks:
        lines.append(
            f"{b.week:<10} {b.commits:>8} {b.insertions:>9} {b.deletions:>9} "
            f"{b.net:>10} {b.avg_files_per_commit:>8.1f} {b.avg_lines_per_commit:>8.0f} "
            f"{b.types.get('fix', 0):>5} {b.types.get('feat', 0):>5} "
            f"{b.types.get('docs', 0):>5} {b.types.get('test', 0):>5} "
            f"{b.types.get('refactor', 0):>6} "
            f"{b.ratio('fix', 'feat'):>9.2f} {b.ratio('test', 'feat'):>10.2f} "
            f"{b.reverts:>4}"
        )
        tot.commits += b.commits
        tot.insertions += b.insertions
        tot.deletions += b.deletions
        tot.files_changed += b.files_changed
        tot.reverts += b.reverts
        tot.types.update(b.types)
    lines.append("-" * len(header))
    lines.append(
        f"{'TOTAL':<10} {tot.commits:>8} {tot.insertions:>9} {tot.deletions:>9} "
        f"{tot.net:>10} {tot.avg_files_per_commit:>8.1f} {tot.avg_lines_per_commit:>8.0f} "
        f"{tot.types.get('fix', 0):>5} {tot.types.get('feat', 0):>5} "
        f"{tot.types.get('docs', 0):>5} {tot.types.get('test', 0):>5} "
        f"{tot.types.get('refactor', 0):>6} "
        f"{tot.ratio('fix', 'feat'):>9.2f} {tot.ratio('test', 'feat'):>10.2f} "
        f"{tot.reverts:>4}"
    )
    return "\n".join(lines)


def render_hotspots(churn: Counter, top: int) -> str:
    lines = [f"\nTop {top} churn hotspots (files changed most often):", "-" * 60]
    for path, n in churn.most_common(top):
        lines.append(f"{n:>5}  {path}")
    return "\n".join(lines)


def render_type_totals(weeks: dict[str, WeekBucket]) -> str:
    agg: Counter = Counter()
    for b in weeks.values():
        agg.update(b.types)
    total = sum(agg.values())
    lines = ["\nCommit types (whole window):", "-" * 40]
    for t, n in agg.most_common():
        lines.append(f"  {t:<10} {n:>6}  ({n * 100 / total:>5.1f}%)")
    return "\n".join(lines)


def render_quality(q: dict) -> str:
    return (
        "\nCommit message quality:\n"
        + "-" * 40 + "\n"
        f"  Avg subject length: {q['avg_subject_length']} chars\n"
        f"  <30 chars (terse):  {q['short_pct']}%\n"
        f"  30-60 chars (good): {q['medium_pct']}%\n"
        f"  60+ chars (long):   {q['long_pct']}%"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="6 months ago",
                    help="git log --since value (default: '6 months ago')")
    ap.add_argument("--author", default=None,
                    help="Restrict to one author (substring match)")
    ap.add_argument("--hotspots", type=int, default=20,
                    help="Number of churn hotspot files to show (default: 20)")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON instead of tables")
    args = ap.parse_args()

    weeks, churn, subjects = collect(args.since, args.author)
    if not weeks:
        print("No commits found.", file=sys.stderr)
        return 1

    quality = message_quality(subjects)

    if args.json:
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "since": args.since,
            "author": args.author,
            "weeks": [
                {
                    "week": b.week,
                    "commits": b.commits,
                    "insertions": b.insertions,
                    "deletions": b.deletions,
                    "net": b.net,
                    "files_changed": b.files_changed,
                    "avg_lines_per_commit": round(b.avg_lines_per_commit, 1),
                    "avg_files_per_commit": round(b.avg_files_per_commit, 2),
                    "types": dict(b.types),
                    "fix_feat_ratio": round(b.ratio("fix", "feat"), 3),
                    "test_feat_ratio": round(b.ratio("test", "feat"), 3),
                    "reverts": b.reverts,
                }
                for b in sorted(weeks.values(), key=lambda x: x.week)
            ],
            "hotspots": churn.most_common(args.hotspots),
            "message_quality": quality,
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Git stats for window: {args.since}"
          + (f" | author={args.author}" if args.author else ""))
    print()
    print(render_table(weeks))
    print(render_type_totals(weeks))
    print(render_hotspots(churn, args.hotspots))
    print(render_quality(quality))
    return 0


if __name__ == "__main__":
    sys.exit(main())
