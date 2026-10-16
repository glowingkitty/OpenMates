"""Fresh accepted Plan reference from a client-decrypted memory-only snapshot.

No lifecycle writes, private ciphertext decryption, fallback or goal replacement.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ACTIVE_PLAN_STATUSES = frozenset({'active', 'executing', 'running_checks', 'blocked'})
OPEN_TASK_STATUSES = frozenset({'todo', 'backlog', 'in_progress', 'blocked', 'pending'})


class AcceptedPlanSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    plan_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)
    approved_revision_id: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=4000, repr=False)
    linked_task_id: str | None = Field(default=None, min_length=1, max_length=100)


def bounded_accepted_plan_snapshot(value: Any) -> dict | None:
    """Malformed optional input is omitted without an input-bearing error log."""
    try:
        snapshot = AcceptedPlanSnapshot.model_validate(value)
        if not snapshot.summary.strip():
            return None
        return snapshot.model_dump(exclude_none=True)
    except Exception:
        return None


def _scope(owner_id: str, team_id: str | None) -> dict:
    if team_id:
        return {'filter[hashed_team_id][_eq]': hashlib.sha256(team_id.encode()).hexdigest()}
    return {'filter[hashed_user_id][_eq]': hashlib.sha256(owner_id.encode()).hexdigest(),
            'filter[hashed_team_id][_null]': True}


def _owned(row: dict, owner_id: str, team_id: str | None) -> bool:
    if team_id:
        return row.get('hashed_team_id') == hashlib.sha256(team_id.encode()).hexdigest()
    return row.get('hashed_user_id') == hashlib.sha256(owner_id.encode()).hexdigest() and not row.get('hashed_team_id')


async def validate_accepted_plan_context(request: Any, directus: Any) -> str | None:
    """Require current durable approval, exact version and actual chat linkage."""
    if any(getattr(request, flag, False) for flag in ('is_external', 'is_incognito', 'is_anonymous')):
        return None
    value = bounded_accepted_plan_snapshot(getattr(request, 'accepted_plan_context', None))
    owner_id, chat_id = getattr(request, 'user_id', None), getattr(request, 'chat_id', None)
    if value is None or not owner_id or not chat_id or directus is None:
        return None
    snapshot = AcceptedPlanSnapshot.model_validate(value)
    team_id = getattr(request, 'team_id', None)
    scope = _scope(owner_id, team_id)
    try:
        if team_id:
            await directus.team.require_team_role(team_id, owner_id, {'owner', 'admin', 'member', 'viewer'})
        params = {**scope, 'filter[plan_id][_eq]': snapshot.plan_id,
                  'fields': 'plan_id,hashed_user_id,hashed_team_id,status,primary_chat_id,version,approval_state,submitted_revision_id,approved_revision_id',
                  'limit': 1}
        rows = await directus.get_items('user_plans', params=params, no_cache=True)
        plan = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
        if (not isinstance(plan, dict) or not _owned(plan, owner_id, team_id)
                or plan.get('plan_id') != snapshot.plan_id or type(plan.get('version')) is not int
                or plan['version'] != snapshot.version or plan.get('status') not in ACTIVE_PLAN_STATUSES
                or plan.get('approval_state') != 'approved'
                or plan.get('submitted_revision_id') != snapshot.approved_revision_id
                or plan.get('approved_revision_id') != snapshot.approved_revision_id):
            return None
        if plan.get('primary_chat_id') != chat_id:
            if not snapshot.linked_task_id:
                return None
            tasks = await directus.get_items('user_tasks', params={**scope,
                'filter[task_id][_eq]': snapshot.linked_task_id,
                'fields': 'task_id,hashed_user_id,hashed_team_id,status,primary_chat_id,plan_id', 'limit': 1}, no_cache=True)
            task = tasks[0] if isinstance(tasks, list) and len(tasks) == 1 else None
            if (not isinstance(task, dict) or not _owned(task, owner_id, team_id)
                    or task.get('task_id') != snapshot.linked_task_id or task.get('plan_id') != snapshot.plan_id
                    or task.get('primary_chat_id') != chat_id or task.get('status') not in OPEN_TASK_STATUSES):
                return None
        # Match the canonical durable approved revision predicate. Query existence
        # filters establish a real fingerprint/snapshot without reading ciphertext.
        revisions = await directus.get_items('user_plan_revisions', params={**scope,
            'filter[plan_id][_eq]': snapshot.plan_id, 'filter[revision_id][_eq]': snapshot.approved_revision_id,
            'filter[approval_state][_eq]': 'approved', 'filter[fingerprint][_nnull]': True,
            'filter[fingerprint][_neq]': '', 'filter[encrypted_snapshot][_nnull]': True,
            'filter[encrypted_snapshot][_neq]': '',
            'fields': 'plan_id,revision_id,hashed_user_id,hashed_team_id,approval_state,fingerprint', 'limit': 1}, no_cache=True)
        revision = revisions[0] if isinstance(revisions, list) and len(revisions) == 1 else None
        if (not isinstance(revision, dict) or not _owned(revision, owner_id, team_id)
                or revision.get('plan_id') != snapshot.plan_id or revision.get('revision_id') != snapshot.approved_revision_id
                or revision.get('approval_state') != 'approved' or not revision.get('fingerprint')
                or revision.get('hashed_user_id') != plan.get('hashed_user_id')
                or revision.get('hashed_team_id') != plan.get('hashed_team_id')):
            return None
        # Material edits or approval invalidation during independent metadata I/O
        # must also invalidate this reference before it reaches the drift model.
        refreshed = await directus.get_items('user_plans', params=params, no_cache=True)
        if refreshed != rows:
            return None
        context = {'source': 'authorized_current_approved_plan', 'plan_id': snapshot.plan_id,
                   'version': snapshot.version, 'approved_revision_id': snapshot.approved_revision_id,
                   'summary': snapshot.summary.strip()}
        # Keep the whole metadata frame valid within the direction module's bound.
        while len(encoded := json.dumps(context, ensure_ascii=False, sort_keys=True)) > 4000:
            context['summary'] = context['summary'][:-100]
        return encoded
    except Exception:
        return None
