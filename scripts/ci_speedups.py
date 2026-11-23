#!/usr/bin/env python3
"""Switch for CI speedups that roll out per job owner before they become the default.

Each speedup changes how an isolated CI job prepares itself (caches, prepared
builds), never what it tests. A new speedup starts off for everyone, is tried
by named owners (coordinator session ids, e.g. a canary lane), and is turned on
for all jobs once its canary runs are green. The coordinator passes the enabled
names to `.github/workflows/isolated-tests.yml` as the `ci_speedups` input (a
sorted comma list); workflow steps test it with `contains(inputs.ci_speedups, …)`.

Switch file `logs/ci-coordinator/speedups.json` (missing or unreadable = all off):
  {"default": ["wasm-cache"], "owners": {"2088": ["browser-cache"]}}
An owner gets the default names plus its own. Unknown names are ignored so a
typo can never reach the workflow.

Usage:
  python3 scripts/ci_speedups.py status
  python3 scripts/ci_speedups.py enable <name> [--owner <session>]
  python3 scripts/ci_speedups.py disable <name> [--owner <session>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# wasm-cache: restore the web Rust core wasm package from a content-addressed cache.
# browser-cache: restore Playwright browsers from a cache keyed on the Playwright version.
# prepared-rust-core: the prepare job ships the Rust-core web build; consumers skip rebuilds.
# e2b-template: E2B overflow jobs start from a prepared dependency template (scripts/ci_e2b_template.py).
KNOWN = frozenset({"wasm-cache", "browser-cache", "prepared-rust-core", "e2b-template"})
ROOT = Path(__file__).resolve().parents[1]


def canonical_root(root: Path = ROOT) -> Path:
    """The main checkout, also when this runs from a linked worktree.

    The coordinator daemon runs in the main checkout; a worktree-local switch
    file would make a chat's submit and the daemon's dispatch disagree.
    """
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root, capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return root
    return Path(common).parent if common else root


def switch_path() -> Path:
    override = os.environ.get("OPENMATES_CI_SPEEDUPS_FILE")
    return Path(override) if override else canonical_root() / "logs" / "ci-coordinator" / "speedups.json"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        print(f"ci_speedups: ignoring unreadable {path}: {error}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _names(value) -> set[str]:
    return {name for name in value if isinstance(name, str) and name in KNOWN} if isinstance(value, list) else set()


def enabled(owner: str, path: Path | None = None) -> frozenset[str]:
    """Speedups on for jobs of `owner`: the default list plus the owner's own."""
    data = _load(path or switch_path())
    owners = data.get("owners") if isinstance(data.get("owners"), dict) else {}
    return frozenset(_names(data.get("default")) | _names(owners.get(owner)))


def dispatch_value(owner: str, path: Path | None = None) -> str:
    """The workflow `ci_speedups` input for a job of `owner` ('' when none is on)."""
    return ",".join(sorted(enabled(owner, path)))


def _update(name: str, owner: str, on: bool, path: Path) -> dict:
    if name not in KNOWN:
        raise SystemExit(f"unknown speedup {name!r}; known: {', '.join(sorted(KNOWN))}")
    data = _load(path)
    owners = data.get("owners") if isinstance(data.get("owners"), dict) else {}
    target = set(_names(owners.get(owner))) if owner else set(_names(data.get("default")))
    target = target | {name} if on else target - {name}
    if owner:
        owners[owner] = sorted(target)
        data["owners"] = {key: value for key, value in owners.items() if value}
    else:
        data["default"] = sorted(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    for action in ("enable", "disable"):
        cmd = sub.add_parser(action)
        cmd.add_argument("name")
        cmd.add_argument("--owner", default="", help="session id; omit to change the default for all jobs")
    args = parser.parse_args(argv)
    path = switch_path()
    if args.action == "status":
        print(json.dumps(_load(path) or {"default": [], "owners": {}}, indent=2, sort_keys=True))
        return 0
    print(json.dumps(_update(args.name, args.owner, args.action == "enable", path), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
