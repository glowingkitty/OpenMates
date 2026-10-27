# backend/apps/social_media/search_collection.py
#
# Shared Social Media search models and provider dispatch.
# Skills and Celery tasks both use this module so platform routing stays
# testable without a worker process. Search defaults to every supported public
# provider unless the caller explicitly requests a platform.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

from typing import Any, Optional
from enum import Enum
from backend.apps.social_media.collection import CommentSort, TimeRange

from pydantic import BaseModel, Field

from backend.shared.providers.bluesky.public import BlueskyPost, search_posts
from backend.shared.providers.mastodon.public import MastodonPost, search_posts as search_mastodon_posts

class SearchSort(str, Enum):
    LATEST = "latest"
    TOP = "top"
    NEW = "new"
    HOT = "hot"
    RELEVANCE = "relevance"
    COMMENTS = "comments"


SUPPORTED_SEARCH_PLATFORMS = {"bluesky", "mastodon"}
DEFAULT_SEARCH_PLATFORMS = ("bluesky", "mastodon")
DEFAULT_REQUEST_LIMIT = 10
MAX_COMMENTS_PER_POST = 5
BLUESKY_PROVIDER_NAME = "Bluesky"
BLUESKY_AUTH_REQUIRED_WARNING = (
    "Bluesky topic search is currently unavailable without configured Bluesky app credentials. "
    "Try fetching a specific Bluesky profile with Get posts, or configure Bluesky credentials for topic search."
)
MASTODON_PROVIDER_NAME = "Mastodon"


class SearchRequestItem(BaseModel):
    """A single social topic search request."""

    id: Optional[Any] = Field(default=None, description="Optional caller-supplied request ID.")
    platform: Optional[str] = Field(
        default=None,
        description="Social platform to search. Omit or use all to search every supported provider.",
    )
    query: str = Field(description="Topic or search query to find posts around.")
    page: Optional[str] = Field(default=None, description="Optional platform instance to search.")
    mastodon_instances: list[str] = Field(
        default_factory=list,
        description="Optional additional Mastodon instances to search. mastodon.social is always searched first.",
    )
    sort: SearchSort = Field(default=SearchSort.LATEST, description="Search sort.")
    time_range: Optional[TimeRange] = Field(
        default=None,
        description="Optional search time range.",
    )
    limit: int = Field(default=DEFAULT_REQUEST_LIMIT, ge=1, le=25, description="Number of posts to fetch.")
    author: Optional[str] = Field(
        default=None,
        description="Optional platform profile/handle filter. Currently only supported by Bluesky.",
    )
    include_comments: bool = Field(default=False, description="Whether to fetch comments for returned posts when supported.")
    comments_limit: int = Field(default=0, ge=0, le=MAX_COMMENTS_PER_POST, description="Comments to fetch per returned post when supported.")
    comments_sort: CommentSort = Field(default=CommentSort.TOP, description="Comment sort.")
    min_score: Optional[int] = Field(default=None, ge=0, description="Minimum post score to include.")
    min_comments: Optional[int] = Field(default=None, ge=0, description="Minimum comment count to include.")
    exclude_stickied: bool = Field(default=True, description="Exclude stickied posts.")
    exclude_nsfw: bool = Field(default=True, description="Exclude NSFW posts.")


class SearchResponseItem(BaseModel):
    """Posts returned for one social topic search request."""

    id: Optional[Any] = None
    platform: str
    query: str
    sort: str
    posts: list[BlueskyPost | MastodonPost] = Field(default_factory=list)
    results: list[BlueskyPost | MastodonPost] = Field(default_factory=list)
    provider: str = Field(default="")
    request_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Response model for the Social Media Search skill."""

    task_id: Optional[str] = None
    embed_id: Optional[str] = None
    task_ids: list[str] = Field(default_factory=list)
    embed_ids: list[str] = Field(default_factory=list)
    status: str = "processing"
    results: list[SearchResponseItem] = Field(default_factory=list)
    provider: str = Field(default="mixed")
    error: Optional[str] = None


async def collect_search_results(
    requests: list[dict[str, Any]],
    *,
    secrets_manager: Any = None,
) -> list[SearchResponseItem]:
    """Search normalized Social Media requests across selected providers."""
    results: list[SearchResponseItem] = []
    for index, raw_item in enumerate(requests, start=1):
        item = SearchRequestItem(**raw_item)
        request_id = item.id if item.id is not None else index
        platforms = _requested_platforms(item.platform)
        soft_skip_unavailable = len(platforms) > 1
        for platform in platforms:
            if platform == "bluesky":
                results.append(
                    await _search_bluesky(
                        request_id,
                        item,
                        secrets_manager,
                        soft_skip_unavailable=soft_skip_unavailable,
                    )
                )
            elif platform == "mastodon":
                results.append(await _search_mastodon(request_id, item))
            else:
                results.append(
                    SearchResponseItem(
                        id=request_id,
                        platform=platform,
                        query=item.query,
                        sort=item.sort,
                        errors=[f"Unsupported social search platform: {platform}"],
                    )
                )
    return results


def _requested_platforms(platform: Optional[str]) -> tuple[str, ...]:
    normalized = (platform or "all").strip().lower()
    if normalized in {"", "all", "mixed", "default"}:
        return DEFAULT_SEARCH_PLATFORMS
    return (normalized,)


async def _search_bluesky(
    request_id: Any,
    item: SearchRequestItem,
    secrets_manager: Any,
    *,
    soft_skip_unavailable: bool = False,
) -> SearchResponseItem:
    bluesky_result = await search_posts(
        item.query,
        sort=item.sort.value,
        limit=item.limit,
        author=item.author,
        include_comments=item.include_comments,
        comments_limit=item.comments_limit,
        secrets_manager=secrets_manager,
    )
    warnings = _clean_bluesky_warnings(
        bluesky_result.warnings,
        bluesky_result.errors,
        soft_skip_unavailable=soft_skip_unavailable,
    )
    errors = _clean_bluesky_errors(bluesky_result.errors, soft_skip_unavailable=soft_skip_unavailable)
    return SearchResponseItem(
        id=request_id,
        platform=bluesky_result.platform,
        query=item.query,
        sort=bluesky_result.sort,
        posts=bluesky_result.posts,
        results=bluesky_result.posts,
        provider=BLUESKY_PROVIDER_NAME,
        request_count=bluesky_result.request_count,
        warnings=warnings,
        errors=errors,
    )


async def _search_mastodon(request_id: Any, item: SearchRequestItem) -> SearchResponseItem:
    instances = _mastodon_instances_for_item(item)
    mastodon_result = await search_mastodon_posts(
        item.query,
        instances=instances,
        limit=item.limit,
        include_comments=item.include_comments,
        comments_limit=item.comments_limit,
    )
    warnings = list(mastodon_result.warnings)
    if item.sort.value != "latest":
        warnings.append("Mastodon public search returns instance-ranked recent results and ignores the requested sort.")
    return SearchResponseItem(
        id=request_id,
        platform=mastodon_result.platform,
        query=item.query,
        sort=mastodon_result.sort,
        posts=mastodon_result.posts,
        results=mastodon_result.posts,
        provider=MASTODON_PROVIDER_NAME,
        request_count=mastodon_result.request_count,
        warnings=warnings,
        errors=mastodon_result.errors,
    )


def _mastodon_instances_for_item(item: SearchRequestItem) -> list[str]:
    instances = list(item.mastodon_instances)
    if item.page:
        instances.insert(0, item.page)
    return instances




def _clean_bluesky_warnings(warnings: list[str], errors: list[str], *, soft_skip_unavailable: bool) -> list[str]:
    cleaned = [warning for warning in warnings if "SECRET__BLUESKY__" not in warning]
    if any(_is_bluesky_auth_error(error) for error in errors):
        cleaned.append(BLUESKY_AUTH_REQUIRED_WARNING)
        if soft_skip_unavailable:
            cleaned.append("Skipped Bluesky in the multi-platform search instead of returning a raw provider error.")
    return list(dict.fromkeys(cleaned))


def _clean_bluesky_errors(errors: list[str], *, soft_skip_unavailable: bool) -> list[str]:
    cleaned: list[str] = []
    for error in errors:
        if _is_bluesky_auth_error(error):
            if not soft_skip_unavailable:
                cleaned.append(BLUESKY_AUTH_REQUIRED_WARNING)
            continue
        cleaned.append(_truncate_provider_error(error))
    return list(dict.fromkeys(cleaned))


def _is_bluesky_auth_error(error: str) -> bool:
    return "HTTP 403" in error or "Forbidden" in error or "Bluesky topic search may require authentication" in error




def _truncate_provider_error(error: str) -> str:
    return error if len(error) <= 240 else f"{error[:237]}..."
