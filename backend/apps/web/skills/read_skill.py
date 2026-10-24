"""Read public pages through the direct, crawler-aware reader boundary."""

import asyncio
import logging
from typing import Dict, Any, List, Literal, Optional

from pydantic import ValidationError
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.public_web_reader import PublicWebReadError, read_public_web_page
from backend.shared.python_utils.url_normalizer import sanitize_url_remove_fragment
from backend.shared.python_utils.app_skill_output_safety import (
    APP_SKILL_SURFACE_REST,
    AppSkillOutputSafetyContext,
    is_central_app_skill_dispatch,
    sanitize_app_skill_output,
)

logger = logging.getLogger(__name__)
READ_CREDITS_PER_PAGE = 20
MAX_READ_REQUESTS = 5
DEFAULT_READ_TIMEOUT_MS = 20_000
MAX_READ_TIMEOUT_MS = 30_000
READ_BATCH_TIMEOUT_SECONDS = 30.0



class WebReadRequestItem(BaseModel):
    """A single web page read request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    url: str = Field(description="URL of the web page to read and extract content from.")
    formats: Optional[List[Literal["markdown"]]] = Field(
        default=None, min_length=1, max_length=1,
        description="Only markdown is supported; omitted formats default to markdown.",
    )
    only_main_content: Optional[bool] = Field(
        default=None,
        description="If true, extract only the main article content (no nav/footer/ads). Default: true.",
    )
    max_age: Optional[int] = Field(
        default=None, ge=0,
        description="Legacy compatibility field; ignored. Every source read is fresh. Saved full-text embeds are unaffected.",
    )
    timeout: Optional[int] = Field(
        default=None, ge=1000, le=MAX_READ_TIMEOUT_MS,
        description="Complete source read timeout in milliseconds (1000-30000; default 20000).",
    )


class ReadRequest(BaseModel):
    """
    Request model for web read skill.
    Always uses 'requests' array format for consistency and parallel processing support.
    Each request specifies its own parameters with defaults defined in the tool_schema.
    """
    requests: List[WebReadRequestItem] = Field(
        ..., min_length=1, max_length=MAX_READ_REQUESTS,
        description="Array of up to five web read request objects. Each object must contain 'url' and can include optional parameters (formats, only_main_content, max_age, timeout)."
    )


class ReadResult(BaseModel):
    """Individual read result model."""
    url: str
    title: Optional[str] = None
    markdown: Optional[str] = None
    # HTML removed: not needed for LLM and significantly increases payload size
    # html: Optional[str] = None
    # Summary removed: not needed and reduces payload size
    # summary: Optional[str] = None
    # Metadata removed: specific fields moved to root level
    # metadata: Optional[Dict[str, Any]] = None
    # Fields moved from metadata to root level for easier access
    language: Optional[str] = None
    favicon: Optional[str] = None
    og_image: Optional[str] = None
    og_sitename: Optional[str] = None
    error: Optional[str] = None
    http_status: Optional[int] = None
    source_url: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    read_status: Optional[str] = None


class ReadResponse(BaseModel):
    """Response model for web read skill."""
    # Results are grouped by request id - each entry contains 'id' and 'results' array
    # This structure allows clients to match responses to original requests without redundant data
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of request results. Each entry contains 'id' (matching request id) and 'results' array with actual read results for that request."
    )
    provider: str = Field(
        default="",
        description="Reader implementation; no external content-reader provider is involved."
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on read results"
    )
    error: Optional[str] = Field(None, description="Error message when no page could be read")
    warnings: List[str] = Field(default_factory=list, description="Visible errors for unsuccessful sibling page reads.")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "favicon",  # Favicon URL not needed for LLM inference
            "og_image",  # OG image URL not needed for LLM inference
            "og_sitename",  # OG site name not needed for LLM inference
        ],
        description="List of field paths (supports dot notation) that should be excluded from LLM inference to reduce token usage. These fields are preserved in chat history for UI rendering but filtered out before sending to LLM. Note: Metadata object is removed - specific fields are moved to root level."
    )
    # preview_data removed: redundant metadata that can be derived from results
    # preview_data: Optional[Dict[str, Any]] = Field(
    #     None,
    #     description="Preview data for frontend rendering. This is skill-specific metadata for UI display (e.g., url, result_count, etc.). Does NOT include actual results - those are in 'results' field."
    # )


class ReadSkill(BaseSkill):
    """Read allowed public pages directly, preserving complete extracted markdown."""

    async def _process_single_read_request(
        self, req: Dict[str, Any], request_id: Any,
    ) -> tuple[Any, List[Dict[str, Any]], Optional[str], Optional[str], Optional[int]]:
        """Validate one request and return normalized content or a typed safe error."""
        try:
            item = WebReadRequestItem.model_validate(req)
        except ValidationError as exc:
            fields = ", ".join(dict.fromkeys(str(error["loc"][0]) for error in exc.errors()))
            return request_id, [], f"Invalid read request fields: {fields}", "invalid_request", None
        read_url = sanitize_url_remove_fragment(item.url)
        try:
            page = await read_public_web_page(
                read_url,
                only_main_content=True if item.only_main_content is None else item.only_main_content,
                timeout_ms=item.timeout or DEFAULT_READ_TIMEOUT_MS,
            )
            markdown = page.get("markdown")
            if not isinstance(markdown, str) or not markdown.strip():
                return request_id, [], "The page has no readable text.", "empty", page.get("http_status")
            result = ReadResult.model_validate({
                **{key: page.get(key) for key in (
                    "title", "language", "favicon", "og_image", "og_sitename",
                    "http_status", "read_status",
                )},
                "url": read_url,
                "source_url": page.get("source_url") or page.get("url") or read_url,
                "markdown": markdown,
                "warnings": page.get("warnings") or [],
            }).model_dump(exclude_none=True)
            result.update(type="read_result", hash=self._generate_result_hash(read_url))
            return request_id, [result], None, None, None
        except PublicWebReadError as exc:
            return request_id, [], exc.message, exc.code, exc.http_status
        except asyncio.TimeoutError:
            return request_id, [], "The public page read timed out.", "timeout", None
        except Exception:
            logger.exception("Public page reader failed unexpectedly")
            return request_id, [], "The public page could not be read.", "read_failed", None

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs: Any,
    ) -> ReadResponse:
        """Read at most five pages within a shared thirty-second source deadline."""
        if not isinstance(requests, list) or not 1 <= len(requests) <= MAX_READ_REQUESTS:
            return ReadResponse(error="Provide between one and five page read requests.")
        validated = []
        request_ids: set[Any] = set()
        for index, request in enumerate(requests):
            if hasattr(request, "model_dump"):
                req = request.model_dump()
            elif isinstance(request, dict):
                req = dict(request)
            else:
                return ReadResponse(error="Each page read request must be an object.")
            _, error = self._validate_and_normalize_request_id(
                req=req, request_index=index, total_requests=len(requests),
                request_ids=request_ids, logger=logger,
            )
            if error:
                return ReadResponse(error=error)
            validated.append(req)
        tasks = [asyncio.create_task(self._process_single_read_request(req, req["id"]))
                 for req in validated]
        try:
            done, pending = await asyncio.wait(tasks, timeout=READ_BATCH_TIMEOUT_SECONDS)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            groups = []
            errors = []
            for req, task in zip(validated, tasks):
                if task in done:
                    identity, results, message, code, status = task.result()
                else:
                    identity, results, message, code, status = (
                        req["id"], [], "The public page read deadline was exceeded.", "timeout", None,
                    )
                group = {"id": identity, "results": results,
                         "usage": {"credits_charged": READ_CREDITS_PER_PAGE if results and not message else 0}}
                if message:
                    group.update(error=message, read_status=code, error_code=code)
                    if status is not None:
                        group["http_status"] = status
                    errors.append(message)
                groups.append(group)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        response = self._build_response_with_errors(
            response_class=ReadResponse, grouped_results=groups,
            errors=errors if len(errors) == len(groups) else [], warnings=errors,
            provider="OpenMates public web reader",
            suggestions=["Summarize this page", "Extract key points", "Read related pages"],
            logger=logger,
        )
        if is_central_app_skill_dispatch():
            return response
        sanitized = await sanitize_app_skill_output(
            response.model_dump(mode="json"),
            AppSkillOutputSafetyContext(
                app_id=self.app_id, skill_id=self.skill_id, surface=APP_SKILL_SURFACE_REST,
                request_body=kwargs, external_data=True, secrets_manager=secrets_manager,
                cache_service=kwargs.get("cache_service"),
                log_prefix="[WebRead direct execute] ",
            ),
        )
        return ReadResponse.model_validate(sanitized)
