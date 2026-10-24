# backend/apps/social_media/collection.py
#
# Shared Social Media collection models and provider dispatch.
# This module is intentionally Celery-free so provider normalization can be
# unit-tested without starting worker dependencies.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

from typing import Any, Optional
from enum import Enum

from pydantic import BaseModel, Field

from backend.shared.providers.bluesky.public import BlueskyPost, fetch_author_posts
from backend.shared.providers.mastodon.public import MastodonPost, fetch_account_posts

class ListingSort(str, Enum):
    NEW = "new"
    HOT = "hot"
    RISING = "rising"
    TOP = "top"
    COMMENTS = "comments"


class CommentSort(str, Enum):
    TOP = "top"
    CONFIDENCE = "confidence"
    NEW = "new"
    CONTROVERSIAL = "controversial"
    OLD = "old"


class TimeRange(str, Enum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    ALL = "all"


SUPPORTED_PLATFORMS = {"bluesky", "mastodon"}
BLUESKY_PROVIDER_NAME = "Bluesky"
DEFAULT_REQUEST_LIMIT = 10
DEFAULT_COMMENTS_LIMIT = 5
MAX_COMMENTS_PER_POST = 5
MASTODON_PROVIDER_NAME = "Mastodon"


class GetPostsRequestItem(BaseModel):
    """A single social page fetch request."""

    id: Optional[Any] = Field(default=None, description="Optional caller-supplied request ID.")
    platform: str = Field(default="", description="Social platform: bluesky or mastodon.")
    page: str = Field(
        default="",
        description=(
            "Platform profile identifier. "
            "for Bluesky, this is an actor handle; for Mastodon, this is user@instance or a profile URL."
        ),
    )
    sort: ListingSort = Field(
        default=ListingSort.NEW,
        description="Post listing sort; profile feeds may ignore this value.",
    )
    time_range: Optional[TimeRange] = Field(
        default=None,
        description="Optional listing time range.",
    )
    limit: int = Field(default=DEFAULT_REQUEST_LIMIT, ge=1, le=25, description="Number of posts to fetch.")
    include_comments: bool = Field(default=True, description="Whether to fetch comments for returned posts.")
    comments_limit: int = Field(default=DEFAULT_COMMENTS_LIMIT, ge=0, le=MAX_COMMENTS_PER_POST, description="Comments to fetch per post.")
    comments_sort: CommentSort = Field(default=CommentSort.TOP, description="Comment sort.")
    min_score: Optional[int] = Field(default=None, ge=0, description="Minimum post score to include.")
    min_comments: Optional[int] = Field(default=None, ge=0, description="Minimum comment count to include.")
    exclude_stickied: bool = Field(default=True, description="Exclude stickied posts.")
    exclude_nsfw: bool = Field(default=True, description="Exclude NSFW posts.")
    include_self_posts: bool = Field(default=True, description="Include text posts.")
    include_link_posts: bool = Field(default=True, description="Include link/media posts.")


class GetPostsResponseItem(BaseModel):
    """Posts returned for one social page fetch request."""

    id: Optional[Any] = None
    platform: str
    page: str
    sort: str
    posts: list[BlueskyPost | MastodonPost] = Field(default_factory=list)
    provider: str = Field(default="")
    request_count: int = 0
    rate_limit: Optional[dict[str, Any]] = None
    rate_limited: bool = False
    next_retry_after_seconds: Optional[float] = None
    comments_skipped_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GetPostsResponse(BaseModel):
    """Response model for the Social Media Get Posts skill."""

    task_id: Optional[str] = None
    embed_id: Optional[str] = None
    task_ids: list[str] = Field(default_factory=list)
    embed_ids: list[str] = Field(default_factory=list)
    status: str = "processing"
    results: list[GetPostsResponseItem] = Field(default_factory=list)
    provider: str = Field(default="mixed")
    error: Optional[str] = None


async def collect_posts(
    requests: list[dict[str, Any]],
) -> list[GetPostsResponseItem]:
    """Fetch posts for a normalized list of social media page requests."""
    results: list[GetPostsResponseItem] = []
    for index, raw_item in enumerate(requests, start=1):
        item = GetPostsRequestItem(**raw_item)
        request_id = item.id if item.id is not None else index
        platform = item.platform.lower().strip()
        if platform not in SUPPORTED_PLATFORMS:
            results.append(
                GetPostsResponseItem(
                    id=request_id,
                    platform=platform,
                    page=item.page,
                    sort=item.sort,
                    errors=[f"Unsupported social platform: {item.platform}"],
                )
            )
            continue
        if platform == "bluesky":
            results.append(await _fetch_bluesky(request_id, item))
        elif platform == "mastodon":
            results.append(await _fetch_mastodon(request_id, item))
    return results






async def _fetch_bluesky(request_id: Any, item: GetPostsRequestItem) -> GetPostsResponseItem:
    bluesky_result = await fetch_author_posts(
        item.page,
        limit=item.limit,
        include_comments=item.include_comments,
        comments_limit=item.comments_limit,
    )
    return GetPostsResponseItem(
        id=request_id,
        platform=bluesky_result.platform,
        page=bluesky_result.page,
        sort=bluesky_result.sort,
        posts=bluesky_result.posts,
        provider=BLUESKY_PROVIDER_NAME,
        request_count=bluesky_result.request_count,
        warnings=bluesky_result.warnings,
        errors=bluesky_result.errors,
    )


async def _fetch_mastodon(request_id: Any, item: GetPostsRequestItem) -> GetPostsResponseItem:
    mastodon_result = await fetch_account_posts(
        item.page,
        limit=item.limit,
        include_comments=item.include_comments,
        comments_limit=item.comments_limit,
    )
    return GetPostsResponseItem(
        id=request_id,
        platform=mastodon_result.platform,
        page=mastodon_result.page,
        sort=mastodon_result.sort,
        posts=mastodon_result.posts,
        provider=MASTODON_PROVIDER_NAME,
        request_count=mastodon_result.request_count,
        warnings=mastodon_result.warnings,
        errors=mastodon_result.errors,
    )
