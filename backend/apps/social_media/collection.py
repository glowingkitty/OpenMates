# backend/apps/social_media/collection.py
#
# Shared Social Media collection models and provider dispatch.
# This module is intentionally Celery-free so provider normalization can be
# unit-tested without starting worker dependencies.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.shared.providers.bluesky.public import BlueskyPost, fetch_author_posts
from backend.shared.providers.mastodon.public import MastodonPost, fetch_account_posts
from backend.shared.providers.reddit.json import (
    RedditCommentSort,
    RedditListingSort,
    RedditTimeRange,
    fetch_subreddit_posts_json,
)
from backend.shared.providers.reddit.rss import RedditRateLimit, RedditRssPost, fetch_subreddit_posts

SUPPORTED_PLATFORMS = {"bluesky", "mastodon", "reddit"}
DEFAULT_REQUEST_LIMIT = 10
DEFAULT_COMMENTS_LIMIT = 5
MAX_COMMENTS_PER_POST = 5


class GetPostsRequestItem(BaseModel):
    """A single social page fetch request."""

    id: Optional[Any] = Field(default=None, description="Optional caller-supplied request ID.")
    platform: str = Field(default="reddit", description="Social platform: reddit, bluesky, or mastodon.")
    page: str = Field(
        default="",
        description=(
            "Platform page/profile identifier. For Reddit, this is the subreddit name; "
            "for Bluesky, this is an actor handle; for Mastodon, this is user@instance or a profile URL."
        ),
    )
    sort: RedditListingSort = Field(
        default=RedditListingSort.NEW,
        description="Post listing sort. Reddit: new, hot, rising, top, comments. Bluesky profile feeds ignore this value.",
    )
    time_range: Optional[RedditTimeRange] = Field(
        default=None,
        description="Reddit time filter for top/comments sorts: hour, day, week, month, year, all.",
    )
    limit: int = Field(default=DEFAULT_REQUEST_LIMIT, ge=1, le=25, description="Number of posts to fetch.")
    include_comments: bool = Field(default=True, description="Whether to fetch comments for returned posts.")
    comments_limit: int = Field(default=DEFAULT_COMMENTS_LIMIT, ge=0, le=MAX_COMMENTS_PER_POST, description="Comments to fetch per post.")
    comments_sort: RedditCommentSort = Field(default=RedditCommentSort.TOP, description="Reddit comment sort.")
    min_score: Optional[int] = Field(default=None, ge=0, description="Minimum Reddit score/upvotes to include.")
    min_comments: Optional[int] = Field(default=None, ge=0, description="Minimum Reddit comment count to include.")
    exclude_stickied: bool = Field(default=True, description="Exclude stickied Reddit posts.")
    exclude_nsfw: bool = Field(default=True, description="Exclude NSFW Reddit posts.")
    include_self_posts: bool = Field(default=True, description="Include Reddit text/self posts.")
    include_link_posts: bool = Field(default=True, description="Include Reddit link/media posts.")


class GetPostsResponseItem(BaseModel):
    """Posts returned for one social page fetch request."""

    id: Optional[Any] = None
    platform: str
    page: str
    sort: str
    posts: list[RedditRssPost | BlueskyPost | MastodonPost] = Field(default_factory=list)
    provider: str = Field(default="")
    request_count: int = 0
    rate_limit: Optional[RedditRateLimit] = None
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
    *,
    reddit_proxy_url: Optional[str] = None,
    reddit_proxy_warning: Optional[str] = None,
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
        else:
            results.append(
                await _fetch_reddit(
                    request_id,
                    item,
                    proxy_url=reddit_proxy_url,
                    proxy_warning=reddit_proxy_warning,
                )
            )
    return results


async def _fetch_reddit(
    request_id: Any,
    item: GetPostsRequestItem,
    *,
    proxy_url: Optional[str] = None,
    proxy_warning: Optional[str] = None,
) -> GetPostsResponseItem:
    if not item.page.strip():
        return GetPostsResponseItem(
            id=request_id,
            platform="reddit",
            page="",
            sort=item.sort,
            provider="reddit_json",
            errors=["Reddit requests require a page/subreddit."],
        )

    if not proxy_url:
        error = proxy_warning or "Reddit JSON requests require Webshare proxy credentials."
        return GetPostsResponseItem(
            id=request_id,
            platform="reddit",
            page=item.page,
            sort=item.sort,
            provider="reddit_json",
            errors=[error],
        )

    reddit_result = await fetch_subreddit_posts_json(
        item.page,
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
        include_self_posts=item.include_self_posts,
        include_link_posts=item.include_link_posts,
        proxy_url=proxy_url,
    )
    provider = "reddit_json"
    if reddit_result.errors and not reddit_result.posts:
        warnings = [
            "Reddit JSON failed; fell back to Reddit RSS.",
            *reddit_result.warnings,
            *reddit_result.errors,
        ]
        fallback = await fetch_subreddit_posts(
            item.page,
            sort="top" if item.sort == RedditListingSort.COMMENTS else item.sort.value,
            limit=item.limit,
            include_comments=item.include_comments,
            comments_limit=item.comments_limit,
            proxy_url=proxy_url,
        )
        fallback.warnings = warnings + fallback.warnings
        reddit_result = fallback
        provider = "reddit_rss"
    warnings = list(reddit_result.warnings)
    if proxy_warning:
        warnings.append(proxy_warning)
    return GetPostsResponseItem(
        id=request_id,
        platform=reddit_result.platform,
        page=reddit_result.page,
        sort=reddit_result.sort,
        posts=reddit_result.posts,
        provider=provider,
        request_count=reddit_result.request_count,
        rate_limit=reddit_result.rate_limit,
        rate_limited=reddit_result.rate_limited,
        next_retry_after_seconds=reddit_result.next_retry_after_seconds,
        comments_skipped_count=reddit_result.comments_skipped_count,
        warnings=warnings,
        errors=reddit_result.errors,
    )


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
        provider=bluesky_result.provider,
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
        provider=mastodon_result.provider,
        request_count=mastodon_result.request_count,
        warnings=mastodon_result.warnings,
        errors=mastodon_result.errors,
    )
