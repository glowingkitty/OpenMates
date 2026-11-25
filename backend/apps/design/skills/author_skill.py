"""Create or revise a typed Design using the dedicated visual author."""

from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.apps.base_skill import BaseSkill
from backend.apps.design.source import DesignSource
from backend.apps.design.scene_author import author_design
from backend.shared.python_utils.internal_llm_policy import policy_from_skill_kwargs
from backend.shared.python_utils.metered_author_billing import author_and_sandbox_credits


logger = logging.getLogger(__name__)

Requirement = Annotated[str, Field(min_length=1, max_length=300)]


class AuthorDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: Annotated[str, Field(min_length=1, max_length=2000)]
    requirements: list[Requirement] = Field(default_factory=list, max_length=5)
    exact_copy: list[Requirement] = Field(default_factory=list, max_length=8)
    source: DesignSource | None = None


class AuthorDesignResponse(BaseModel):
    success: bool = False
    scene_json: str | None = None
    source_embed_id: str | None = None
    base_version: int | None = None
    model_id: str | None = None
    attempts: int = 0
    elapsed_ms: int = 0
    usage: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    credits_charged: int = 0


class AuthorSkill(BaseSkill):
    """Return a validated scene to the authenticated caller for encrypted client persistence."""

    async def execute(
        self, brief: str, requirements: list[str] | None = None, exact_copy: list[str] | None = None,
        revise: bool = False, design_source: DesignSource | None = None,
        user_id: str | None = None, chat_id: str | None = None, team_id: str | None = None,
        message_id: str | None = None,
        skill_task_id: str | None = None, secrets_manager: Any = None,
        external_request: bool = False, design_author_allowed: bool = False, **context: Any,
    ) -> AuthorDesignResponse:
        if not design_author_allowed or not user_id or not chat_id or team_id or external_request:
            return AuthorDesignResponse(error="design_personal_chat_required")
        if revise and design_source is None:
            return AuthorDesignResponse(error="design_current_attachment_required")
        try:
            request = AuthorDesignRequest(brief=brief.strip(), requirements=requirements or [],
                                          exact_copy=exact_copy or [], source=design_source)
        except ValidationError:
            return AuthorDesignResponse(error="design_request_invalid")
        result = await author_design(
            task_id=skill_task_id or message_id or "design_author", brief=request.brief,
            requirements=tuple(request.requirements), exact_copy=tuple(request.exact_copy),
            source=request.source.scene if request.source else None,
            secrets_manager=secrets_manager, policy=policy_from_skill_kwargs(context),
        )
        credits = 0
        if result.scene is not None:
            credits, _ = await author_and_sandbox_credits(
                usage=result.usage, sandbox_seconds=(), label="design.author",
                sandbox_credits_per_started_minute=0,
            )
        logger.info(
            "Design author result model=%s accepted=%s attempts=%d elapsed_ms=%d credits=%d failure=%s",
            result.model_id, result.scene is not None, result.attempts, result.elapsed_ms, credits, result.error,
        )
        return AuthorDesignResponse(
            credits_charged=credits,
            success=result.scene is not None,
            scene_json=result.scene.wire_json() if result.scene else None,
            source_embed_id=str(request.source.embed_id) if request.source else None,
            base_version=request.source.base_version if request.source else None,
            model_id=result.model_id, attempts=result.attempts, elapsed_ms=result.elapsed_ms,
            usage=[asdict(meter) for meter in result.usage], error=result.error,
        )
