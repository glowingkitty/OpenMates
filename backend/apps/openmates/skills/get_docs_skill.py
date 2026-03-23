# backend/apps/openmates/skills/get_docs_skill.py
#
# Get Docs skill — retrieves a specific OpenMates documentation page by URL or slug.
# Fetches content from the public docs site (openmates.org/docs/) to ensure
# the data is always up-to-date with the deployed version.
#
# Architecture: docs/architecture/docs-web-app.md

import logging
import os
import re
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

# Base URL for the OpenMates docs site — configurable for self-hosted instances
DOCS_BASE_URL = os.getenv("DOCS_BASE_URL", "https://openmates.org")

# Maximum content length to return (characters) — prevents excessive token usage
MAX_CONTENT_LENGTH = 50_000


class GetDocsRequest(BaseModel):
    """Request model for the get_docs skill (REST API documentation)."""

    url: str = Field(
        ...,
        description="An openmates.org/docs URL or a docs slug (e.g., 'architecture/chats' "
        "or 'https://openmates.org/docs/architecture/chats')",
    )


class GetDocsResponse(BaseModel):
    """Response model for the get_docs skill."""

    title: Optional[str] = Field(None, description="Document title")
    slug: str = Field(default="", description="Document slug path")
    content: Optional[str] = Field(None, description="Full markdown content of the document")
    word_count: int = Field(default=0, description="Word count of the document")
    url: str = Field(default="", description="Full URL to the document")
    error: Optional[str] = Field(None, description="Error message if retrieval failed")


def _extract_slug(url_or_slug: str) -> str:
    """Extract the docs slug from a URL or slug string."""
    url_or_slug = url_or_slug.strip()

    # Handle full URLs: https://openmates.org/docs/architecture/chats
    match = re.match(r"https?://[^/]+/docs/(.+?)/?$", url_or_slug)
    if match:
        return match.group(1)

    # Handle /docs/... paths
    if url_or_slug.startswith("/docs/"):
        return url_or_slug[6:].rstrip("/")

    # Handle docs/... paths
    if url_or_slug.startswith("docs/"):
        return url_or_slug[5:].rstrip("/")

    # Assume it's already a slug
    return url_or_slug.strip("/")


class GetDocsSkill(BaseSkill):
    """
    Retrieves an OpenMates documentation page by URL or slug.

    Fetches the page content from the public docs site and returns the
    markdown content, title, and metadata. Automatically triggered when
    the AI detects an openmates.org/docs URL in the conversation.
    """

    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "production",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
        )

    async def execute(
        self,
        url: str,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> GetDocsResponse:
        """
        Retrieve a documentation page.

        Args:
            url: An openmates.org/docs URL or slug path.
            user_id: Ignored — docs are public.

        Returns:
            GetDocsResponse with the document content and metadata.
        """
        try:
            slug = _extract_slug(url)
            if not slug:
                return GetDocsResponse(
                    slug="",
                    error="No document slug could be extracted from the provided URL.",
                )

            full_url = f"{DOCS_BASE_URL}/docs/{slug}"
            logger.info(f"GetDocsSkill: Fetching docs page: {full_url}")

            # Fetch the page HTML from the public docs site
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(full_url, follow_redirects=True)

            if response.status_code == 404:
                return GetDocsResponse(
                    slug=slug,
                    url=full_url,
                    error=f"Documentation page not found: /docs/{slug}",
                )

            if response.status_code != 200:
                return GetDocsResponse(
                    slug=slug,
                    url=full_url,
                    error=f"Failed to fetch page (HTTP {response.status_code})",
                )

            html = response.text

            # Extract title from <title> tag
            title_match = re.search(r"<title>(.+?)\s*\|", html)
            title = title_match.group(1).strip() if title_match else slug.split("/")[-1]

            # Extract the main content — docs pages render markdown as article content
            # Look for the docs message container content
            content = _extract_text_content(html)

            if not content or len(content.strip()) < 50:
                return GetDocsResponse(
                    slug=slug,
                    url=full_url,
                    title=title,
                    error="Page was found but content could not be extracted.",
                )

            # Truncate if too long
            if len(content) > MAX_CONTENT_LENGTH:
                content = content[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated]"

            word_count = len(content.split())

            return GetDocsResponse(
                title=title,
                slug=slug,
                content=content,
                word_count=word_count,
                url=full_url,
            )

        except httpx.TimeoutException:
            logger.error(f"GetDocsSkill: Timeout fetching docs page: {url}")
            return GetDocsResponse(
                slug=_extract_slug(url),
                error="Request timed out while fetching the documentation page.",
            )
        except Exception as e:
            logger.error(f"GetDocsSkill: Unexpected error: {e}", exc_info=True)
            return GetDocsResponse(
                slug=_extract_slug(url),
                error=f"An unexpected error occurred: {str(e)}",
            )


def _extract_text_content(html: str) -> str:
    """
    Extract readable text content from the docs page HTML.

    Strips HTML tags and extracts the main content area text.
    """
    # Remove script and style elements
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

    # Try to find the main content area (docs-page-content or article)
    content_match = re.search(
        r'<div[^>]*class="[^"]*docs-page-content[^"]*"[^>]*>(.*?)</div>\s*(?:</div>)',
        html,
        flags=re.DOTALL,
    )
    if not content_match:
        # Fall back to the body
        content_match = re.search(r"<body[^>]*>(.*?)</body>", html, flags=re.DOTALL)

    if not content_match:
        return ""

    text = content_match.group(1)

    # Convert common HTML to readable text
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</?p[^>]*>", "\n", text)
    text = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>", r"\n## \2\n", text)
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(r"<pre[^>]*>(.*?)</pre>", r"\n```\n\1\n```\n", text, flags=re.DOTALL)
    text = re.sub(r"<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"[\2](\1)", text, flags=re.DOTALL)
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)

    # Remove remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode HTML entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text
