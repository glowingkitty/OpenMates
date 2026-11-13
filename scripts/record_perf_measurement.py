#!/usr/bin/env python3
"""Append one validated measurement to docs/migration/rust/performance-history.yml.

Examples:
  python3 scripts/record_perf_measurement.py --flow search --metric searchRenderedMs \
      --value-kind ratio --value 1.01 --ci 0.897 1.149 --n-pairs 12 \
      --from-ci-run 44cf35f1 --evidence "web-rust-core-bench search 12 pairs" --notes "..."
  python3 scripts/record_perf_measurement.py --from-json measurement.json

`--from-json` takes an object (or list of objects) with the entry field names;
`--from-ci-run <prefix>` fills ci_job and source_commit from the receipt under
test-results/ci-runs/. Without --verdict the verdict is derived from the ratio CI
by the gate rule (never rust_worse); pass --verdict for a reported one.
Existing entries are never changed; the file is validated before and after.

Architecture: docs/migration/rust/overview.yml
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rust_perf_history as history  # noqa: E402

RUNS = Path("test-results/ci-runs")


def receipt_fields(prefix: str) -> dict:
    matches = sorted((history.ROOT / RUNS).glob(f"{prefix}*/receipt.json"))
    if len(matches) != 1:
        raise SystemExit(f"--from-ci-run {prefix}: expected exactly one run, found {len(matches)}")
    receipt = json.loads(matches[0].read_text(encoding="utf-8"))
    return {"ci_job": receipt["id"][:8], "source_commit": receipt["source_commit"][:12]}


def build_entry(base: dict, args: argparse.Namespace, data: dict) -> dict:
    entry = dict(base)
    cli = {
        "flow": args.flow, "metric": args.metric, "value_kind": args.value_kind, "value": args.value,
        "n_pairs": args.n_pairs, "ci_job": args.ci_job, "source_commit": args.source_commit,
        "evidence": args.evidence, "notes": args.notes, "date": args.date, "verdict": args.verdict,
        "ts_value": args.ts_value,
    }
    entry.update({k: v for k, v in cli.items() if v is not None})
    if args.ci:
        entry["ci95"] = list(args.ci)
    if args.range:
        entry["range"] = list(args.range)
    if args.from_ci_run:
        entry.update({k: v for k, v in receipt_fields(args.from_ci_run).items() if entry.get(k) is None})
    entry.setdefault("date", date.today().isoformat())
    entry.setdefault("value", None)
    entry.setdefault("ci95", None)
    entry.setdefault("n_pairs", None)
    entry.setdefault("ci_job", None)
    entry.setdefault("source_commit", None)
    entry.setdefault("confidence", "traced")
    entry.setdefault("evidence", "CI result" if entry.get("ci_job") else "manual")
    if "verdict" not in entry:
        entry["verdict"] = history.derive_verdict(entry.get("flow", ""), entry.get("value_kind", ""), entry["ci95"])
        entry["verdict_basis"] = "derived" if entry["verdict"] != "unverified" else "none"
    else:
        entry.setdefault("verdict_basis", "reported")
    entry["id"] = history.next_id(data, str(entry["date"]), str(entry.get("flow")))
    ordered = {k: entry[k] for k in history.REQUIRED if k in entry}
    ordered.update({k: entry[k] for k in history.OPTIONAL if k in entry})
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-json", type=Path, help="JSON object or list of entry fields")
    parser.add_argument("--from-ci-run", help="CI run id prefix; fills ci_job and source_commit")
    parser.add_argument("--flow", choices=history.FLOWS)
    parser.add_argument("--metric")
    parser.add_argument("--value-kind", choices=history.VALUE_KINDS)
    parser.add_argument("--value", type=float)
    parser.add_argument("--ts-value", type=float)
    parser.add_argument("--ci", nargs=2, type=float, metavar=("LOW", "HIGH"))
    parser.add_argument("--range", nargs=2, type=float, metavar=("LOW", "HIGH"))
    parser.add_argument("--n-pairs", type=int)
    parser.add_argument("--verdict", choices=history.VERDICTS)
    parser.add_argument("--ci-job")
    parser.add_argument("--source-commit")
    parser.add_argument("--evidence")
    parser.add_argument("--date", help="ISO date; default today")
    parser.add_argument("--notes")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = history.ROOT / history.HISTORY
    data = history.load(path)
    problems = history.validate(data)
    if problems:
        raise SystemExit("history is invalid before append:\n" + "\n".join(problems))
    bases = [{}]
    if args.from_json:
        loaded = json.loads(args.from_json.read_text(encoding="utf-8"))
        bases = loaded if isinstance(loaded, list) else [loaded]
    new_entries = []
    for base in bases:
        entry = build_entry(base, args, data)
        data["measurements"].append(entry)  # so the next id/ordering sees it
        new_entries.append(entry)
    problems = history.validate(data)
    if problems:
        raise SystemExit("refusing to append invalid entry:\n" + "\n".join(problems))
    block = "".join(history.dump_entry(e) for e in new_entries)
    if args.dry_run:
        sys.stdout.write(block)
        return 0
    original = path.read_text(encoding="utf-8")
    path.write_text(original.rstrip("\n") + "\n" + block, encoding="utf-8")
    if history.validate(yaml.safe_load(path.read_text(encoding="utf-8"))):
        path.write_text(original, encoding="utf-8")
        raise SystemExit("appended file failed validation; restored")
    print(f"appended {', '.join(e['id'] for e in new_entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
