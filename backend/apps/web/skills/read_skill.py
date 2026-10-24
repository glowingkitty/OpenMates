# backend/apps/web/skills/read_skill.py
#
# Web read skill implementation.
# Preserves the web reading contract while no supported reader is configured.
#
# This skill supports multiple URLs in a single request,
# processing them in parallel (up to 5 parallel requests).

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager


class WebReadRequestItem(BaseModel):
    """A single web page read request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    url: str = Field(description="URL of the web page to read and extract content from.")
    formats: Optional[List[str]] = Field(
        default=None,
        description="Output formats to return (e.g. ['markdown', 'html']). Defaults to ['markdown'].",
    )
    only_main_content: Optional[bool] = Field(
        default=None,
        description="If true, extract only the main article content (no nav/footer/ads). Default: true.",
    )
    max_age: Optional[int] = Field(
        default=None,
        description="Max cache age in seconds. Uses cached version if available within this age.",
    )
    timeout: Optional[int] = Field(
        default=None,
        description="Request timeout in milliseconds.",
    )


class ReadRequest(BaseModel):
    """
    Request model for web read skill.
    Always uses 'requests' array format for consistency and parallel processing support.
    Each request specifies its own parameters with defaults defined in the tool_schema.
    """
    requests: List[WebReadRequestItem] = Field(
        ...,
        description="Array of web read request objects. Each object must contain 'url' and can include optional parameters (formats, only_main_content, max_age, timeout)."
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
        description="The configured supported content reader, if available."
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on read results"
    )
    error: Optional[str] = Field(None, description="Error message if read failed")
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
    """Keep the read contract available when no supported reader is configured."""

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs: Any,
    ) -> ReadResponse:
        """Return a visible capability gap without making outbound requests."""
        return ReadResponse(results=[], provider="", error="No supported content reader is configured.")
