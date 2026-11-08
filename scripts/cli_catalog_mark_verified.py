#!/usr/bin/env python3
"""Mark CLI catalog commands as differential-verified from CI differential artifacts.

Input is one or more `cli-native-differential-<group>.json` files written by
frontend/apps/web_app/tests/helpers/cli-native-differential.ts. A command counts as
verified only when every record naming it in `catalog` has verdict `pass`; any `gap`
or `fail` record (an expectedGap or a mismatch) makes the command ineligible and the
command is skipped (or refused when named with --command). Only the first `gaps[]` string of each verified entry changes: it gets
the "Differential-verified against the npm CLI (<spec>)" prefix and keeps its old text.
The tool is deterministic and idempotent. After a write, run
scripts/sync_rust_cli_assets.py to refresh the assets copy and manifest sha.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path("config/cli-command-catalog.json")
PREFIX = "Differential-verified against the npm CLI ("
SUFFIX = "): exit code, normalized JSON stdout and stderr class match."


def eligible_commands(artifacts: list[Path], requested: set[str] | None = None) -> set[str]:
    """Commands whose every record passed. Without `requested`, gap/fail commands are skipped;
    with it, any requested command that is not pass-only (expectedGap, mismatch, absent) is refused."""
    verdicts: dict[str, set[str]] = {}
    for artifact in artifacts:
        for record in json.loads(artifact.read_text(encoding="utf-8"))["records"]:
            for command in record.get("catalog") or []:
                verdicts.setdefault(command, set()).add(record["verdict"])
    passed = {c for c, v in verdicts.items() if v == {"pass"}}
    if requested is None:
        return passed
    refused = sorted(requested - passed)
    if refused:
        raise ValueError(
            "Refusing commands that are not pass-only in the artifacts "
            "(expectedGap, mismatch or not run): " + ", ".join(refused)
        )
    return set(requested)


def marker(spec: str) -> str:
    return PREFIX + spec + SUFFIX


def mark(catalog: dict, commands: set[str], spec: str) -> list[str]:
    """Update gaps[0] of each named entry in place; returns the commands that changed."""
    by_path = {" ".join(entry["path"]): entry for entry in catalog["commands"]}
    unknown = sorted(commands - set(by_path))
    if unknown:
        raise ValueError("Unknown catalog commands: " + ", ".join(unknown))
    changed = []
    for command in sorted(commands):
        gaps = by_path[command].setdefault("gaps", [])
        text = marker(spec)
        if gaps and gaps[0].startswith(PREFIX):
            rest = gaps[0].split(SUFFIX, 1)[1].lstrip() if SUFFIX in gaps[0] else ""
            updated = (text + " " + rest).rstrip()
        elif gaps:
            updated = text + " " + gaps[0]
        else:
            updated = text
        if gaps and gaps[0] == updated:
            continue
        if gaps:
            gaps[0] = updated
        else:
            gaps.append(updated)
        changed.append(command)
    return changed


def run(spec: str, artifacts: list[Path], root: Path = ROOT, requested: set[str] | None = None) -> list[str]:
    commands = eligible_commands(artifacts, requested)
    path = root / CATALOG
    catalog = json.loads(path.read_text(encoding="utf-8"))
    changed = mark(catalog, commands, spec)
    if changed:
        path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="e.g. cli-native-plans.spec.ts")
    parser.add_argument("--command", action="append", help="require this command to be pass-only (repeatable)")
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        changed = run(args.spec, args.artifacts, requested=set(args.command) if args.command else None)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error)) from error
    print(f"{len(changed)} catalog entries updated for {args.spec}")


if __name__ == "__main__":
    main()
