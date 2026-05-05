#!/usr/bin/env python3
"""
Adds task frontmatter to Obsidian notes that use capture tags.

This script is intentionally conservative: it detects #todo, #bug, and #event
in note content, adds only missing YAML properties, and leaves the note body
unchanged. Existing frontmatter values win, so manual edits remain the source of
truth once a note has been classified.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = PROJECT_ROOT / "vaults" / "memory"
EXCLUDED_DIRS = {".obsidian", ".obsidian-auto", "Daily Notes", "Templates"}
EXCLUDED_TYPES = {"board", "dashboard", "daily-note", "guide"}
CAPTURE_TAG_PATTERN = re.compile(r"(?<!\w)#(?P<tag>todo|bug|event)\b", re.IGNORECASE)
FRONTMATTER_END = "\n---"


@dataclass(frozen=True)
class Classification:
    note_type: str
    tags: tuple[str, ...]
    area: str


CLASSIFICATIONS = {
    "todo": Classification(note_type="task", tags=("task",), area=""),
    "bug": Classification(note_type="bug", tags=("bug",), area="bugs"),
    "event": Classification(note_type="event", tags=("event", "marketing"), area="marketing"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Obsidian capture-tag task notes.")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--write", action="store_true", help="Write changes. Defaults to dry-run.")
    return parser.parse_args()


def should_skip(path: Path, vault: Path) -> bool:
    parts = path.relative_to(vault).parts
    return bool(parts and parts[0] in EXCLUDED_DIRS)


def parse_frontmatter(text: str) -> tuple[list[str], str]:
    if not text.startswith("---\n"):
        return [], text
    end = text.find(FRONTMATTER_END, 4)
    if end == -1:
        return [], text
    body_start = end + len(FRONTMATTER_END)
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1
    return text[4:end].splitlines(), text[body_start:]


def frontmatter_keys(lines: list[str]) -> set[str]:
    keys: set[str] = set()
    for line in lines:
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, _ = line.split(":", 1)
        keys.add(key.strip())
    return keys


def frontmatter_value(lines: list[str], key: str) -> str:
    prefix = f"{key}:"
    for line in lines:
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip().strip('"')
    return ""


def frontmatter_tags(lines: list[str]) -> set[str]:
    tags: set[str] = set()
    in_tags = False
    for line in lines:
        stripped = line.strip()
        if stripped == "tags:":
            in_tags = True
            continue
        if in_tags and stripped.startswith("- "):
            tags.add(stripped[2:].strip())
            continue
        if in_tags and stripped and not line.startswith((" ", "\t")):
            break
    return tags


def classify(text: str) -> Classification | None:
    found = {match.group("tag").lower() for match in CAPTURE_TAG_PATTERN.finditer(text)}
    if "bug" in found:
        return CLASSIFICATIONS["bug"]
    if "event" in found:
        return CLASSIFICATIONS["event"]
    if "todo" in found:
        return CLASSIFICATIONS["todo"]
    return None


def updated_frontmatter(lines: list[str], classification: Classification) -> list[str]:
    keys = frontmatter_keys(lines)
    existing_tags = frontmatter_tags(lines)
    new_lines = list(lines)

    defaults = [
        ("type", classification.note_type),
        ("project", "OpenMates"),
        ("area", classification.area),
        ("task_status", "backlog"),
        ("priority", "medium"),
        ("due", ""),
        ("created", date.today().isoformat()),
    ]
    for key, value in defaults:
        if key not in keys:
            new_lines.append(f"{key}: {value}")

    missing_tags = [tag for tag in classification.tags if tag not in existing_tags]
    if "tags" not in keys:
        new_lines.append("tags:")
        new_lines.extend(f"  - {tag}" for tag in classification.tags)
    elif missing_tags:
        insert_at = len(new_lines)
        for index, line in enumerate(new_lines):
            if line.strip() == "tags:":
                insert_at = index + 1
                while insert_at < len(new_lines) and new_lines[insert_at].startswith((" ", "\t")):
                    insert_at += 1
                break
        for tag in reversed(missing_tags):
            new_lines.insert(insert_at, f"  - {tag}")

    return new_lines


def normalize_note(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    classification = classify(text)
    if not classification:
        return False
    lines, body = parse_frontmatter(text)
    if frontmatter_value(lines, "type") in EXCLUDED_TYPES or "task_status" in frontmatter_keys(lines):
        return False
    new_lines = updated_frontmatter(lines, classification)
    new_text = "\n".join(["---", *new_lines, "---", body]).rstrip() + "\n"
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> None:
    args = parse_args()
    vault = args.vault.expanduser()
    changed: list[Path] = []
    candidates: list[Path] = []
    for path in vault.rglob("*.md"):
        if should_skip(path, vault):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines, _ = parse_frontmatter(text)
        if (
            classify(text)
            and frontmatter_value(lines, "type") not in EXCLUDED_TYPES
            and "task_status" not in frontmatter_keys(lines)
        ):
            candidates.append(path)

    if args.write:
        for path in candidates:
            if normalize_note(path):
                changed.append(path)
    else:
        changed = candidates

    action = "updated" if args.write else "would update"
    for path in changed:
        print(f"{action}: {path.relative_to(vault)}")
    print(f"{action} {len(changed)} note(s)")


if __name__ == "__main__":
    main()
