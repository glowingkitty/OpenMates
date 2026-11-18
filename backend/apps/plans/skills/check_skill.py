"""Check skill: validates an assistant-defined reusable Check and returns an embed-ready result.

Source validation reuses the Check service rules; nothing is stored here.
"""

# test-file: backend/tests/test_plans_spec_check_skills.py

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.services.user_check_service import CheckError, validate_revision_sources

logger = logging.getLogger(__name__)

CHECK_ERROR_MESSAGES = {
    "CHECK_SOURCE_INVALID": "Each source needs a unique source_binding_id, a valid source_kind and a role of required or supporting",
    "CHECK_REQUIRED_SOURCE_MISSING": "A Check needs at least one required source",
    "CHECK_DETERMINISTIC_SOURCE_REQUIRED": "requires_deterministic needs at least one required deterministic source (e2e, unit, integration, static_analysis or deterministic_audit)",
}
SOURCE_OPTIONAL_FIELDS = ("label", "test_target", "question", "threshold", "instruction")


class CheckValidationError(ValueError):
    """A user-visible validation message for a defined Check."""


class CheckResponse(BaseModel):
    success: bool = Field(default=False)
    type: str = "check"
    title: str = ""
    description: str = ""
    covered_claims: list[str] = Field(default_factory=list)
    requires_deterministic: bool = False
    sources: list[dict[str, Any]] = Field(default_factory=list)
    chat_id: str | None = None
    error: str | None = None


def _normalize_sources(sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in sources or []:
        source = {k: raw[k] for k in ("source_binding_id", "source_kind", "role") if k in raw}
        for key in SOURCE_OPTIONAL_FIELDS:
            if raw.get(key) not in (None, ""):
                source[key] = raw[key]
        result.append(source)
    return result


class CheckSkill(BaseSkill):
    """Return a validated Check definition as a chat embed."""

    async def execute(
        self,
        title: str,
        description: str | None = None,
        covered_claims: list[str] | None = None,
        requires_deterministic: bool = False,
        sources: list[dict[str, Any]] | None = None,
        chat_id: str | None = None,
        **kwargs: Any,
    ) -> CheckResponse:
        try:
            check_title = str(title or "").strip()
            if not check_title:
                raise CheckValidationError("Check needs a title")
            normalized = _normalize_sources(sources)
            try:
                validate_revision_sources(normalized, bool(requires_deterministic))
            except CheckError as exc:
                raise CheckValidationError(CHECK_ERROR_MESSAGES.get(exc.code, exc.code)) from exc
            for source in normalized:
                binding = source["source_binding_id"]
                if source["source_kind"] == "ai_evaluation" and not str(source.get("question") or "").strip():
                    raise CheckValidationError(f"AI evaluation source {binding} needs a question")
                if source["source_kind"] == "human_confirmation" and not str(source.get("instruction") or "").strip():
                    raise CheckValidationError(f"Human confirmation source {binding} needs an instruction")
            return CheckResponse(
                success=True,
                title=check_title,
                description=str(description or "").strip(),
                covered_claims=[str(c).strip() for c in (covered_claims or []) if str(c).strip()],
                requires_deterministic=bool(requires_deterministic),
                sources=normalized,
                chat_id=chat_id,
            )
        except CheckValidationError as exc:
            return CheckResponse(success=False, error=str(exc))
