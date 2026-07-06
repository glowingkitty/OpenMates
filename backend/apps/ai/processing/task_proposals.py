# backend/apps/ai/processing/task_proposals.py
#
# Pure Tasks V1 proposal sanitizers for the AI postprocessor. These helpers keep
# assistant-generated task suggestions review-only and bounded before the client
# encrypts accepted content through /v1/user-tasks.

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAX_TASK_PROPOSALS = 3
TASK_PROPOSAL_STATUSES = {"backlog", "todo", "in_progress", "blocked", "done"}
TASK_PROPOSAL_ASSIGNEES = {"user", "ai"}
TASK_LINE_PREFIXES = ("-", "*", "•")


class TaskProposal(BaseModel):
    """Review-only plaintext task proposal for client-side encryption and commit."""

    title: str
    description: str | None = None
    status: str = "todo"
    assignee_type: str = "user"


class TaskUpdateProposal(BaseModel):
    """Review-only plaintext task update proposal for an existing visible task."""

    task_id: str
    title: str | None = None
    description: str | None = None
    status: str | None = None
    assignee_type: str | None = None


def _clean_optional_text(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def sanitize_task_proposals(raw_proposals: Any, task_id: str) -> list[TaskProposal]:
    """Bound LLM task proposals before sending them to the client for review."""
    if not isinstance(raw_proposals, list):
        return []

    proposals: list[TaskProposal] = []
    for raw in raw_proposals[:MAX_TASK_PROPOSALS]:
        if not isinstance(raw, dict):
            continue
        title = _clean_optional_text(raw.get("title"), max_length=160)
        if not title:
            continue
        status = raw.get("status") if raw.get("status") in TASK_PROPOSAL_STATUSES else "todo"
        assignee_type = raw.get("assignee_type") if raw.get("assignee_type") in TASK_PROPOSAL_ASSIGNEES else "user"
        proposals.append(
            TaskProposal(
                title=title,
                description=_clean_optional_text(raw.get("description"), max_length=2000),
                status=status,
                assignee_type=assignee_type,
            )
        )

    if len(proposals) != len(raw_proposals[:MAX_TASK_PROPOSALS]):
        logger.info("[Task ID: %s] [PostProcessor] Filtered invalid task proposal(s)", task_id)
    return proposals


def sanitize_task_update_proposals(raw_updates: Any, task_id: str) -> list[TaskUpdateProposal]:
    """Bound task update proposals; the client validates visibility before commit."""
    if not isinstance(raw_updates, list):
        return []

    updates: list[TaskUpdateProposal] = []
    for raw in raw_updates[:MAX_TASK_PROPOSALS]:
        if not isinstance(raw, dict):
            continue
        visible_task_id = _clean_optional_text(raw.get("task_id"), max_length=120)
        if not visible_task_id:
            continue
        status = raw.get("status") if raw.get("status") in TASK_PROPOSAL_STATUSES else None
        assignee_type = raw.get("assignee_type") if raw.get("assignee_type") in TASK_PROPOSAL_ASSIGNEES else None
        update = TaskUpdateProposal(
            task_id=visible_task_id,
            title=_clean_optional_text(raw.get("title"), max_length=160),
            description=_clean_optional_text(raw.get("description"), max_length=2000),
            status=status,
            assignee_type=assignee_type,
        )
        if update.title or update.description or update.status or update.assignee_type:
            updates.append(update)

    if len(updates) != len(raw_updates[:MAX_TASK_PROPOSALS]):
        logger.info("[Task ID: %s] [PostProcessor] Filtered invalid task update proposal(s)", task_id)
    return updates


def extract_review_task_proposals(text: str, task_id: str = "user-task-extract") -> list[TaskProposal]:
    """Create bounded review-only task proposals from transient user text.

    The durable task API remains encrypted. This helper intentionally returns
    plaintext only to the current request so the client can review/edit before
    committing encrypted task records.
    """
    cleaned_text = text.strip()
    if not cleaned_text:
        return []

    raw_proposals: list[dict[str, str]] = []
    for raw_line in cleaned_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for prefix in TASK_LINE_PREFIXES:
            if line.startswith(prefix):
                line = line[len(prefix) :].strip()
                break
        if line:
            raw_proposals.append({"title": line, "description": cleaned_text})
        if len(raw_proposals) >= MAX_TASK_PROPOSALS:
            break

    if not raw_proposals:
        raw_proposals.append({"title": cleaned_text[:160], "description": cleaned_text})

    return sanitize_task_proposals(raw_proposals, task_id)
