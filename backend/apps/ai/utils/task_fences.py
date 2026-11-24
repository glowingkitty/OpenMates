"""Validate assistant-authored ``openmates_task`` fences.

A Task is created or edited only through an inline JSON block in the reply.
This module is pure: it parses the block, checks every field against the chat
context handed in by the caller (known Team members and Projects) and returns a
normalized model plus plain-English errors. It never reads or writes anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

TASK_FENCE_LANGUAGES = frozenset({"openmates_task", "omtask"})
MAX_SOURCE_BYTES = 64 * 1024
MAX_TITLE = 200
MAX_DESCRIPTION = 4000
CREATE_STATUSES = ("backlog", "todo", "in_progress", "blocked")
KNOWN_FIELDS = ("title", "description", "status", "due_date", "assignee", "project", "plan")
MAX_PLAN_REF = 128
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})\Z"
)


def is_task_fence(language: str | None) -> bool:
    return (language or "").strip().lower() in TASK_FENCE_LANGUAGES


@dataclass(frozen=True)
class TaskFenceContext:
    is_team: bool = False
    known_assignees: dict[str, str] = field(default_factory=dict)
    known_projects: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskFenceResult:
    status: str
    model: dict[str, Any] | None
    source_json: str
    title: str
    errors: list[dict[str, str]]
    warnings: list[dict[str, str]]


def _issue(field_name: str, code: str, message: str) -> dict[str, str]:
    return {"field": field_name, "code": code, "message": message}


def _parse_due(value: str) -> int | None:
    """Return unix seconds for a valid due date, or None when it is invalid."""
    if DATE.fullmatch(value):
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return None
        return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    if TIMESTAMP.fullmatch(value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.utcoffset() is not None:
            return int(parsed.timestamp())
    return None


def _canonical_source(raw: dict[str, Any]) -> str:
    ordered = {key: raw[key] for key in KNOWN_FIELDS if key in raw and raw[key] is not None}
    return json.dumps(ordered, ensure_ascii=False, indent=2)


def validate_task_fence(
    source: str, *, context: TaskFenceContext, allow_done: bool = False
) -> TaskFenceResult:
    """Parse and validate one task block; ``allow_done`` is true only for edits."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    try:
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("too large")
        raw = json.loads(source)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
    except (ValueError, RecursionError):
        return TaskFenceResult(
            "invalid", None, source[:MAX_SOURCE_BYTES], "",
            [_issue("source", "invalid_json", "The task block is not a valid JSON object.")], [],
        )

    for key in raw:
        if key not in KNOWN_FIELDS:
            warnings.append(_issue(str(key), "unknown_field", f'The field "{key}" is not used for tasks and was ignored.'))

    def text(name: str) -> str | None:
        value = raw.get(name)
        return value.strip() if isinstance(value, str) else None

    title = text("title") or ""
    if not title:
        errors.append(_issue("title", "missing_title", "The task needs a title."))
    elif len(title) > MAX_TITLE:
        errors.append(_issue("title", "title_too_long", f"The title is longer than {MAX_TITLE} characters."))

    description = text("description")
    if raw.get("description") is not None and (description is None or len(description) > MAX_DESCRIPTION):
        errors.append(_issue("description", "description_too_long", f"The description must be text of at most {MAX_DESCRIPTION} characters."))

    status = (text("status") or "todo").lower() if raw.get("status") is not None else "todo"
    allowed = CREATE_STATUSES + (("done",) if allow_done else ())
    if status not in allowed:
        hint = " A task can only be marked done by editing it." if status == "done" else ""
        errors.append(_issue("status", "invalid_status", f'"{status}" is not a valid status; use {", ".join(allowed)}.{hint}'))

    due_date = text("due_date")
    due_at = None
    if raw.get("due_date") is not None:
        due_at = _parse_due(due_date) if due_date else None
        if due_at is None:
            errors.append(_issue("due_date", "invalid_due_date", "Use a valid date or a timestamp with a UTC offset."))

    assignee_raw = text("assignee") if raw.get("assignee") is not None else "user"
    assignee_key = (assignee_raw or "").lower()
    assignee_type, assignee_id, assignee_name = "user", None, None
    if assignee_key == "openmates":
        assignee_type = "openmates"
    elif assignee_key in ("user", "me"):
        assignee_type = "user"  # in a Team chat this is the requesting member
    elif context.is_team and assignee_key in context.known_assignees:
        assignee_type, assignee_id, assignee_name = "member", context.known_assignees[assignee_key], assignee_raw
    else:
        assignee_type = "user"
        where = "this Team" if context.is_team else "a personal chat (use user or openmates)"
        errors.append(_issue("assignee", "unknown_assignee", f'The assignee "{assignee_raw}" is not available in {where}.'))

    project_raw = text("project")
    project_id, project_name = None, None
    if raw.get("project") is not None:
        found = context.known_projects.get((project_raw or "").lower())
        if found is None:
            errors.append(_issue("project", "unknown_project", f'The Project "{project_raw}" was not found.'))
        else:
            project_id, project_name = found, project_raw

    # A Plan reference (Spec authoring): the caller checks that the Plan exists when staging.
    plan_id = text("plan")
    if raw.get("plan") is not None and (not plan_id or len(plan_id) > MAX_PLAN_REF):
        errors.append(_issue("plan", "invalid_plan", "The plan must be the Plan reference returned when it was created."))

    canonical = dict(raw)
    canonical.update({"title": title or raw.get("title"), "status": status, "assignee": assignee_raw})
    if description:
        canonical["description"] = description
    else:
        canonical.pop("description", None)
    if due_date:
        canonical["due_date"] = due_date
    if project_raw:
        canonical["project"] = project_raw
    source_json = _canonical_source(canonical)

    if errors:
        return TaskFenceResult("invalid", None, source_json, title, errors, warnings)
    model = {
        "title": title, "description": description or "", "status": status,
        "due_date": due_date, "due_at": due_at, "assignee_type": assignee_type,
        "assignee_id": assignee_id, "assignee_name": assignee_name,
        "project_id": project_id, "project_name": project_name, "plan_id": plan_id or None,
    }
    return TaskFenceResult("valid", model, source_json, title, errors, warnings)


def task_validation_feedback(errors: list[dict[str, str]]) -> str:
    """One plain line per error, for the next turn's history."""
    return "\n".join(f"- {error.get('message', '')}" for error in errors)
