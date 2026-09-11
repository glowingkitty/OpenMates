#!/usr/bin/env python3
"""Install the dev-host dependency security schedule.

The GitHub default branch remains production-oriented, so recurring dev scans
run from the canonical dev checkout. The managed crontab block is idempotent,
does not import repository secrets, and replaces legacy disabled entries.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


BEGIN_MARKER = "# BEGIN OpenMates dev dependency security"
END_MARKER = "# END OpenMates dev dependency security"
SCANNER_NAMES = ("check-dependabot-daily.sh", "check-eu-vulns-daily.sh")


def default_project_root() -> Path:
    """Use the canonical dev checkout even when invoked from a session worktree."""
    script_root = Path(__file__).resolve().parent.parent
    marker = ".openmates-agent-worktrees"
    if marker in script_root.parts:
        return Path(*script_root.parts[: script_root.parts.index(marker)])
    return script_root


def render_crontab(existing: str, project_root: Path) -> str:
    """Return a crontab with one canonical dependency-security block."""
    retained: list[str] = []
    in_managed_block = False
    for line in existing.splitlines():
        if line == BEGIN_MARKER:
            in_managed_block = True
            continue
        if line == END_MARKER:
            in_managed_block = False
            continue
        if in_managed_block or any(name in line for name in SCANNER_NAMES):
            continue
        retained.append(line)

    while retained and not retained[-1].strip():
        retained.pop()

    root = project_root.resolve()
    block = [
        BEGIN_MARKER,
        "# Hourly dev vulnerability discovery and unattended minimum-fixed updates.",
        f"30 * * * * {root}/scripts/check-dependabot-daily.sh >> {root}/logs/dependabot-alerts.log 2>&1",
        f"35 * * * * {root}/scripts/check-eu-vulns-daily.sh >> {root}/logs/eu-vulns.log 2>&1",
        END_MARKER,
    ]
    return "\n".join([*retained, "", *block]).strip() + "\n"


def current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or "could not read crontab")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=default_project_root(),
    )
    args = parser.parse_args()
    if args.install == args.check:
        parser.error("choose exactly one of --install or --check")

    existing = current_crontab()
    expected = render_crontab(existing, args.project_root)
    if args.check:
        if existing != expected:
            print("Dependency security schedule is not current.")
            return 1
        print("Dependency security schedule is current.")
        return 0

    result = subprocess.run(["crontab", "-"], input=expected, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "could not install crontab")
    print("Installed dev dependency security schedule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
