# backend/apps/openmates/skills/search_docs_skill.py
#
# Search Docs skill — full-text search across OpenMates documentation.
# Fetches the docs search index from the public site and performs
# keyword matching across titles and content.
#
# Architecture: docs/architecture/docs-web-app.md

import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

# Base URL for the OpenMates docs site
DOCS_BASE_URL = os.getenv("DOCS_BASE_URL", "https://openmates.org")

# Maximum number of search results
MAX_RESULTS = 10

# Cache TTL for the search index (seconds) — re-fetched every 10 minutes
SEARCH_INDEX_CACHE_TTL = 600

# Module-level cache for the search index
_cached_search_index: Optional[List[Dict[str, Any]]] = None
_cache_timestamp: float = 0


class SearchDocsRequest(BaseModel):
    """Request model for the search_docs skill (REST API documentation)."""

    query: str = Field(
        ...,
        description="Search terms to find in OpenMates documentation",
    )


class SearchDocsResult(BaseModel):
    """A single search result."""

    title: str = Field(description="Document title")
    slug: str = Field(description="Document slug path")
    url: str = Field(description="Full URL to the document")
    snippet: str = Field(description="Text snippet showing the match context")
    relevance: float = Field(description="Relevance score (0-1)")


class SearchDocsResponse(BaseModel):
    """Response model for the search_docs skill."""

    results: List[SearchDocsResult] = Field(
        default_factory=list,
        description="Matching documentation pages",
    )
    query: str = Field(default="", description="The search query that was executed")
    total_results: int = Field(default=0, description="Number of matching results")
    error: Optional[str] = Field(None, description="Error message if search failed")


class SearchDocsSkill(BaseSkill):
    """
    Full-text search across OpenMates documentation.

    Searches document titles and content for the given query terms,
    returning the most relevant matches with snippets.
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
        query: str,
        user_id: Optional[str] = None,
        cache_service=None,
        **kwargs,
    ) -> SearchDocsResponse:
        """
        Search across OpenMates documentation.

        Args:
            query: Search terms.
            user_id: Ignored — docs are public.
            cache_service: Optional cache service for index caching.

        Returns:
            SearchDocsResponse with matching results.
        """
        try:
            query = query.strip()
            if not query:
                return SearchDocsResponse(
                    query=query,
                    error="Search query is empty.",
                )

            # Get or refresh the search index
            search_index = await self._get_search_index(cache_service)
            if search_index is None:
                return SearchDocsResponse(
                    query=query,
                    error="Could not load the documentation search index.",
                )

            # Perform search
            words = query.lower().split()
            scored_results: List[tuple] = []

            for entry in search_index:
                title_lower = entry.get("title", "").lower()
                content_lower = entry.get("content", "").lower()

                # Calculate relevance score
                score = 0.0
                matched_words = 0

                for word in words:
                    title_count = title_lower.count(word)
                    content_count = content_lower.count(word)

                    if title_count > 0:
                        score += 3.0 * title_count  # Title matches weighted 3x
                        matched_words += 1
                    if content_count > 0:
                        score += 1.0 * min(content_count, 5)  # Cap content matches
                        matched_words += 1

                # Exact phrase match bonus
                if query.lower() in title_lower:
                    score += 10.0
                if query.lower() in content_lower:
                    score += 2.0

                # Only include if at least one word matched
                if matched_words > 0:
                    # Normalize score to 0-1 range
                    relevance = min(score / (len(words) * 10), 1.0)
                    snippet = _extract_snippet(entry.get("content", ""), words)
                    scored_results.append((relevance, entry, snippet))

            # Sort by relevance (descending) and take top results
            scored_results.sort(key=lambda x: x[0], reverse=True)
            top_results = scored_results[:MAX_RESULTS]

            results = [
                SearchDocsResult(
                    title=entry.get("title", ""),
                    slug=entry.get("slug", ""),
                    url=f"{DOCS_BASE_URL}/docs/{entry.get('slug', '')}",
                    snippet=snippet,
                    relevance=round(relevance, 3),
                )
                for relevance, entry, snippet in top_results
            ]

            return SearchDocsResponse(
                results=results,
                query=query,
                total_results=len(results),
            )

        except Exception as e:
            logger.error(f"SearchDocsSkill: Unexpected error: {e}", exc_info=True)
            return SearchDocsResponse(
                query=query,
                error=f"An unexpected error occurred: {str(e)}",
            )

    async def _get_search_index(
        self, cache_service=None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get the docs search index, using cache when available.

        The search index is fetched from the docs site's generated JSON data.
        Falls back to fetching individual pages if the index endpoint is not available.
        """
        import json
        import time

        global _cached_search_index, _cache_timestamp

        # Check module-level cache
        if _cached_search_index and (time.time() - _cache_timestamp) < SEARCH_INDEX_CACHE_TTL:
            return _cached_search_index

        # Check Redis cache if available
        cache_key = "openmates:docs:search_index"
        if cache_service:
            try:
                cached = await cache_service.get(cache_key)
                if cached:
                    _cached_search_index = json.loads(cached)
                    _cache_timestamp = time.time()
                    return _cached_search_index
            except Exception as e:
                logger.debug(f"SearchDocsSkill: Cache read failed: {e}")

        # Fetch the sitemap to discover all doc pages, then build index
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Try fetching the sitemap for all doc URLs
                sitemap_resp = await client.get(
                    f"{DOCS_BASE_URL}/sitemap.xml", follow_redirects=True
                )

                if sitemap_resp.status_code == 200:
                    # Extract docs URLs from sitemap
                    doc_urls = re.findall(
                        r"<loc>(https?://[^<]+/docs/[^<]+)</loc>", sitemap_resp.text
                    )

                    search_index = []
                    for doc_url in doc_urls:
                        slug_match = re.match(r"https?://[^/]+/docs/(.+?)/?$", doc_url)
                        if not slug_match:
                            continue
                        slug = slug_match.group(1)

                        # Fetch each page to build the index
                        try:
                            page_resp = await client.get(doc_url, follow_redirects=True)
                            if page_resp.status_code != 200:
                                continue

                            html = page_resp.text
                            title_match = re.search(r"<title>(.+?)\s*\|", html)
                            title = title_match.group(1).strip() if title_match else slug

                            # Extract text content
                            content = _extract_plain_text(html)
                            if content:
                                search_index.append(
                                    {
                                        "title": title,
                                        "slug": slug,
                                        "content": content[:5000],  # Limit per-doc content
                                    }
                                )
                        except Exception as e:
                            logger.debug(
                                f"SearchDocsSkill: Failed to fetch {doc_url}: {e}"
                            )
                            continue

                    if search_index:
                        # Cache the index
                        _cached_search_index = search_index
                        _cache_timestamp = time.time()

                        if cache_service:
                            try:
                                await cache_service.set(
                                    cache_key,
                                    json.dumps(search_index),
                                    ttl=SEARCH_INDEX_CACHE_TTL,
                                )
                            except Exception as e:
                                logger.debug(
                                    f"SearchDocsSkill: Cache write failed: {e}"
                                )

                        return search_index

        except Exception as e:
            logger.error(f"SearchDocsSkill: Failed to build search index: {e}", exc_info=True)

        return _cached_search_index  # Return stale cache if available


def _extract_plain_text(html: str) -> str:
    """Extract plain text from HTML, stripping all tags."""
    # Remove script and style
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)

    # Decode entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    # Clean whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_snippet(content: str, words: List[str], max_length: int = 200) -> str:
    """Extract a text snippet around the first match of any search word."""
    content_lower = content.lower()

    # Find the earliest match position
    earliest_pos = len(content)
    for word in words:
        pos = content_lower.find(word)
        if 0 <= pos < earliest_pos:
            earliest_pos = pos

    if earliest_pos >= len(content):
        # No match in content — return the beginning
        return content[:max_length] + ("..." if len(content) > max_length else "")

    # Extract context around the match
    start = max(0, earliest_pos - 60)
    end = min(len(content), earliest_pos + max_length - 60)

    snippet = content[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."

    return snippet
