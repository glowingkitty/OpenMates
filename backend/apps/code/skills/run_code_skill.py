# backend/apps/code/skills/run_code_skill.py
#
# Metadata skill for Code Run.
# Browser-triggered executions use /v1/code/run so the current code embed can
# open an inline terminal immediately. This skill definition makes Code Run
# discoverable in the Code app catalog with the same pricing as the route.

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill


class RunCodeRequest(BaseModel):
    chat_id: str = Field(description="Chat ID containing the code embeds to run.")
    target_embed_id: str = Field(description="Code embed ID to execute as the entrypoint.")
    enable_internet: bool = Field(default=True, description="Allow outbound internet access from the E2B sandbox.")


class RunCodeResponse(BaseModel):
    execution_id: str | None = None
    status: str = "requires_web_app_route"
    error: str | None = None


class RunCodeSkill(BaseSkill):
    """Catalog entry for running code embeds in an E2B sandbox."""

    async def execute(self, request: RunCodeRequest, **kwargs) -> RunCodeResponse:
        del request, kwargs
        return RunCodeResponse(
            error="Code Run is started from the web app code fullscreen via /v1/code/run."
        )
