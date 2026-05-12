#!/usr/bin/env python3
"""Synchronize OpenMates agent-tool compatibility files.

Claude Code remains the canonical authoring format for project skills,
subagents, and hook scripts. This helper generates the Codex/OpenCode mirror
files that use different metadata formats while preserving the same workflow
instructions. Run with `--check` in validation paths to detect drift.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
AGENT_SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
CLAUDE_AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
CODEX_AGENTS_DIR = REPO_ROOT / ".codex" / "agents"
OPENCODE_AGENTS_DIR = REPO_ROOT / ".opencode" / "agents"
CLAUDE_HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
CODEX_HOOKS_DIR = REPO_ROOT / ".codex" / "hooks"
CODEX_HOOK_BRIDGE = CODEX_HOOKS_DIR / "claude-hook-bridge.sh"
OPENCODE_HOOK_PLUGIN = REPO_ROOT / ".opencode" / "plugins" / "openmates-claude-hooks.js"

FRONTMATTER_BOUNDARY = "---"
MODEL_MAP = {
    "haiku": "claude-code/haiku",
    "sonnet": "claude-code/sonnet",
    "opus": "claude-code/opus",
}
NON_CLAUDE_HOOK_COMMANDS = {
    "lint-design-tokens.sh": REPO_ROOT / "scripts" / "lint-design-tokens.sh",
    "lint-swift-design-tokens.sh": REPO_ROOT / "scripts" / "lint-swift-design-tokens.sh",
}


class ParityError(RuntimeError):
    """Raised when generated compatibility files are out of sync."""


def parse_markdown(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text()
    lines = text.splitlines()
    if not lines or lines[0] != FRONTMATTER_BOUNDARY:
        raise ParityError(f"{path} is missing YAML frontmatter")

    try:
        end = lines.index(FRONTMATTER_BOUNDARY, 1)
    except ValueError as exc:
        raise ParityError(f"{path} has unterminated YAML frontmatter") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    body = "\n".join(lines[end + 1 :]).strip("\n")
    return metadata, body


def replace_frontmatter_name(text: str, name: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != FRONTMATTER_BOUNDARY:
        raise ParityError("skill is missing YAML frontmatter")

    try:
        end = lines.index(FRONTMATTER_BOUNDARY, 1)
    except ValueError as exc:
        raise ParityError("skill has unterminated YAML frontmatter") from exc

    name_seen = False
    for index in range(1, end):
        if lines[index].startswith("name:"):
            lines[index] = f"name: {name}"
            name_seen = True
            break

    if not name_seen:
        lines.insert(1, f"name: {name}")

    return "\n".join(lines).rstrip() + "\n"


def sync_skills(*, check: bool) -> list[str]:
    problems: list[str] = []
    AGENT_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    claude_skill_names = {path.parent.name for path in CLAUDE_SKILLS_DIR.glob("*/SKILL.md")}
    agent_skill_names = {path.parent.name for path in AGENT_SKILLS_DIR.glob("*/SKILL.md")}

    for stale_name in sorted(agent_skill_names - claude_skill_names):
        stale_dir = AGENT_SKILLS_DIR / stale_name
        problems.append(f"stale skill mirror: {stale_dir}")

    for source in sorted(CLAUDE_SKILLS_DIR.glob("*/SKILL.md")):
        name = source.parent.name
        target = AGENT_SKILLS_DIR / name / "SKILL.md"
        rendered = replace_frontmatter_name(source.read_text(), name)

        if check:
            if not target.exists():
                problems.append(f"missing skill mirror: {target}")
            elif target.read_text() != rendered:
                problems.append(f"out-of-sync skill mirror: {target}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)

    return problems


def toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_codex_agent(source: Path) -> str:
    metadata, body = parse_markdown(source)
    name = metadata.get("name", source.stem)
    description = metadata.get("description")
    if not description:
        raise ParityError(f"{source} is missing a description")

    tools = {tool.strip() for tool in metadata.get("tools", "").split(",") if tool.strip()}
    content = [
        f"name = {toml_string(name)}",
        f"description = {toml_string(description)}",
    ]

    if "Write" not in tools and "Edit" not in tools:
        content.append('sandbox_mode = "read-only"')

    content.extend([
        "developer_instructions = '''",
        body,
        "'''",
    ])
    return "\n".join(content).rstrip() + "\n"


def yaml_scalar(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def render_opencode_agent(source: Path) -> str:
    metadata, body = parse_markdown(source)
    description = metadata.get("description")
    if not description:
        raise ParityError(f"{source} is missing a description")

    tools = {tool.strip() for tool in metadata.get("tools", "").split(",") if tool.strip()}
    lines = [
        FRONTMATTER_BOUNDARY,
        f"description: {yaml_scalar(description)}",
        "mode: subagent",
    ]

    if model := metadata.get("model"):
        lines.append(f"model: {MODEL_MAP.get(model, model)}")
    if max_turns := metadata.get("maxTurns"):
        lines.append(f"steps: {max_turns}")

    lines.extend([
        "permission:",
        "  read: allow",
        "  grep: allow",
        "  glob: allow",
        f"  bash: {'allow' if 'Bash' in tools else 'deny'}",
        f"  edit: {'allow' if {'Write', 'Edit'} & tools else 'deny'}",
        FRONTMATTER_BOUNDARY,
        "",
        body,
    ])
    return "\n".join(lines).rstrip() + "\n"


def sync_agents(*, check: bool) -> list[str]:
    problems: list[str] = []
    CODEX_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    OPENCODE_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    claude_names = {path.stem for path in CLAUDE_AGENTS_DIR.glob("*.md")}
    codex_names = {path.stem for path in CODEX_AGENTS_DIR.glob("*.toml")}
    opencode_names = {path.stem for path in OPENCODE_AGENTS_DIR.glob("*.md")}

    for stale_name in sorted(codex_names - claude_names):
        problems.append(f"stale Codex agent mirror: {CODEX_AGENTS_DIR / (stale_name + '.toml')}")
    for stale_name in sorted(opencode_names - claude_names):
        problems.append(f"stale OpenCode agent mirror: {OPENCODE_AGENTS_DIR / (stale_name + '.md')}")

    for source in sorted(CLAUDE_AGENTS_DIR.glob("*.md")):
        codex_target = CODEX_AGENTS_DIR / f"{source.stem}.toml"
        opencode_target = OPENCODE_AGENTS_DIR / source.name
        expected = {
            codex_target: render_codex_agent(source),
            opencode_target: render_opencode_agent(source),
        }

        for target, rendered in expected.items():
            if check:
                if not target.exists():
                    problems.append(f"missing agent mirror: {target}")
                elif target.read_text() != rendered:
                    problems.append(f"out-of-sync agent mirror: {target}")
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered)

    return problems


def validate_skill_names() -> list[str]:
    problems: list[str] = []
    pattern = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
    for skill in sorted(AGENT_SKILLS_DIR.glob("*/SKILL.md")):
        metadata, _body = parse_markdown(skill)
        expected_name = skill.parent.name
        actual_name = metadata.get("name")
        if actual_name != expected_name:
            problems.append(f"{skill} has name {actual_name!r}, expected {expected_name!r}")
        if not pattern.fullmatch(expected_name):
            problems.append(f"{skill} directory is not a valid Agent Skills name")
    return problems


def validate_hooks() -> list[str]:
    problems: list[str] = []
    for codex_hook in sorted(CODEX_HOOKS_DIR.glob("*.sh")):
        if codex_hook.name == CODEX_HOOK_BRIDGE.name:
            continue
        claude_hook = CLAUDE_HOOKS_DIR / codex_hook.name
        if not claude_hook.exists():
            problems.append(f"Codex hook mirror has no Claude source: {codex_hook}")
        elif codex_hook.read_text() != claude_hook.read_text():
            problems.append(f"Codex hook mirror drifted from Claude source: {codex_hook}")

    bridge_text = CODEX_HOOK_BRIDGE.read_text()
    plugin_text = OPENCODE_HOOK_PLUGIN.read_text()
    referenced_hooks = set(re.findall(r'"([a-z0-9.-]+\.sh)"', bridge_text))
    referenced_hooks.update(re.findall(r'"([a-z0-9.-]+\.sh)"', plugin_text))
    for hook_name in sorted(referenced_hooks):
        if hook_name == CODEX_HOOK_BRIDGE.name:
            continue
        if hook_name in NON_CLAUDE_HOOK_COMMANDS:
            if not NON_CLAUDE_HOOK_COMMANDS[hook_name].exists():
                problems.append(f"adapter references missing script command: {hook_name}")
            continue
        if not (CLAUDE_HOOKS_DIR / hook_name).exists():
            problems.append(f"adapter references missing Claude hook: {hook_name}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize OpenMates agent-tool parity files")
    parser.add_argument("--check", action="store_true", help="only report drift without writing files")
    args = parser.parse_args()

    problems = [
        *sync_skills(check=args.check),
        *sync_agents(check=args.check),
        *validate_skill_names(),
        *validate_hooks(),
    ]
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1

    if args.check:
        print("Agent-tool parity is up to date.")
    else:
        print("Synchronized Agent Skills, Codex agents, and OpenCode agents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
