#!/usr/bin/env python3
"""Check that this checkout can run Codex chats under the repository's rules.

Codex chats obey the same rule set as Claude chats: AGENTS.md is generated from CLAUDE.md
(scripts/agents_md.py) and .codex/hooks.json sends every Codex hook event to
scripts/codex_hook_adapter.py, which runs the hooks of .claude/settings.json. The host-wide
Codex config (hooks switched on, project trust, model and effort defaults) is managed by
the dev host outside this repository. claude_dispatch runs `check` before it starts a
Codex chat and refuses the start when a guard is missing, so a Codex chat never runs without
its guards. A stale AGENTS.md only warns (owner, 23 Nov): sessions.py deploy regenerates it.

Commands:
  check [--no-cli]   Exit 1 with the reasons when AGENTS.md drifted, .codex/hooks.json is not
                     the fixed adapter file, the host config does not switch hooks on or trust
                     this checkout, or (without --no-cli) the CLI is missing or not logged in.
Tests: scripts/tests/test_codex_setup.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS = ("PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop", "SubagentStop")
ADAPTER = 'python3 "$(git rev-parse --show-toplevel)/scripts/codex_hook_adapter.py" --event {event}'


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_bin() -> str:
    return os.environ.get("CODEX_BIN") or str(Path.home() / ".local" / "bin" / "codex")


def hooks_problems(repo: Path) -> list[str]:
    try:
        hooks = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, ValueError, AttributeError) as error:
        return [f".codex/hooks.json unreadable: {error}"]
    found = []
    for event in EVENTS:
        commands = [h.get("command") for g in hooks.get(event) or [] for h in g.get("hooks") or []]
        if commands != [ADAPTER.format(event=event)]:
            found.append(f".codex/hooks.json: {event} must run only the adapter")
    extra = sorted(set(hooks) - set(EVENTS))
    if extra:
        found.append(f".codex/hooks.json: unexpected events {extra}")
    return found


def config_problems(repo: Path, home: Path) -> list[str]:
    try:
        text = (home / "config.toml").read_text(encoding="utf-8")
    except OSError:
        return [f"{home / 'config.toml'} is missing (the dev host installs it)"]
    found = []
    flat = text.replace(" ", "")
    if "hooks=true" not in flat:
        found.append(f"{home / 'config.toml'} does not switch hooks on ([features] hooks = true)")
    canonical = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=repo,
                               capture_output=True, text=True, check=False).stdout.strip()
    root = str(Path(canonical).parent) if canonical else str(repo)
    if f'[projects."{root}"]' not in text or 'trust_level = "trusted"' not in text:
        found.append(f"{home / 'config.toml'} does not trust {root} (its project hooks would not load)")
    return found


def cli_problems() -> list[str]:
    binary = codex_bin()
    if not os.access(binary, os.X_OK):
        return [f"Codex CLI missing at {binary}"]
    status = subprocess.run([binary, "login", "status"], capture_output=True, text=True, timeout=30, check=False)
    if status.returncode != 0 or "not logged in" in (status.stdout + status.stderr).lower():
        return [f"Codex is not logged in: the owner runs {binary} login --device-auth"]
    return []


def problems(repo: Path, home: Path, cli: bool = True) -> list[str]:
    found = hooks_problems(repo)
    agents = subprocess.run([sys.executable, str(repo / "scripts" / "agents_md.py"), "check", "--repo", str(repo)],
                            capture_output=True, text=True, check=False)
    if agents.returncode != 0:  # owner, 23 Nov: drift warns, never refuses a start (deploy regenerates it)
        print("warning: AGENTS.md drifted from CLAUDE.md (the next deploy regenerates it; "
              "now: python3 scripts/agents_md.py generate)", file=sys.stderr)
    if cli:
        found += config_problems(repo, home) + cli_problems()
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check",))
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--codex-home", type=Path, default=None)
    parser.add_argument("--no-cli", action="store_true", help="repository files only (CI, tests)")
    args = parser.parse_args(argv)
    found = problems(args.repo, args.codex_home or codex_home(), cli=not args.no_cli)
    print("\n".join(found) if found else "codex runtime ok")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
