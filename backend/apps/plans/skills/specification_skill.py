"""Specification skill: validates an assistant-drafted Specification and returns an embed-ready result.

Specifications are client-encrypted; nothing is stored here. The client saves
the Specification into the Project when the user approves it.
"""

# test-file: backend/tests/test_plans_spec_check_skills.py

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

FLOW_KINDS = frozenset({"user_flow", "edge_case"})


class SpecificationValidationError(ValueError):
    """A user-visible validation message for a drafted Specification."""


class SpecificationResponse(BaseModel):
    success: bool = Field(default=False)
    type: str = "specification"
    title: str = ""
    summary: str = ""
    outcome: str = ""
    category: str = ""
    scope: dict[str, list[str]] = Field(default_factory=lambda: {"included": [], "excluded": []})
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    flows: list[dict[str, Any]] = Field(default_factory=list)
    chat_id: str | None = None
    error: str | None = None


def _text_list(values: Any, label: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise SpecificationValidationError(f"{label} must be a list")
    return [str(v).strip() for v in values if str(v).strip()]


def _requirements(items: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items or []:
        req_id = str((item or {}).get("id") or "").strip()
        statement = str((item or {}).get("statement") or "").strip()
        if not req_id:
            raise SpecificationValidationError("Every requirement needs an id")
        if req_id in seen:
            raise SpecificationValidationError(f"Duplicate requirement id: {req_id}")
        if not statement:
            raise SpecificationValidationError(f"Requirement {req_id} needs a statement")
        seen.add(req_id)
        entry: dict[str, Any] = {"id": req_id, "statement": statement}
        example = str(item.get("example") or "").strip()
        if example:
            entry["example"] = example
        result.append(entry)
    return result


def _flows(items: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items or []:
        flow_id = str((item or {}).get("id") or "").strip()
        if not flow_id:
            raise SpecificationValidationError("Every flow needs an id")
        if flow_id in seen:
            raise SpecificationValidationError(f"Duplicate flow id: {flow_id}")
        kind = item.get("kind")
        if kind not in FLOW_KINDS:
            raise SpecificationValidationError(f"Flow {flow_id} kind must be user_flow or edge_case")
        title = str(item.get("title") or "").strip()
        if not title:
            raise SpecificationValidationError(f"Flow {flow_id} needs a title")
        steps = _text_list(item.get("steps"), f"Flow {flow_id} steps")
        seen.add(flow_id)
        result.append({"id": flow_id, "title": title, "kind": kind, "steps": steps})
    return result


class SpecificationSkill(BaseSkill):
    """Return a validated Specification draft as a chat embed."""

    async def execute(
        self,
        title: str,
        summary: str,
        outcome: str | None = None,
        category: str | None = None,
        scope_included: list[str] | None = None,
        scope_excluded: list[str] | None = None,
        requirements: list[dict[str, Any]] | None = None,
        flows: list[dict[str, Any]] | None = None,
        chat_id: str | None = None,
        **kwargs: Any,
    ) -> SpecificationResponse:
        try:
            spec_title = str(title or "").strip()
            spec_summary = str(summary or "").strip()
            if not spec_title:
                raise SpecificationValidationError("Specification needs a title")
            if not spec_summary:
                raise SpecificationValidationError("Specification needs a summary")
            return SpecificationResponse(
                success=True,
                title=spec_title,
                summary=spec_summary,
                outcome=str(outcome or "").strip(),
                category=str(category or "").strip(),
                scope={
                    "included": _text_list(scope_included, "scope_included"),
                    "excluded": _text_list(scope_excluded, "scope_excluded"),
                },
                requirements=_requirements(requirements),
                flows=_flows(flows),
                chat_id=chat_id,
            )
        except SpecificationValidationError as exc:
            return SpecificationResponse(success=False, error=str(exc))
