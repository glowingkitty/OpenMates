# backend/shared/providers/reddit/json.py
#
# Reddit JSON provider for read-only social listening.
# Fetches public subreddit listings, Reddit search results, and post comments
# through provider-managed Webshare residential proxies. It intentionally keeps
# the same normalized response shape as the RSS provider so app skills can use
# JSON first and fall back to RSS without changing embed contracts.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
import http.client
import logging
from typing import Any, Optional
import urllib.error
import urllib.parse
import urllib.request

from backend.shared.providers.reddit.rss import RedditRateLimit, RedditRssComment, RedditRssPost, RedditRssResult

logger = logging.getLogger(__name__)

REDDIT_BASE_URL = "https://www.reddit.com"
USER_AGENT = "linux:openmates-social-media:0.1.0 (by /u/openmates)"
REQUEST_TIMEOUT_SECONDS = 25.0
MAX_429_RETRIES = 2
DEFAULT_429_RETRY_DELAY_SECONDS = 2.0
MAX_POST_LIMIT = 25
MAX_COMMENT_LIMIT = 5
DEFAULT_POST_LIMIT = 10
DEFAULT_COMMENT_LIMIT = 5


class RedditListingSort(str, Enum):
    """Supported Reddit subreddit listing sorts."""

    NEW = "new"
    HOT = "hot"
    RISING = "rising"
    TOP = "top"
    COMMENTS = "comments"


class RedditSearchSort(str, Enum):
    """Supported Reddit search sorts."""

    RELEVANCE = "relevance"
    HOT = "hot"
    TOP = "top"
    NEW = "new"
    COMMENTS = "comments"
    LATEST = "latest"


class RedditTimeRange(str, Enum):
    """Supported Reddit time filters for top/search endpoints."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    ALL = "all"


class RedditCommentSort(str, Enum):
    """Supported Reddit comment sorts."""

    CONFIDENCE = "confidence"
    TOP = "top"
    NEW = "new"
    CONTROVERSIAL = "controversial"
    OLD = "old"


class RedditJsonHttpError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        rate_limit: RedditRateLimit,
        retry_after_seconds: Optional[float] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.rate_limit = rate_limit
        self.retry_after_seconds = retry_after_seconds


class RedditJsonRateLimitError(RedditJsonHttpError):
    pass


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


async def fetch_subreddit_posts_json(
    page: str,
    *,
    sort: RedditListingSort = RedditListingSort.NEW,
    time_range: Optional[RedditTimeRange] = None,
    limit: int = DEFAULT_POST_LIMIT,
    include_comments: bool = True,
    comments_limit: int = DEFAULT_COMMENT_LIMIT,
    comments_sort: RedditCommentSort = RedditCommentSort.TOP,
    min_score: Optional[int] = None,
    min_comments: Optional[int] = None,
    exclude_stickied: bool = True,
    exclude_nsfw: bool = True,
    include_self_posts: bool = True,
    include_link_posts: bool = True,
    proxy_url: Optional[str] = None,
) -> RedditRssResult:
    """Fetch subreddit posts through Reddit JSON endpoints."""
    subreddit = _normalize_subreddit(page)
    post_limit = max(1, min(limit, MAX_POST_LIMIT))
    comment_limit = max(0, min(comments_limit, MAX_COMMENT_LIMIT))
    result = RedditRssResult(page=subreddit, sort=sort.value)

    try:
        listing = await _fetch_json_with_retry(
            _subreddit_listing_url(subreddit, sort, time_range, post_limit),
            proxy_url=proxy_url,
        )
        result.request_count += 1
        result.rate_limit = listing.rate_limit
        posts = _filter_posts(
            _parse_listing_posts(
                listing.data,
                subreddit,
                exclude_stickied=exclude_stickied,
                exclude_nsfw=exclude_nsfw,
                include_self_posts=include_self_posts,
                include_link_posts=include_link_posts,
            ),
            min_score=min_score,
            min_comments=min_comments,
        )[:post_limit]
    except RedditJsonRateLimitError as exc:
        result.rate_limited = True
        result.next_retry_after_seconds = exc.retry_after_seconds
        result.rate_limit = exc.rate_limit
        result.warnings.append(f"Reddit rate limit reached before fetching r/{subreddit}.")
        return result
    except Exception as exc:
        logger.warning("Reddit JSON post fetch failed for r/%s: %s", subreddit, exc)
        result.errors.append(f"Could not fetch r/{subreddit} from Reddit: {exc}")
        return result

    if include_comments and comment_limit > 0:
        for post in posts:
            try:
                detail = await _fetch_json_with_retry(
                    _post_comments_url(post.id, comments_sort, comment_limit),
                    proxy_url=proxy_url,
                )
                result.request_count += 1
                result.rate_limit = detail.rate_limit
                comments = _parse_detail_comments(detail.data)[:comment_limit]
                post.comments = comments
                post.fetched_comment_count = len(comments)
            except RedditJsonRateLimitError as exc:
                result.rate_limited = True
                result.next_retry_after_seconds = exc.retry_after_seconds
                result.rate_limit = exc.rate_limit
                result.comments_skipped_count += len(posts) - posts.index(post)
                result.warnings.append("Skipped remaining comments because Reddit is rate limited.")
                break
            except Exception as exc:
                logger.info("Reddit JSON comment fetch failed for %s: %s", post.url, exc)
                result.errors.append(f"Could not fetch comments for {post.url} from Reddit: {exc}")

    result.posts = posts
    return result


async def search_reddit_posts_json(
    query: str,
    *,
    page: Optional[str] = None,
    sort: RedditSearchSort = RedditSearchSort.RELEVANCE,
    time_range: Optional[RedditTimeRange] = None,
    limit: int = DEFAULT_POST_LIMIT,
    include_comments: bool = False,
    comments_limit: int = 0,
    comments_sort: RedditCommentSort = RedditCommentSort.TOP,
    min_score: Optional[int] = None,
    min_comments: Optional[int] = None,
    exclude_stickied: bool = True,
    exclude_nsfw: bool = True,
    proxy_url: Optional[str] = None,
) -> RedditRssResult:
    """Search Reddit posts through JSON endpoints."""
    search_query = (query or "").strip()
    if not search_query:
        return RedditRssResult(page=page or "", sort=sort.value, errors=["Reddit search requires a query."])

    post_limit = max(1, min(limit, MAX_POST_LIMIT))
    result = RedditRssResult(page=page or search_query, sort=_normalize_search_sort(sort).value)
    try:
        response = await _fetch_json_with_retry(
            _search_url(search_query, page, sort, time_range, post_limit),
            proxy_url=proxy_url,
        )
        result.request_count += 1
        result.rate_limit = response.rate_limit
        posts = _filter_posts(
            _parse_listing_posts(
                response.data,
                page or search_query,
                exclude_stickied=exclude_stickied,
                exclude_nsfw=exclude_nsfw,
                include_self_posts=True,
                include_link_posts=True,
            ),
            min_score=min_score,
            min_comments=min_comments,
        )[:post_limit]
    except RedditJsonRateLimitError as exc:
        result.rate_limited = True
        result.next_retry_after_seconds = exc.retry_after_seconds
        result.rate_limit = exc.rate_limit
        result.warnings.append("Reddit rate limit reached before completing search.")
        return result
    except Exception as exc:
        logger.warning("Reddit JSON search failed for %s: %s", search_query, exc)
        result.errors.append(f"Could not search Reddit via JSON for {search_query}: {exc}")
        return result

    if include_comments and comments_limit > 0:
        comment_limit = max(0, min(comments_limit, MAX_COMMENT_LIMIT))
        for post in posts:
            try:
                detail = await _fetch_json_with_retry(
                    _post_comments_url(post.id, comments_sort, comment_limit),
                    proxy_url=proxy_url,
                )
                result.request_count += 1
                result.rate_limit = detail.rate_limit
                post.comments = _parse_detail_comments(detail.data)[:comment_limit]
                post.fetched_comment_count = len(post.comments)
            except Exception as exc:
                result.errors.append(f"Could not fetch comments for {post.url} from Reddit: {exc}")

    result.posts = posts
    return result


class _FetchJsonResponse:
    def __init__(self, data: Any, rate_limit: RedditRateLimit):
        self.data = data
        self.rate_limit = rate_limit


async def _fetch_json_with_retry(url: str, *, proxy_url: Optional[str]) -> _FetchJsonResponse:
    for attempt in range(1, MAX_429_RETRIES + 1):
        try:
            return await asyncio.to_thread(_fetch_json_sync, url, proxy_url)
        except RedditJsonRateLimitError as exc:
            if attempt >= MAX_429_RETRIES:
                raise
            await asyncio.sleep(exc.retry_after_seconds or DEFAULT_429_RETRY_DELAY_SECONDS)
        except (http.client.IncompleteRead, TimeoutError, urllib.error.URLError) as exc:
            if attempt >= MAX_429_RETRIES:
                raise
            logger.info(
                "Transient Reddit JSON fetch error for %s; retrying (attempt %s/%s): %s",
                url,
                attempt,
                MAX_429_RETRIES,
                exc,
            )
            await asyncio.sleep(DEFAULT_429_RETRY_DELAY_SECONDS)
    raise RuntimeError("Reddit JSON retry loop exited unexpectedly")  # pragma: no cover


def _fetch_json_sync(url: str, proxy_url: Optional[str]) -> _FetchJsonResponse:
    import json

    request = urllib.request.Request(url, headers=_headers())
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})) if proxy_url else None
        open_request = opener.open if opener else urllib.request.urlopen
        with open_request(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
            text = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            return _FetchJsonResponse(json.loads(text), _parse_rate_limit(response.headers))
    except urllib.error.HTTPError as exc:
        rate_limit = _parse_rate_limit(exc.headers)
        retry_after = _parse_retry_after_seconds(exc.headers, rate_limit)
        body = exc.read().decode("utf-8", errors="replace")[:160]
        message = f"HTTP {exc.code} for {url}: {body}"
        if exc.code == 429:
            raise RedditJsonRateLimitError(message, status_code=exc.code, rate_limit=rate_limit, retry_after_seconds=retry_after) from exc
        raise RedditJsonHttpError(message, status_code=exc.code, rate_limit=rate_limit, retry_after_seconds=retry_after) from exc


def _subreddit_listing_url(subreddit: str, sort: RedditListingSort, time_range: Optional[RedditTimeRange], limit: int) -> str:
    encoded_subreddit = urllib.parse.quote(subreddit, safe="")
    if sort == RedditListingSort.COMMENTS:
        query = urllib.parse.urlencode({"q": "*", "restrict_sr": "1", "sort": "comments", "t": (time_range or RedditTimeRange.WEEK).value, "limit": limit})
        return f"{REDDIT_BASE_URL}/r/{encoded_subreddit}/search.json?{query}"
    params: dict[str, Any] = {"limit": limit}
    if sort == RedditListingSort.TOP and time_range:
        params["t"] = time_range.value
    return f"{REDDIT_BASE_URL}/r/{encoded_subreddit}/{sort.value}.json?{urllib.parse.urlencode(params)}"


def _search_url(query: str, page: Optional[str], sort: RedditSearchSort, time_range: Optional[RedditTimeRange], limit: int) -> str:
    normalized_sort = _normalize_search_sort(sort)
    params: dict[str, Any] = {"q": query, "sort": normalized_sort.value, "limit": limit}
    if time_range:
        params["t"] = time_range.value
    if page:
        params["restrict_sr"] = "1"
        return f"{REDDIT_BASE_URL}/r/{urllib.parse.quote(_normalize_subreddit(page), safe='')}/search.json?{urllib.parse.urlencode(params)}"
    return f"{REDDIT_BASE_URL}/search.json?{urllib.parse.urlencode(params)}"


def _post_comments_url(post_id: str, sort: RedditCommentSort, limit: int) -> str:
    # Reddit's comments JSON can return only `more` placeholders for some active
    # threads when a very small `limit` is sent. Fetch the page and slice locally.
    del limit
    params = urllib.parse.urlencode({"sort": sort.value})
    return f"{REDDIT_BASE_URL}/comments/{urllib.parse.quote(post_id, safe='')}.json?{params}"


def _normalize_subreddit(page: str) -> str:
    cleaned = (page or "").strip().removeprefix("r/").strip("/")
    if not cleaned:
        raise ValueError("Reddit page/subreddit is required.")
    return cleaned


def _normalize_search_sort(sort: RedditSearchSort) -> RedditSearchSort:
    return RedditSearchSort.NEW if sort == RedditSearchSort.LATEST else sort


def _parse_listing_posts(
    payload: Any,
    page: str,
    *,
    exclude_stickied: bool = False,
    exclude_nsfw: bool = False,
    include_self_posts: bool = True,
    include_link_posts: bool = True,
) -> list[RedditRssPost]:
    children = payload.get("data", {}).get("children", []) if isinstance(payload, dict) else []
    return [
        _post_from_data(child.get("data", {}), page)
        for child in children
        if child.get("kind") == "t3"
        and _post_allowed(
            child.get("data", {}),
            exclude_stickied=exclude_stickied,
            exclude_nsfw=exclude_nsfw,
            include_self_posts=include_self_posts,
            include_link_posts=include_link_posts,
        )
    ]


def _post_from_data(data: dict[str, Any], page: str) -> RedditRssPost:
    permalink = data.get("permalink") or ""
    url = f"{REDDIT_BASE_URL}{permalink}" if permalink.startswith("/") else data.get("url") or ""
    published_at = _datetime_from_utc(data.get("created_utc"))
    ups = _optional_int(data.get("ups"))
    num_comments = _optional_int(data.get("num_comments"))
    return RedditRssPost(
        id=str(data.get("id") or ""),
        page=(data.get("subreddit") or page or "").removeprefix("r/"),
        title=str(data.get("title") or ""),
        body=str(data.get("selftext") or ""),
        author=data.get("author"),
        url=url,
        published_at=published_at,
        score=_optional_int(data.get("score")),
        ups=ups,
        downs=_optional_int(data.get("downs")),
        upvote_ratio=_optional_float(data.get("upvote_ratio")),
        num_comments=num_comments,
        like_count=ups,
        reply_count=num_comments,
    )


def _parse_detail_comments(payload: Any) -> list[RedditRssComment]:
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    children = payload[1].get("data", {}).get("children", [])
    comments: list[RedditRssComment] = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data", {})
        body = str(data.get("body") or "").strip()
        if not body or body in {"[removed]", "[deleted]"}:
            continue
        comments.append(
            RedditRssComment(
                id=str(data.get("id") or ""),
                author=data.get("author"),
                body=body,
                url=f"{REDDIT_BASE_URL}{data.get('permalink', '')}",
                published_at=_datetime_from_utc(data.get("created_utc")),
                score=_optional_int(data.get("score")),
                ups=_optional_int(data.get("ups")),
                downs=_optional_int(data.get("downs")),
            )
        )
    return sorted(
        comments,
        key=lambda comment: comment.ups if comment.ups is not None else comment.score or 0,
        reverse=True,
    )


def _filter_posts(
    posts: list[RedditRssPost],
    *,
    min_score: Optional[int],
    min_comments: Optional[int],
) -> list[RedditRssPost]:
    filtered = posts
    if min_score is not None:
        filtered = [post for post in filtered if (post.score or 0) >= min_score]
    if min_comments is not None:
        filtered = [post for post in filtered if (post.num_comments or 0) >= min_comments]
    return filtered


def _post_allowed(
    data: dict[str, Any],
    *,
    exclude_stickied: bool,
    exclude_nsfw: bool,
    include_self_posts: bool,
    include_link_posts: bool,
) -> bool:
    if exclude_stickied and data.get("stickied"):
        return False
    if exclude_nsfw and data.get("over_18"):
        return False
    is_self = bool(data.get("is_self"))
    if is_self and not include_self_posts:
        return False
    if not is_self and not include_link_posts:
        return False
    return True


def _datetime_from_utc(value: Any) -> Optional[str]:
    timestamp = _optional_float(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_rate_limit(headers: Any) -> RedditRateLimit:
    return RedditRateLimit(
        used=_optional_float(headers.get("x-ratelimit-used")),
        remaining=_optional_float(headers.get("x-ratelimit-remaining")),
        reset_seconds=_optional_float(headers.get("x-ratelimit-reset")),
    )


def _parse_retry_after_seconds(headers: Any, rate_limit: RedditRateLimit) -> Optional[float]:
    retry_after = _optional_float(headers.get("retry-after"))
    if retry_after is not None:
        return retry_after
    return rate_limit.reset_seconds
