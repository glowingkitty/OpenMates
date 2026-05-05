#!/usr/bin/env python3
"""
Generates Linear-style Kanban boards for the local Obsidian memory vault.

Notes remain the source of truth: each task card is a Markdown note with a
`task_status` frontmatter field. This script scans those notes and rewrites the
derived board files for all tasks, marketing tasks, and bug/report tasks. It is
safe for cron because output is deterministic and uses only the Python standard
library.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = PROJECT_ROOT / "vaults" / "memory"
BOARDS_DIR = Path("Boards")
TASK_STATUSES = ("backlog", "todo", "in_progress", "in_review", "done")
STATUS_TITLES = {
    "backlog": "Backlog",
    "todo": "Todo",
    "in_progress": "In Progress",
    "in_review": "In Review",
    "done": "Done",
}
EXCLUDED_TYPES = {"board", "dashboard", "daily-note", "guide"}
EXCLUDED_DIRS = {".obsidian", ".obsidian-auto", "Daily Notes", "Templates", "Boards", "Archive"}


@dataclass(frozen=True)
class TaskNote:
    path: Path
    link: str
    note_type: str
    project: str
    area: str
    task_status: str
    priority: str
    due: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Board:
    filename: str
    title: str
    description: str
    area: str
    predicate: str


BOARDS = (
    Board(
        filename="all-todos.md",
        title="All Todos",
        description="All note-level tasks in the vault, grouped by status.",
        area="task-management",
        predicate="all",
    ),
    Board(
        filename="marketing.md",
        title="Marketing",
        description="Open marketing tasks and projects, grouped by status.",
        area="marketing",
        predicate="marketing",
    ),
    Board(
        filename="bugs.md",
        title="Bugs & Reported Issues",
        description="Bugs and reported issues, grouped by status.",
        area="bugs",
        predicate="bugs",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Obsidian task Kanban boards.")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def parse_frontmatter(text: str) -> dict[str, str | list[str]]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}

    data: dict[str, str | list[str]] = {}
    current_list: str | None = None
    for line in text[4:end].splitlines():
        stripped = line.strip()
        if not stripped:
            current_list = None
            continue
        if current_list and stripped.startswith("- "):
            existing = data.setdefault(current_list, [])
            if isinstance(existing, list):
                existing.append(stripped[2:].strip())
            continue
        if line.startswith((" ", "\t")) or ":" not in line:
            current_list = None
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if value:
            data[key] = value
            current_list = None
        else:
            data[key] = []
            current_list = key
    return data


def prop(props: dict[str, str | list[str]], key: str) -> str:
    value = props.get(key)
    return value if isinstance(value, str) else ""


def tags(props: dict[str, str | list[str]]) -> tuple[str, ...]:
    value = props.get("tags")
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, str):
        return (value,)
    return ()


def should_skip(path: Path, vault: Path) -> bool:
    parts = path.relative_to(vault).parts
    return bool(parts and parts[0] in EXCLUDED_DIRS)


def obsidian_link(path: Path, vault: Path) -> str:
    return f"[[{path.relative_to(vault).with_suffix('').as_posix()}]]"


def load_tasks(vault: Path) -> list[TaskNote]:
    tasks: list[TaskNote] = []
    for path in vault.rglob("*.md"):
        if should_skip(path, vault):
            continue
        props = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        note_type = prop(props, "type")
        task_status = prop(props, "task_status")
        if not task_status or note_type in EXCLUDED_TYPES:
            continue
        if task_status not in TASK_STATUSES:
            task_status = "backlog"
        tasks.append(
            TaskNote(
                path=path,
                link=obsidian_link(path, vault),
                note_type=note_type,
                project=prop(props, "project"),
                area=prop(props, "area"),
                task_status=task_status,
                priority=prop(props, "priority"),
                due=prop(props, "due"),
                tags=tags(props),
            )
        )
    return sorted(tasks, key=task_sort_key)


def task_sort_key(task: TaskNote) -> tuple[int, str, str, str]:
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return (priority_order.get(task.priority, 3), task.due or "9999-99-99", task.area, task.link.lower())


def task_matches(board: Board, task: TaskNote) -> bool:
    if board.predicate == "all":
        return True
    if board.predicate == "marketing":
        return task.area == "marketing" or "marketing" in task.tags
    if board.predicate == "bugs":
        return task.note_type == "bug" or "bug" in task.tags or task.area in {"bugs", "billing"}
    return False


def task_line(task: TaskNote) -> str:
    details = []
    if task.priority:
        details.append(task.priority)
    if task.due:
        details.append(f"due {task.due}")
    if task.area:
        details.append(task.area)
    suffix = f" ({', '.join(details)})" if details else ""
    return f"- [ ] {task.link}{suffix}"


def board_content(board: Board, tasks: list[TaskNote]) -> str:
    lines = [
        "---",
        "type: board",
        "kanban-plugin: board",
        "project: OpenMates",
        f"area: {board.area}",
        "task_status: in_progress",
        "tags:",
        "  - kanban",
        "  - task-management",
        "---",
        "",
        f"# {board.title}",
        "",
        board.description,
        "",
        "> Generated from note frontmatter. Change `task_status` in the linked note, then rerun the board generator.",
        "",
    ]

    board_tasks = [task for task in tasks if task_matches(board, task)]
    for status in TASK_STATUSES:
        lines.append(f"## {STATUS_TITLES[status]}")
        lines.append("")
        status_tasks = [task for task in board_tasks if task.task_status == status]
        if status_tasks:
            lines.extend(task_line(task) for task in status_tasks)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    args = parse_args()
    vault = args.vault.expanduser()
    tasks = load_tasks(vault)
    for board in BOARDS:
        output_path = vault / BOARDS_DIR / board.filename
        content = board_content(board, tasks)
        if args.dry_run:
            print(f"Would write {output_path} ({len(content.splitlines())} lines)")
            continue
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
