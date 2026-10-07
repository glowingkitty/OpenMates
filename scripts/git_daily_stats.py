#!/usr/bin/env python3
"""Daily committed line changes, using Git and Python's standard library.

Examples:
    python3 scripts/git_daily_stats.py --days 14
    python3 scripts/git_daily_stats.py --ref dev --end-date 2026-10-07 --json
    python3 scripts/git_daily_stats.py --scope all --timezone UTC

The window includes the end date (today by default) and zero-activity days.
Days use committer timestamps in the selected timezone. First-parent history
counts merged changes once, against the merge's first parent. Churn is additions
plus deletions, so changing one line usually contributes two lines of churn;
this measures activity, not unique lines changed or developer productivity.

Code scope includes source, templates, tests and scripts with CODE_EXTENSIONS.
All scope includes every tracked text file, including docs, config and lockfiles.
Binary changes are reported separately. Uncommitted changes are excluded.
Pin --ref to a commit and --end-date for byte-identical repeatable JSON output.
Requires Git with --since-as-filter support and Python >= 3.9 (zoneinfo).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


CODE_EXTENSIONS = frozenset(
    ".py .pyi .ts .tsx .js .jsx .mjs .cjs .svelte .vue "
    ".css .scss .sass .less .html .htm .mjml .swift .m .mm .h .c .cc .cpp "
    ".cxx .hpp .rs .go .java .kt .kts .sh .bash .zsh .fish .ps1 .rb .php "
    ".sql .lua .dart .ex .exs .erl .hrl .clj .cljs .cs .fs .r .jl .pl .pm "
    ".proto .graphql .gql .tf".split()
)


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=True
    )
    return result.stdout


def empty_counts() -> dict[str, int]:
    return {
        "commits": 0, "added": 0, "deleted": 0, "churn": 0, "net": 0,
        "binary_file_changes": 0,
    }


def collect_daily(
    repo: Path, ref: str, days: int, end_date: date, timezone: ZoneInfo, scope: str,
) -> dict:
    if git(repo, "rev-parse", "--is-shallow-repository").strip() == b"true":
        raise ValueError("Complete Git history is required; this repository is shallow.")
    revision = git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
    ).decode().strip()
    start_date = end_date - timedelta(days=days - 1)
    start = int(datetime.combine(start_date, time.min, timezone).timestamp())
    stop = int(datetime.combine(end_date + timedelta(days=1), time.min, timezone).timestamp())
    buckets = {
        (start_date + timedelta(days=offset)).isoformat(): empty_counts()
        for offset in range(days)
    }
    paths = (
        [f":(top,icase,glob)**/*{suffix}" for suffix in sorted(CODE_EXTENSIONS)]
        if scope == "code" else []
    )

    # One history scan. NUL delimiters preserve tabs/newlines in filenames;
    # explicit diff options avoid external tools, textconv and local diff defaults.
    # Sparse/full history retains commits without scoped changes while pathspecs
    # avoid computing huge generated/config diffs for the source-code report.
    raw = git(
        repo, "log", "--first-parent", "--diff-merges=first-parent", "--root",
        "--full-history", "--sparse",
        "--format=%x00COMMIT:%ct", "--numstat", "-z", "--no-color",
        "--no-ext-diff", "--no-textconv", "--find-renames=50%", "-l0",
        "--diff-algorithm=myers", "--no-indent-heuristic", "--ignore-submodules=none",
        f"--since-as-filter=@{start}", f"--until=@{stop}", revision, "--", *paths,
    )
    current = None
    tokens = iter(raw.split(b"\0"))
    for token in tokens:
        token = token.lstrip(b"\n")
        if not token:
            continue
        if token.startswith(b"COMMIT:"):
            stamp = int(token[7:])
            # Git's --until is inclusive; our next-midnight boundary is exclusive.
            current = (
                buckets[datetime.fromtimestamp(stamp, timezone).date().isoformat()]
                if start <= stamp < stop else None
            )
            if current is not None:
                current["commits"] += 1
            continue

        added, deleted, path = token.split(b"\t", 2)
        if not path:  # Renames have separate old/new NUL-delimited paths.
            old_path, path = next(tokens), next(tokens)
        else:
            old_path = path
        if current is None:
            continue
        include_added = (
            scope == "all" or PurePosixPath(os.fsdecode(path)).suffix.lower() in CODE_EXTENSIONS
        )
        include_deleted = (
            scope == "all" or PurePosixPath(os.fsdecode(old_path)).suffix.lower() in CODE_EXTENSIONS
        )
        if not (include_added or include_deleted):
            continue
        if added == b"-" or deleted == b"-":
            current["binary_file_changes"] += 1
            continue
        current["added"] += int(added) if include_added else 0
        current["deleted"] += int(deleted) if include_deleted else 0

    totals = empty_counts()
    for bucket in buckets.values():
        bucket["churn"] = bucket["added"] + bucket["deleted"]
        bucket["net"] = bucket["added"] - bucket["deleted"]
        for key in totals:
            totals[key] += bucket[key]
    return {
        "revision": revision,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timezone": timezone.key,
        "date_basis": "committer",
        "history": "first-parent (merges compared with their first parent)",
        "scope": scope,
        "code_extensions": sorted(CODE_EXTENSIONS) if scope == "code" else [],
        "commit_count_basis": "all first-parent commits, including commits without scoped changes",
        "days": [{"date": day, **bucket} for day, bucket in buckets.items()],
        "totals": totals,
    }


def render_table(report: dict) -> str:
    lines = [
        f"Daily {report['scope']} line changes: {report['start_date']} to {report['end_date']} ({report['timezone']})",
        f"Revision: {report['revision']}",
        "Committer dates; first-parent history; churn = added + deleted; net = added - deleted.",
        "Commits includes commits without changes in the selected scope.",
        f"{'Date':<10} {'Commits':>7} {'Added':>10} {'Deleted':>10} {'Churn':>10} {'Net':>11}",
    ]
    for row in [*report["days"], {"date": "TOTAL", **report["totals"]}]:
        lines.append(
            f"{row['date']:<10} {row['commits']:>7,} {row['added']:>10,} "
            f"{row['deleted']:>10,} {row['churn']:>10,} {row['net']:>+11,}"
        )
    lines.append(f"Binary file changes excluded from line totals: {report['totals']['binary_file_changes']}")
    return "\n".join(lines)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1], help="Repository path (default: this script's repository)")
    parser.add_argument("--ref", default="HEAD", help="Branch or commit (default: HEAD); use a commit hash to pin the snapshot")
    parser.add_argument("--days", type=positive_int, default=14, help="Calendar days, including the end date (default: 14)")
    parser.add_argument("--end-date", type=date.fromisoformat, help="Inclusive YYYY-MM-DD end date (default: today in the selected timezone)")
    parser.add_argument("--timezone", default="Europe/Berlin", help="IANA timezone (default: Europe/Berlin)")
    parser.add_argument("--scope", choices=("code", "all"), default="code", help="Source code or all tracked text files (default: code)")
    parser.add_argument("--json", action="store_true", help="Emit deterministic machine-readable JSON")
    args = parser.parse_args()
    try:
        timezone = ZoneInfo(args.timezone)
        report = collect_daily(
            args.repo, args.ref, args.days,
            args.end_date or datetime.now(timezone).date(), timezone, args.scope,
        )
    except subprocess.CalledProcessError as exc:
        parser.error(exc.stderr.decode(errors="replace").strip())
    except (OSError, ValueError, OverflowError, ZoneInfoNotFoundError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2) if args.json else render_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
