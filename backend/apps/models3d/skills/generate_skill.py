# backend/apps/models3d/skills/generate_skill.py
#
# 3D generation skill request validation and asynchronous task dispatch.
# It resolves user-facing embed references before enqueuing work, keeping
# plaintext images and provider credentials outside the task broker payload.

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery
from backend.shared.python_utils.image_generation_defaults import (
    ImageGenerationDefault,
    resolve_images_generate_default,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_CREDITS = 25
VIEW_ORDER = ("front", "back", "left", "right")


@dataclass(frozen=True)
class GenerationPlan:
    """Validated, compact generation input safe to send to Celery."""

    input_mode: str
    requires_reference_image: bool
    reference_image_model: str | None
    reference_embed_ids: tuple[str, ...]
    ordered_views: tuple[tuple[str, str], ...]
    estimated_credits: int


def build_generation_plan(
    *,
    prompt: str | None,
    image_embed_refs: Sequence[str],
    image_views: Sequence[Mapping[str, Any]],
    file_path_index: Mapping[str, str],
    reference_image_default: ImageGenerationDefault | None = None,
    model_credits: int = DEFAULT_MODEL_CREDITS,
) -> GenerationPlan:
    """Validate one input mode and replace user-facing image names with embed IDs."""
    normalized_prompt = (prompt or "").strip()
    if len(image_embed_refs) > 1:
        raise ValueError("Single-image generation requires exactly one image reference")
    if len(image_views) > len(VIEW_ORDER):
        raise ValueError("Multi-view generation requires two to four labeled images")
    refs = tuple(reference for reference in image_embed_refs if isinstance(reference, str) and reference)
    views = image_views
    mode_count = int(bool(normalized_prompt)) + int(bool(refs)) + int(bool(views))
    if mode_count != 1:
        raise ValueError("Provide exactly one input mode: text, one image, or multi-view images")

    if normalized_prompt:
        image_default = reference_image_default or resolve_images_generate_default()
        return GenerationPlan(
            input_mode="text",
            requires_reference_image=True,
            reference_embed_ids=(),
            ordered_views=(),
            reference_image_model=image_default.model_reference,
            estimated_credits=image_default.credits + model_credits,
        )

    if refs:
        if len(refs) != 1:
            raise ValueError("Single-image generation requires exactly one image reference")
        embed_id = file_path_index.get(refs[0])
        if not embed_id:
            raise ValueError("Referenced image is not available in this conversation")
        return GenerationPlan(
            input_mode="single_image",
            requires_reference_image=False,
            reference_image_model=None,
            reference_embed_ids=(embed_id,),
            ordered_views=(),
            estimated_credits=model_credits,
        )

    if not 2 <= len(views) <= len(VIEW_ORDER):
        raise ValueError("Multi-view generation requires two to four labeled images")

    resolved_views: dict[str, str] = {}
    for view_input in views:
        if not isinstance(view_input, Mapping):
            raise ValueError("Each multi-view image must be an object")
        view = str(view_input.get("view") or "").lower()
        embed_ref = str(view_input.get("embed_ref") or "")
        if view not in VIEW_ORDER:
            raise ValueError("Multi-view image labels must be front, back, left, or right")
        if view in resolved_views:
            raise ValueError("Multi-view generation contains a duplicate view label")
        embed_id = file_path_index.get(embed_ref)
        if not embed_id:
            raise ValueError("Referenced image is not available in this conversation")
        resolved_views[view] = embed_id

    ordered_views = tuple((view, resolved_views[view]) for view in VIEW_ORDER if view in resolved_views)
    return GenerationPlan(
        input_mode="multi_view",
        requires_reference_image=False,
        reference_image_model=None,
        reference_embed_ids=tuple(embed_id for _, embed_id in ordered_views),
        ordered_views=ordered_views,
        estimated_credits=model_credits,
    )


class GenerateSkill(BaseSkill):
    """Validate models3d requests and enqueue the generation worker."""

    async def execute(
        self,
        prompt: str | None = None,
        image_embed_refs: list[str] | None = None,
        image_views: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in models3d.GenerateSkill")
            return {"error": "3D model generation service temporarily unavailable"}

        try:
            plan = build_generation_plan(
                prompt=prompt,
                image_embed_refs=image_embed_refs or [],
                image_views=image_views or [],
                file_path_index=kwargs.get("file_path_index") or {},
            )
        except ValueError as exc:
            return {"error": str(exc)}

        if plan.input_mode == "text":
            return {
                "error": "Text-to-3D is not available until reference image artifact retention is implemented"
            }

        placeholder_embed_ids = kwargs.get("placeholder_embed_ids") or []
        embed_id = next((value for value in placeholder_embed_ids if value), str(uuid.uuid4()))
        task_args = {
            "prompt": prompt.strip() if prompt else None,
            "input_mode": plan.input_mode,
            "reference_embed_ids": list(plan.reference_embed_ids),
            "ordered_views": [{"view": view, "embed_id": embed_id} for view, embed_id in plan.ordered_views],
            "estimated_credits": plan.estimated_credits,
            "reference_image_model": plan.reference_image_model,
            "user_id": kwargs.get("user_id"),
            "user_vault_key_id": kwargs.get("user_vault_key_id"),
            "api_key_hash": kwargs.get("api_key_hash"),
            "device_hash": kwargs.get("device_hash"),
            "chat_id": self._current_chat_id,
            "message_id": self._current_message_id,
            "external_request": kwargs.get("external_request", False),
            "app_id": self.app_id,
            "skill_id": self.skill_id,
            "embed_id": embed_id,
        }
        try:
            task_id = await execute_skill_via_celery(
                app_id=self.app_id,
                skill_id=self.skill_id,
                arguments=task_args,
                celery_producer=self.celery_producer,
            )
        except Exception as exc:
            logger.error("Failed to dispatch models3d generation task: %s", exc, exc_info=True)
            return {"error": "Failed to start 3D model generation"}

        return {
            "task_id": task_id,
            "embed_id": embed_id,
            "status": "processing",
            "estimated_credits": plan.estimated_credits,
        }
