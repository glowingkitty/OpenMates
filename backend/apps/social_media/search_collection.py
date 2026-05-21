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

from pydantic import BaseModel, Field

from backend.shared.providers.bluesky.public import BlueskyPost, search_posts
from backend.shared.providers.reddit.json import (
    RedditCommentSort,
    RedditSearchSort,
    RedditTimeRange,
    search_reddit_posts_json,
)
from backend.shared.providers.reddit.rss import RedditRssPost, search_reddit_posts

SUPPORTED_SEARCH_PLATFORMS = {"bluesky", "reddit"}
DEFAULT_SEARCH_PLATFORMS = ("bluesky", "reddit")
DEFAULT_REQUEST_LIMIT = 10
MAX_COMMENTS_PER_POST = 5


class SearchRequestItem(BaseModel):
    """A single social topic search request."""

    id: Optional[Any] = Field(default=None, description="Optional caller-supplied request ID.")
    platform: Optional[str] = Field(
        default=None,
        description="Social platform to search. Omit or use all to search every supported provider.",
    )
    query: str = Field(description="Topic or search query to find posts around.")
    page: Optional[str] = Field(default=None, description="Optional subreddit/page to restrict Reddit search to.")
    sort: RedditSearchSort = Field(default=RedditSearchSort.LATEST, description="Search sort.")
    time_range: Optional[RedditTimeRange] = Field(
        default=None,
        description="Reddit time filter for top/comments search: hour, day, week, month, year, all.",
    )
    limit: int = Field(default=DEFAULT_REQUEST_LIMIT, ge=1, le=25, description="Number of posts to fetch.")
    author: Optional[str] = Field(
        default=None,
        description="Optional platform profile/handle filter. Currently only supported by Bluesky.",
    )
    include_comments: bool = Field(default=False, description="Whether to fetch comments for returned posts when supported.")
    comments_limit: int = Field(default=0, ge=0, le=MAX_COMMENTS_PER_POST, description="Comments to fetch per returned post when supported.")
    comments_sort: RedditCommentSort = Field(default=RedditCommentSort.TOP, description="Reddit comment sort.")
    min_score: Optional[int] = Field(default=None, ge=0, description="Minimum Reddit score/upvotes to include.")
    min_comments: Optional[int] = Field(default=None, ge=0, description="Minimum Reddit comment count to include.")
    exclude_stickied: bool = Field(default=True, description="Exclude stickied Reddit posts.")
    exclude_nsfw: bool = Field(default=True, description="Exclude NSFW Reddit posts.")


class SearchResponseItem(BaseModel):
    """Posts returned for one social topic search request."""

    id: Optional[Any] = None
    platform: str
    query: str
    sort: str
    posts: list[BlueskyPost | RedditRssPost] = Field(default_factory=list)
    results: list[BlueskyPost | RedditRssPost] = Field(default_factory=list)
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
    reddit_proxy_url: Optional[str] = None,
    reddit_proxy_warning: Optional[str] = None,
) -> list[SearchResponseItem]:
    """Search normalized Social Media requests across selected providers."""
    results: list[SearchResponseItem] = []
    for index, raw_item in enumerate(requests, start=1):
        item = SearchRequestItem(**raw_item)
        request_id = item.id if item.id is not None else index
        for platform in _requested_platforms(item.platform):
            if platform == "bluesky":
                results.append(await _search_bluesky(request_id, item, secrets_manager))
            elif platform == "reddit":
                results.append(await _search_reddit(request_id, item, reddit_proxy_url, reddit_proxy_warning))
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


async def _search_bluesky(request_id: Any, item: SearchRequestItem, secrets_manager: Any) -> SearchResponseItem:
    bluesky_result = await search_posts(
        item.query,
        sort=item.sort.value,
        limit=item.limit,
        author=item.author,
        include_comments=item.include_comments,
        comments_limit=item.comments_limit,
        secrets_manager=secrets_manager,
    )
    return SearchResponseItem(
        id=request_id,
        platform=bluesky_result.platform,
        query=item.query,
        sort=bluesky_result.sort,
        posts=bluesky_result.posts,
        results=bluesky_result.posts,
        provider=bluesky_result.provider,
        request_count=bluesky_result.request_count,
        warnings=bluesky_result.warnings,
        errors=bluesky_result.errors,
    )


async def _search_reddit(
    request_id: Any,
    item: SearchRequestItem,
    reddit_proxy_url: Optional[str],
    reddit_proxy_warning: Optional[str],
) -> SearchResponseItem:
    if not reddit_proxy_url:
        error = reddit_proxy_warning or "Reddit JSON search requires Webshare proxy credentials."
        return SearchResponseItem(
            id=request_id,
            platform="reddit",
            query=item.query,
            sort=item.sort,
            provider="reddit_json",
            errors=[error],
        )

    reddit_result = await search_reddit_posts_json(
        item.query,
        page=item.page,
        sort=item.sort,
        time_range=item.time_range,
        limit=item.limit,
        include_comments=item.include_comments,
        comments_limit=item.comments_limit,
        comments_sort=item.comments_sort,
        min_score=item.min_score,
        min_comments=item.min_comments,
        exclude_stickied=item.exclude_stickied,
        exclude_nsfw=item.exclude_nsfw,
        proxy_url=reddit_proxy_url,
    )
    provider = "reddit_json"
    if reddit_result.errors and not reddit_result.posts:
        fallback = await search_reddit_posts(
            item.query,
            sort=item.sort.value,
            limit=item.limit,
            proxy_url=reddit_proxy_url,
        )
        fallback.warnings = [
            "Reddit JSON failed; fell back to Reddit RSS.",
            *reddit_result.warnings,
            *reddit_result.errors,
            *fallback.warnings,
        ]
        reddit_result = fallback
        provider = "reddit_rss"
    return SearchResponseItem(
        id=request_id,
        platform=reddit_result.platform,
        query=item.query,
        sort=reddit_result.sort,
        posts=reddit_result.posts,
        results=reddit_result.posts,
        provider=provider,
        request_count=reddit_result.request_count,
        warnings=reddit_result.warnings,
        errors=reddit_result.errors,
    )
