# backend/shared/providers/reddit/rss.py
#
# Reddit RSS/Atom provider for read-only social listening.
# Fetches recent subreddit posts and optional post comments without using
# Reddit account credentials. This is intentionally conservative: it owns a small
# per-call request budget and returns partial results if Reddit asks us to slow down.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

import html
import asyncio
import logging
from email.utils import parsedate_to_datetime
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

REDDIT_BASE_URL = "https://www.reddit.com"
USER_AGENT = "linux:openmates-social-media:0.1.0 (by /u/openmates)"
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_429_RETRIES = 2
DEFAULT_429_RETRY_DELAY_SECONDS = 2.0
MAX_INLINE_RATE_LIMIT_WAIT_SECONDS = 30.0
DEFAULT_MAX_REQUESTS_PER_CALL = 20
MIN_REMAINING_REQUESTS_FOR_COMMENTS = 5.0
DEFAULT_POST_LIMIT = 10
DEFAULT_COMMENT_LIMIT = 5
MAX_POST_LIMIT = 25
MAX_COMMENT_LIMIT = 25
ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}
IGNORED_COMMENT_AUTHORS = {"/u/AutoModerator", "AutoModerator"}


class RedditRateLimit(BaseModel):
    """Rate-limit details returned by Reddit RSS endpoints when available."""

    used: Optional[float] = None
    remaining: Optional[float] = None
    reset_seconds: Optional[float] = None


class RedditRssComment(BaseModel):
    """A Reddit comment parsed from a post RSS feed."""

    id: str = Field(description="Reddit comment ID if available.")
    author: Optional[str] = Field(default=None, description="Public Reddit username.")
    body: str = Field(description="Comment text with HTML removed.")
    url: str = Field(description="Canonical Reddit comment URL.")
    published_at: Optional[str] = Field(default=None, description="ISO timestamp from the feed.")
    score: Optional[int] = Field(default=None, description="Reddit public score when available.")
    ups: Optional[int] = Field(default=None, description="Reddit public upvote count when available.")
    downs: Optional[int] = Field(default=None, description="Reddit public downvote count when available.")


class RedditRssPost(BaseModel):
    """A Reddit post parsed from a subreddit RSS feed."""

    id: str = Field(description="Reddit post ID.")
    platform: str = Field(default="reddit")
    page: str = Field(description="Subreddit name without r/.")
    title: str = Field(description="Full post title.")
    body: str = Field(default="", description="Post body when available; link posts may only contain feed metadata.")
    author: Optional[str] = Field(default=None, description="Public Reddit username.")
    url: str = Field(description="Canonical Reddit post URL.")
    published_at: Optional[str] = Field(default=None, description="ISO timestamp from the feed.")
    score: Optional[int] = Field(default=None, description="Reddit public score when available.")
    ups: Optional[int] = Field(default=None, description="Reddit public upvote count when available.")
    downs: Optional[int] = Field(default=None, description="Reddit public downvote count when available.")
    upvote_ratio: Optional[float] = Field(default=None, description="Reddit public upvote ratio when available.")
    num_comments: Optional[int] = Field(default=None, description="Reddit public comment count when available.")
    like_count: Optional[int] = Field(default=None, description="Normalized like/upvote count for embeds.")
    reply_count: Optional[int] = Field(default=None, description="Normalized comment/reply count for embeds.")
    comments: list[RedditRssComment] = Field(default_factory=list)
    fetched_comment_count: int = Field(default=0, description="Number of comments fetched from RSS for this post.")


class RedditRssResult(BaseModel):
    """Result from a Reddit RSS page fetch."""

    platform: str = Field(default="reddit")
    page: str
    sort: str
    posts: list[RedditRssPost] = Field(default_factory=list)
    request_count: int = 0
    rate_limit: Optional[RedditRateLimit] = None
    rate_limited: bool = False
    next_retry_after_seconds: Optional[float] = None
    comments_skipped_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class _HtmlTextExtractor(HTMLParser):
    """Minimal HTML-to-text converter for Reddit feed content."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in {"p", "br", "li", "div", "ol", "ul"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return _normalize_whitespace(" ".join(self.parts))


async def fetch_subreddit_posts(
    page: str,
    *,
    sort: str = "new",
    limit: int = DEFAULT_POST_LIMIT,
    include_comments: bool = True,
    comments_limit: int = DEFAULT_COMMENT_LIMIT,
    max_requests_per_call: int = DEFAULT_MAX_REQUESTS_PER_CALL,
    min_remaining_for_comments: float = MIN_REMAINING_REQUESTS_FOR_COMMENTS,
    max_inline_wait_seconds: float = MAX_INLINE_RATE_LIMIT_WAIT_SECONDS,
    proxy_url: Optional[str] = None,
) -> RedditRssResult:
    """
    Fetch recent Reddit posts and optional comments from subreddit RSS feeds.

    Args:
        page: Subreddit name, with or without the r/ prefix.
        sort: Reddit listing sort. Supported values: new, hot, rising, top.
        limit: Number of subreddit posts to request.
        include_comments: Whether to fetch each post's RSS comment feed.
        comments_limit: Number of comments requested per post.
        max_requests_per_call: Hard request budget for this provider call.
        min_remaining_for_comments: Stop comment fetches when Reddit reports less
            remaining budget than this threshold.
        max_inline_wait_seconds: Maximum time to sleep inline for a 429 retry.
        proxy_url: Optional HTTP proxy URL for provider-managed Reddit requests.

    Returns:
        RedditRssResult with normalized posts, comments, request count, and errors.
    """
    subreddit = _normalize_subreddit(page)
    sort = _normalize_sort(sort)
    post_limit = max(1, min(limit, MAX_POST_LIMIT))
    comment_limit = max(0, min(comments_limit, MAX_COMMENT_LIMIT))
    request_budget = max(1, max_requests_per_call)
    result = RedditRssResult(page=subreddit, sort=sort)

    listing_url = _subreddit_feed_url(subreddit, sort, post_limit)
    try:
        response = await _fetch_text_with_retry(
            listing_url,
            max_inline_wait_seconds=max_inline_wait_seconds,
            proxy_url=proxy_url,
        )
        result.request_count += 1
        result.rate_limit = response.rate_limit
        posts = _parse_post_feed(response.text, subreddit)
    except _RedditRssRateLimitError as exc:
        logger.warning("Reddit RSS post fetch rate limited for r/%s: %s", subreddit, exc)
        result.rate_limited = True
        result.next_retry_after_seconds = exc.retry_after_seconds
        result.rate_limit = exc.rate_limit
        result.warnings.append(f"Reddit rate limit reached before fetching r/{subreddit}.")
        return result
    except Exception as exc:
        logger.warning("Reddit RSS post fetch failed for r/%s: %s", subreddit, exc)
        result.errors.append(f"Could not fetch r/{subreddit}: {exc}")
        return result

    if include_comments and comment_limit > 0:
        for index, post in enumerate(posts):
            if result.request_count >= request_budget:
                skipped = len(posts) - index
                result.comments_skipped_count += skipped
                result.warnings.append(
                    f"Skipped comments for {skipped} posts because the per-call Reddit request budget was reached."
                )
                break

            if _remaining_too_low(result.rate_limit, min_remaining_for_comments):
                skipped = len(posts) - index
                result.comments_skipped_count += skipped
                result.warnings.append(
                    f"Skipped comments for {skipped} posts because Reddit remaining budget is low."
                )
                break

            try:
                comment_url = _post_comments_feed_url(post.url, comment_limit)
                comment_response = await _fetch_text_with_retry(
                    comment_url,
                    max_inline_wait_seconds=max_inline_wait_seconds,
                    proxy_url=proxy_url,
                )
                result.request_count += 1
                result.rate_limit = comment_response.rate_limit
                post.comments = _parse_comment_feed(comment_response.text, post.url)[:comment_limit]
                post.fetched_comment_count = len(post.comments)
            except _RedditRssRateLimitError as exc:
                skipped = len(posts) - index
                result.rate_limited = True
                result.next_retry_after_seconds = exc.retry_after_seconds
                result.rate_limit = exc.rate_limit
                result.comments_skipped_count += skipped
                result.warnings.append(
                    f"Skipped comments for {skipped} posts because Reddit is rate limited."
                )
                break
            except Exception as exc:
                logger.info("Reddit RSS comment fetch failed for %s: %s", post.url, exc)
                result.errors.append(f"Could not fetch comments for {post.url}: {exc}")

    result.posts = posts
    return result


async def search_reddit_posts(
    query: str,
    *,
    sort: str = "new",
    limit: int = DEFAULT_POST_LIMIT,
    include_comments: bool = False,
    comments_limit: int = 0,
    max_requests_per_call: int = DEFAULT_MAX_REQUESTS_PER_CALL,
    proxy_url: Optional[str] = None,
) -> RedditRssResult:
    """Search public Reddit posts through Reddit's RSS search endpoint."""
    search_query = (query or "").strip()
    if not search_query:
        return RedditRssResult(page="", sort=sort, errors=["Reddit search requires a query."])

    post_limit = max(1, min(limit, MAX_POST_LIMIT))
    normalized_sort = _normalize_search_sort(sort)
    result = RedditRssResult(page=search_query, sort=normalized_sort)
    search_url = _search_feed_url(search_query, normalized_sort, post_limit)
    try:
        response = await _fetch_text_with_retry(
            search_url,
            max_inline_wait_seconds=MAX_INLINE_RATE_LIMIT_WAIT_SECONDS,
            proxy_url=proxy_url,
        )
        result.request_count += 1
        result.rate_limit = response.rate_limit
        result.posts = [
            post
            for post in _parse_post_feed(response.text, search_query)
            if "/comments/" in urllib.parse.urlparse(post.url).path
        ][:post_limit]
        if include_comments and comments_limit > 0:
            comment_limit = max(0, min(comments_limit, MAX_COMMENT_LIMIT))
            request_budget = max(1, max_requests_per_call)
            for index, post in enumerate(result.posts):
                if result.request_count >= request_budget:
                    skipped = len(result.posts) - index
                    result.comments_skipped_count += skipped
                    result.warnings.append(
                        f"Skipped comments for {skipped} posts because the per-call Reddit request budget was reached."
                    )
                    break
                try:
                    comment_response = await _fetch_text_with_retry(
                        _post_comments_feed_url(post.url, comment_limit),
                        max_inline_wait_seconds=MAX_INLINE_RATE_LIMIT_WAIT_SECONDS,
                        proxy_url=proxy_url,
                    )
                    result.request_count += 1
                    result.rate_limit = comment_response.rate_limit
                    post.comments = _parse_comment_feed(comment_response.text, post.url)[:comment_limit]
                    post.fetched_comment_count = len(post.comments)
                except _RedditRssRateLimitError as exc:
                    skipped = len(result.posts) - index
                    result.rate_limited = True
                    result.next_retry_after_seconds = exc.retry_after_seconds
                    result.rate_limit = exc.rate_limit
                    result.comments_skipped_count += skipped
                    result.warnings.append(
                        f"Skipped comments for {skipped} posts because Reddit is rate limited."
                    )
                    break
                except Exception as exc:
                    logger.info("Reddit RSS search comment fetch failed for %s: %s", post.url, exc)
                    result.errors.append(f"Could not fetch comments for {post.url}: {exc}")
    except _RedditRssRateLimitError as exc:
        logger.warning("Reddit RSS search rate limited for %s: %s", search_query, exc)
        result.rate_limited = True
        result.next_retry_after_seconds = exc.retry_after_seconds
        result.rate_limit = exc.rate_limit
        result.warnings.append("Reddit rate limit reached before completing search.")
    except Exception as exc:
        logger.warning("Reddit RSS search failed for %s: %s", search_query, exc)
        result.errors.append(f"Could not search Reddit for {search_query}: {exc}")
    return result


class _FetchResponse(BaseModel):
    text: str
    rate_limit: RedditRateLimit


class _RedditRssHttpError(RuntimeError):
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


class _RedditRssRateLimitError(_RedditRssHttpError):
    pass


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/rss+xml, text/xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


async def _fetch_text(url: str, *, proxy_url: Optional[str] = None) -> _FetchResponse:
    return await asyncio.to_thread(_fetch_text_sync, url, proxy_url)


async def _fetch_text_with_retry(
    url: str,
    *,
    max_inline_wait_seconds: float,
    proxy_url: Optional[str] = None,
) -> _FetchResponse:
    for attempt in range(1, MAX_429_RETRIES + 1):
        try:
            return await _fetch_text(url, proxy_url=proxy_url)
        except _RedditRssRateLimitError as exc:
            if attempt >= MAX_429_RETRIES:
                raise

            wait_seconds = exc.retry_after_seconds or DEFAULT_429_RETRY_DELAY_SECONDS
            if wait_seconds > max_inline_wait_seconds:
                raise

            logger.info(
                "Reddit RSS rate limited for %s; retrying in %.1fs (attempt %s/%s)",
                url,
                wait_seconds,
                attempt,
                MAX_429_RETRIES,
            )
            await asyncio.sleep(wait_seconds)

    raise RuntimeError("Reddit RSS retry loop exited unexpectedly")  # pragma: no cover


def _fetch_text_sync(url: str, proxy_url: Optional[str] = None) -> _FetchResponse:
    request = urllib.request.Request(url, headers=_headers())
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})) if proxy_url else None
        open_request = opener.open if opener else urllib.request.urlopen
        with open_request(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return _FetchResponse(
                text=raw.decode(charset, errors="replace"),
                rate_limit=_parse_rate_limit(response.headers),
            )
    except urllib.error.HTTPError as exc:
        rate_limit = _parse_rate_limit(exc.headers)
        retry_after = _parse_retry_after_seconds(exc.headers, rate_limit)
        body = exc.read().decode("utf-8", errors="replace")[:160]
        message = f"HTTP {exc.code} for {url}: {body}"
        if exc.code == 429:
            raise _RedditRssRateLimitError(
                message,
                status_code=exc.code,
                rate_limit=rate_limit,
                retry_after_seconds=retry_after,
            ) from exc
        raise _RedditRssHttpError(
            message,
            status_code=exc.code,
            rate_limit=rate_limit,
            retry_after_seconds=retry_after,
        ) from exc


def _normalize_subreddit(page: str) -> str:
    cleaned = (page or "").strip().removeprefix("r/").strip("/")
    if not cleaned:
        raise ValueError("Reddit page/subreddit is required.")
    return cleaned


def _normalize_sort(sort: str) -> str:
    normalized = (sort or "new").strip().lower()
    if normalized not in {"new", "hot", "rising", "top"}:
        raise ValueError("Reddit RSS sort must be one of: new, hot, rising, top.")
    return normalized


def _normalize_search_sort(sort: str) -> str:
    normalized = (sort or "new").strip().lower()
    if normalized == "latest":
        return "new"
    if normalized not in {"new", "hot", "top", "comments", "relevance"}:
        return "new"
    return normalized


def _subreddit_feed_url(subreddit: str, sort: str, limit: int) -> str:
    encoded_subreddit = urllib.parse.quote(subreddit, safe="")
    return f"{REDDIT_BASE_URL}/r/{encoded_subreddit}/{sort}/.rss?limit={limit}"


def _search_feed_url(query: str, sort: str, limit: int) -> str:
    encoded_query = urllib.parse.urlencode({"q": query, "sort": sort, "limit": limit})
    return f"{REDDIT_BASE_URL}/search.rss?{encoded_query}"


def _post_comments_feed_url(post_url: str, limit: int) -> str:
    parsed = urllib.parse.urlparse(post_url)
    encoded_path = urllib.parse.quote(parsed.path, safe="/:")
    return f"{REDDIT_BASE_URL}{encoded_path}.rss?limit={limit}&sort=top"


def _parse_post_feed(xml_text: str, subreddit: str) -> list[RedditRssPost]:
    root = ET.fromstring(xml_text)
    posts: list[RedditRssPost] = []
    for entry in root.findall("atom:entry", ATOM_NAMESPACE):
        url = _entry_url(entry)
        path_parts = urllib.parse.urlparse(url).path.rstrip("/").split("/")
        post_id = path_parts[-2] if "comments" in path_parts else path_parts[-1]
        posts.append(
            RedditRssPost(
                id=post_id,
                page=subreddit,
                title=_entry_text(entry, "title"),
                body=_clean_reddit_text(_entry_text(entry, "content")),
                author=_entry_author(entry),
                url=url,
                published_at=_normalize_datetime(_entry_text(entry, "updated")),
            )
        )
    return posts


def _parse_comment_feed(xml_text: str, post_url: str) -> list[RedditRssComment]:
    root = ET.fromstring(xml_text)
    post_path = urllib.parse.urlparse(post_url).path.rstrip("/")
    comments: list[RedditRssComment] = []
    for entry in root.findall("atom:entry", ATOM_NAMESPACE):
        url = _entry_url(entry)
        if urllib.parse.urlparse(url).path.rstrip("/") == post_path:
            continue
        author = _entry_author(entry)
        if author in IGNORED_COMMENT_AUTHORS:
            continue
        body = _clean_reddit_text(_entry_text(entry, "content"))
        if not body:
            continue
        comments.append(
            RedditRssComment(
                id=urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1],
                author=author,
                body=body,
                url=url,
                published_at=_normalize_datetime(_entry_text(entry, "updated")),
            )
        )
    return comments


def _entry_text(entry: ET.Element, field: str) -> str:
    element = entry.find(f"atom:{field}", ATOM_NAMESPACE)
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _entry_url(entry: ET.Element) -> str:
    link = entry.find("atom:link", ATOM_NAMESPACE)
    if link is None:
        return ""
    return link.attrib.get("href", "")


def _entry_author(entry: ET.Element) -> Optional[str]:
    name = entry.find("atom:author/atom:name", ATOM_NAMESPACE)
    if name is None or name.text is None:
        return None
    return name.text.strip() or None


def _clean_reddit_text(value: str) -> str:
    text = html.unescape(value or "")
    if "<" in text and ">" in text:
        parser = _HtmlTextExtractor()
        parser.feed(text)
        text = parser.text()
    text = _normalize_whitespace(text)
    if " submitted by /u/" in text:
        text = text.split(" submitted by /u/", 1)[0]
    return text


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_datetime(value: str) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_rate_limit(headers: object) -> RedditRateLimit:
    return RedditRateLimit(
        used=_header_float(headers, "x-ratelimit-used"),
        remaining=_header_float(headers, "x-ratelimit-remaining"),
        reset_seconds=_header_float(headers, "x-ratelimit-reset"),
    )


def _remaining_too_low(rate_limit: Optional[RedditRateLimit], threshold: float) -> bool:
    if rate_limit is None or rate_limit.remaining is None:
        return False
    return rate_limit.remaining <= threshold


def _parse_retry_after_seconds(headers: object, rate_limit: RedditRateLimit) -> Optional[float]:
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    if retry_after:
        try:
            return max(float(retry_after), 0.1)
        except (TypeError, ValueError):
            try:
                retry_dt = parsedate_to_datetime(retry_after)
                if retry_dt.tzinfo is None:
                    retry_dt = retry_dt.replace(tzinfo=timezone.utc)
                return max((retry_dt - datetime.now(timezone.utc)).total_seconds(), 0.1)
            except (TypeError, ValueError):
                pass

    if rate_limit.reset_seconds is not None:
        return max(rate_limit.reset_seconds, 0.1)
    return None


def _header_float(headers: object, name: str) -> Optional[float]:
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
