#!/usr/bin/env python3
"""Generate AGENTS.md for OpenAI Codex chats from the Claude sources.

Single source of truth: CLAUDE.md, .claude/rules/*.md and
.claude/skills/*/SKILL.md. AGENTS.md is a generated file; never edit it.

Commands:
  generate  write AGENTS.md at the repo root
  check     exit 1 with a short diff summary when AGENTS.md differs from the
            generated output or the output exceeds the host's 64 KiB
            project_doc_max_bytes (warns above Codex's default 32 KiB)

sessions.py deploy regenerates AGENTS.md on every deploy, so it never drifts on dev.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MAX_BYTES = 65536  # the dev host's ~/.codex/config.toml project_doc_max_bytes (connector-managed)
DEFAULT_CODEX_BYTES = 32768  # Codex's own default; above it only hosts with the larger setting read it all

HEADER = (
    "<!-- Generated from CLAUDE.md, .claude/rules and .claude/skills by "
    "scripts/agents_md.py; do not edit. Run "
    "`python3 scripts/agents_md.py generate`. -->\n"
)

ENGINE_NOTES = """# Codex engine notes

You are a Codex chat started by the dev host. The rules below were written for
Claude and apply to you identically. Wherever they say Claude Code,
CLAUDE_CODE_SESSION_ID, a Claude hook or a Claude sub-agent, use the Codex
equivalents:
- Your chat id is $OPENMATES_CHAT_ID (also exported as CLAUDE_CODE_SESSION_ID,
  so sessions.py, agent_question.py and the waiters work unchanged). Link your
  Task with `--external-chat claude:$OPENMATES_CHAT_ID`.
- The repository hooks run for you too (.codex/hooks.json sends every event to
  scripts/codex_hook_adapter.py, which runs .claude/settings.json). A refusal
  is final: fix the cause, never work around a hook, and never edit the Codex
  hooks or config.
- Your session folder stays the canonical checkout: after `sessions.py start`,
  edit only with absolute paths inside the returned worktree and run commands
  with that worktree as working directory.
- No Claude-only tools (SendUserFile, Agent types, Skill tool): read a skill's
  SKILL.md when the rules point to `/skill-name`; show proof files with
  `agent_question.py --attach`.
- Model and effort are fixed by the launcher (medium at most); never switch
  model or raise effort, also not for sub-agents.
"""


def parse_frontmatter(text: str, path: Path) -> dict:
    """Return the YAML frontmatter of a markdown file ({} when absent)."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter")
    data = yaml.safe_load(text[4:end])
    return data if isinstance(data, dict) else {}


def _one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def build(repo: Path) -> str:
    """Return the full AGENTS.md text for the repo at `repo`."""
    parts = [HEADER, ENGINE_NOTES]
    claude = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    parts.append(claude if claude.endswith("\n") else claude + "\n")

    rules = ["# Domain rules\n"]
    for rule in sorted((repo / ".claude" / "rules").glob("*.md")):
        rel = rule.relative_to(repo).as_posix()
        meta = parse_frontmatter(rule.read_text(encoding="utf-8"), rule)
        globs = meta.get("paths") or []
        if isinstance(globs, str):
            globs = [globs]
        rules.append(f"\n## {rel}\n")
        if globs:
            rules.append("applies when you touch: " + ", ".join(f"`{g}`" for g in globs) + "\n")
        rules.append("Read this file before editing matching files.\n")
    parts.append("".join(rules))

    skills = ["# Skills\n\n"]
    for skill in sorted((repo / ".claude" / "skills").glob("*/SKILL.md")):
        rel = skill.relative_to(repo).as_posix()
        meta = parse_frontmatter(skill.read_text(encoding="utf-8"), skill)
        name = meta.get("name") or skill.parent.name
        skills.append(f"- `/{name}` — {_one_line(meta.get('description'))} — {rel}\n")
    parts.append("".join(skills))
    return "\n".join(p if p.endswith("\n") else p + "\n" for p in parts)


def cmd_generate(repo: Path) -> int:
    text = build(repo)
    (repo / "AGENTS.md").write_text(text, encoding="utf-8")
    size = len(text.encode("utf-8"))
    print(f"AGENTS.md written ({size} bytes)")
    if size > DEFAULT_CODEX_BYTES:
        print(f"note: above Codex's default {DEFAULT_CODEX_BYTES} bytes; the dev host reads up to {MAX_BYTES}",
              file=sys.stderr)
    if size > MAX_BYTES:
        print(f"WARNING: exceeds {MAX_BYTES} bytes", file=sys.stderr)
        return 1
    return 0


def cmd_check(repo: Path) -> int:
    expected = build(repo)
    size = len(expected.encode("utf-8"))
    print(f"generated size: {size} bytes (limit {MAX_BYTES})")
    failed = False
    if size > MAX_BYTES:
        print(f"FAIL: generated AGENTS.md exceeds {MAX_BYTES} bytes")
        failed = True
    target = repo / "AGENTS.md"
    actual = target.read_text(encoding="utf-8") if target.exists() else None
    if actual != expected:
        failed = True
        if actual is None:
            print("FAIL: AGENTS.md is missing")
        else:
            diff = list(difflib.unified_diff(
                actual.splitlines(), expected.splitlines(),
                "AGENTS.md", "generated", lineterm="", n=0))
            print(f"FAIL: AGENTS.md is stale ({len(diff)} diff lines); first lines:")
            print("\n".join(diff[:12]))
        print("Run `python3 scripts/agents_md.py generate`.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["generate", "check"])
    parser.add_argument("--repo", type=Path, default=REPO, help="repo root (default: this repo)")
    args = parser.parse_args(argv)
    if args.command == "generate":
        return cmd_generate(args.repo)
    return cmd_check(args.repo)


if __name__ == "__main__":
    sys.exit(main())
