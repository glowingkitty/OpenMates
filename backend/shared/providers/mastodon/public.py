"""
backend/shared/providers/mastodon/public.py

Public Mastodon provider for read-only social listening. Uses public account,
status, and context endpoints exposed by Mastodon instances without requiring
user credentials. It normalizes public statuses and direct replies into the
Social Media app's shared post/comment shape.

Architecture: docs/architecture/apps/social-media.md
"""

from __future__ import annotations

import asyncio
from html import unescape
import json
import logging
import re
from typing import Any, Optional
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

USER_AGENT = "OpenMates/0.1 social-media"
REQUEST_TIMEOUT_SECONDS = 20.0
DEFAULT_POST_LIMIT = 10
MAX_POST_LIMIT = 25
DEFAULT_SEARCH_INSTANCE = "mastodon.social"
MAX_SEARCH_INSTANCES = 5


class MastodonComment(BaseModel):
    """A normalized Mastodon reply from a status context."""

    id: str = Field(description="Mastodon status ID for the reply.")
    author: Optional[str] = Field(default=None, description="Public Mastodon acct.")
    author_display_name: Optional[str] = None
    body: str = Field(default="", description="Reply text with HTML removed.")
    url: str = Field(default="", description="Canonical Mastodon status URL.")
    published_at: Optional[str] = None
    like_count: int = 0
    reply_count: int = 0
    repost_count: int = 0


class MastodonPost(BaseModel):
    """A normalized Mastodon status returned by public API endpoints."""

    id: str = Field(description="Mastodon status ID.")
    platform: str = Field(default="mastodon")
    page: str = Field(description="Normalized Mastodon account identifier.")
    title: str = Field(description="Short display title for the status.")
    body: str = Field(default="", description="Status text with HTML removed.")
    author: Optional[str] = Field(default=None, description="Public Mastodon acct.")
    author_display_name: Optional[str] = None
    author_avatar_url: Optional[str] = None
    url: str = Field(default="", description="Canonical Mastodon status URL.")
    published_at: Optional[str] = None
    reply_count: int = 0
    repost_count: int = 0
    like_count: int = 0
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    external_url: Optional[str] = None
    external_title: Optional[str] = None
    comments: list[MastodonComment] = Field(default_factory=list)
    fetched_comment_count: int = 0


class MastodonResult(BaseModel):
    """Result from a Mastodon public API request."""

    platform: str = Field(default="mastodon")
    page: str
    sort: str = Field(default="profile")
    posts: list[MastodonPost] = Field(default_factory=list)
    provider: str = Field(default="Mastodon")
    request_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


async def fetch_account_posts(
    page: str,
    *,
    limit: int = DEFAULT_POST_LIMIT,
    include_comments: bool = True,
    comments_limit: int = 5,
) -> MastodonResult:
    """Fetch recent public statuses from a Mastodon account."""
    account_ref = _parse_account_ref(page)
    result = MastodonResult(page=account_ref.label if account_ref else page.strip())
    if account_ref is None:
        result.errors.append("Mastodon requests require a profile URL or account in user@instance format.")
        return result

    try:
        account = await _fetch_json(
            account_ref.instance,
            "/api/v1/accounts/lookup",
            {"acct": account_ref.lookup_acct},
        )
        result.request_count += 1
        account_id = str(account.get("id") or "").strip()
        if not account_id:
            result.errors.append(f"Mastodon account lookup for {account_ref.label} did not return an account ID.")
            return result

        statuses = await _fetch_json(
            account_ref.instance,
            f"/api/v1/accounts/{urllib.parse.quote(account_id, safe='')}/statuses",
            {
                "limit": str(_normalize_limit(limit)),
                "exclude_replies": "false",
                "exclude_reblogs": "true",
            },
        )
        result.request_count += 1
        if not isinstance(statuses, list):
            result.errors.append(f"Mastodon statuses response for {account_ref.label} was not a list.")
            return result

        result.posts = [_post_from_status(status, page=account_ref.label) for status in statuses if isinstance(status, dict)]
        if include_comments:
            await _hydrate_post_comments(result, account_ref.instance, comments_limit=comments_limit)
    except Exception as exc:
        logger.warning("Mastodon profile fetch failed for %s: %s", account_ref.label, exc)
        result.errors.append(f"Could not fetch Mastodon profile {account_ref.label}: {exc}")
    return result


async def search_posts(
    query: str,
    *,
    instances: Optional[list[str]] = None,
    limit: int = DEFAULT_POST_LIMIT,
    include_comments: bool = False,
    comments_limit: int = 0,
) -> MastodonResult:
    """Search public statuses from mastodon.social and optional extra instances."""
    normalized_query = query.strip()
    search_instances = _normalize_search_instances(instances)
    result = MastodonResult(page=", ".join(search_instances), sort="latest")
    if not normalized_query:
        result.errors.append("Mastodon search requests require a query.")
        return result

    per_instance_limit = _normalize_limit(limit)
    seen_urls: set[str] = set()
    for instance in search_instances:
        try:
            payload = await _fetch_json(
                instance,
                "/api/v2/search",
                {
                    "q": normalized_query,
                    "type": "statuses",
                    "limit": str(per_instance_limit),
                    "resolve": "false",
                },
            )
            result.request_count += 1
            statuses = payload.get("statuses") if isinstance(payload, dict) else None
            if not isinstance(statuses, list):
                result.warnings.append(f"Mastodon search response from {instance} did not include statuses.")
                statuses = []
            post_count_before_instance = len(result.posts)
            for status in statuses:
                _append_search_status(result, status, instance=instance, seen_urls=seen_urls)
                if len(result.posts) >= per_instance_limit:
                    break
            if len(result.posts) >= per_instance_limit:
                break

            tag = _tag_from_query(normalized_query)
            if tag and len(result.posts) == post_count_before_instance:
                tag_statuses = await _fetch_json(
                    instance,
                    f"/api/v1/timelines/tag/{urllib.parse.quote(tag, safe='')}",
                    {"limit": str(per_instance_limit)},
                )
                result.request_count += 1
                if not isinstance(tag_statuses, list):
                    result.warnings.append(f"Mastodon tag timeline response from {instance} did not include statuses.")
                    continue
                for status in tag_statuses:
                    _append_search_status(result, status, instance=instance, seen_urls=seen_urls)
                    if len(result.posts) >= per_instance_limit:
                        break
        except Exception as exc:
            logger.warning("Mastodon search failed for %s on %s: %s", normalized_query, instance, exc)
            result.warnings.append(f"Could not search Mastodon instance {instance}: {exc}")
        if len(result.posts) >= per_instance_limit:
            break

    if include_comments:
        await _hydrate_search_post_comments(result, comments_limit=comments_limit)
    return result


def _append_search_status(
    result: MastodonResult,
    status: Any,
    *,
    instance: str,
    seen_urls: set[str],
) -> None:
    if not isinstance(status, dict):
        return
    post = _post_from_status(status, page=instance)
    dedupe_key = post.url or post.id
    if dedupe_key and dedupe_key in seen_urls:
        return
    if dedupe_key:
        seen_urls.add(dedupe_key)
    result.posts.append(post)


async def _hydrate_search_post_comments(result: MastodonResult, *, comments_limit: int) -> None:
    instances_by_post = {post.id: _instance_from_status_url(post.url) for post in result.posts}
    comment_limit = _normalize_comment_limit(comments_limit)
    if comment_limit <= 0:
        return
    for post in result.posts:
        instance = instances_by_post.get(post.id)
        if not instance or not post.id:
            continue
        try:
            context = await _fetch_json(instance, f"/api/v1/statuses/{urllib.parse.quote(post.id, safe='')}/context", {})
            result.request_count += 1
            descendants = context.get("descendants") if isinstance(context, dict) else []
            if not isinstance(descendants, list):
                descendants = []
            post.comments = [
                _comment_from_status(comment)
                for comment in descendants[:comment_limit]
                if isinstance(comment, dict)
            ]
            post.fetched_comment_count = len(post.comments)
        except Exception as exc:
            logger.info("Mastodon search context fetch failed for %s: %s", post.url or post.id, exc)
            result.warnings.append(f"Could not fetch Mastodon replies for {post.url or post.id}: {exc}")


async def _hydrate_post_comments(result: MastodonResult, instance: str, *, comments_limit: int) -> None:
    comment_limit = _normalize_comment_limit(comments_limit)
    if comment_limit <= 0:
        return
    for post in result.posts:
        if not post.id:
            continue
        try:
            context = await _fetch_json(instance, f"/api/v1/statuses/{urllib.parse.quote(post.id, safe='')}/context", {})
            result.request_count += 1
            descendants = context.get("descendants") if isinstance(context, dict) else []
            if not isinstance(descendants, list):
                descendants = []
            post.comments = [
                _comment_from_status(comment)
                for comment in descendants[:comment_limit]
                if isinstance(comment, dict)
            ]
            post.fetched_comment_count = len(post.comments)
        except Exception as exc:
            logger.info("Mastodon context fetch failed for %s: %s", post.url or post.id, exc)
            result.warnings.append(f"Could not fetch Mastodon replies for {post.url or post.id}: {exc}")


async def _fetch_json(instance: str, path: str, params: dict[str, str]) -> Any:
    return await asyncio.to_thread(_fetch_json_sync, instance, path, params)


def _fetch_json_sync(instance: str, path: str, params: dict[str, str]) -> Any:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"https://{instance}{path}{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc


class _AccountRef(BaseModel):
    instance: str
    lookup_acct: str
    label: str


def _parse_account_ref(page: str) -> Optional[_AccountRef]:
    value = page.strip()
    if not value:
        return None

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        instance = parsed.netloc.lower().strip()
        username = _username_from_path(parsed.path)
        if instance and username:
            return _AccountRef(instance=instance, lookup_acct=username, label=f"{username}@{instance}")
        return None

    normalized = value[1:] if value.startswith("@") else value
    if "@" not in normalized:
        return None
    username, instance = normalized.rsplit("@", 1)
    username = username.lstrip("@").strip()
    instance = instance.lower().strip()
    if not username or not instance or "." not in instance:
        return None
    return _AccountRef(instance=instance, lookup_acct=username, label=f"{username}@{instance}")


def _username_from_path(path: str) -> Optional[str]:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    first = parts[0]
    if first.startswith("@"):
        return first[1:]
    if first == "users" and len(parts) > 1:
        return parts[1]
    return None


def _normalize_search_instances(instances: Optional[list[str]]) -> list[str]:
    normalized = [DEFAULT_SEARCH_INSTANCE]
    for value in instances or []:
        instance = _normalize_instance(value)
        if instance and instance not in normalized:
            normalized.append(instance)
        if len(normalized) >= MAX_SEARCH_INSTANCES:
            break
    return normalized


def _normalize_instance(value: str) -> Optional[str]:
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("http://") or candidate.startswith("https://"):
        candidate = urllib.parse.urlparse(candidate).netloc
    candidate = candidate.strip().lower().split("/", 1)[0]
    if "@" in candidate:
        candidate = candidate.rsplit("@", 1)[-1]
    if "." not in candidate or any(char.isspace() for char in candidate):
        return None
    return candidate


def _tag_from_query(query: str) -> Optional[str]:
    candidate = query.strip().lstrip("#")
    candidate = re.sub(r"[^A-Za-z0-9_]", "", candidate)
    return candidate.lower() or None


def _instance_from_status_url(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    return _normalize_instance(parsed.netloc)


def _post_from_status(status: dict[str, Any], *, page: str) -> MastodonPost:
    account = status.get("account") if isinstance(status.get("account"), dict) else {}
    body = _clean_html(str(status.get("content") or ""))
    media_url, thumbnail_url = _extract_media(status.get("media_attachments"))
    card = status.get("card") if isinstance(status.get("card"), dict) else {}
    return MastodonPost(
        id=str(status.get("id") or ""),
        page=page,
        title=_title_from_text(body, _account_label(account)),
        body=body,
        author=_account_label(account),
        author_display_name=_clean_html(str(account.get("display_name") or "")) or None,
        author_avatar_url=account.get("avatar_static") or account.get("avatar"),
        url=str(status.get("url") or status.get("uri") or ""),
        published_at=status.get("created_at"),
        reply_count=int(status.get("replies_count") or 0),
        repost_count=int(status.get("reblogs_count") or 0),
        like_count=int(status.get("favourites_count") or 0),
        media_url=media_url,
        thumbnail_url=thumbnail_url,
        external_url=card.get("url"),
        external_title=card.get("title"),
    )


def _comment_from_status(status: dict[str, Any]) -> MastodonComment:
    account = status.get("account") if isinstance(status.get("account"), dict) else {}
    return MastodonComment(
        id=str(status.get("id") or ""),
        author=_account_label(account),
        author_display_name=_clean_html(str(account.get("display_name") or "")) or None,
        body=_clean_html(str(status.get("content") or "")),
        url=str(status.get("url") or status.get("uri") or ""),
        published_at=status.get("created_at"),
        like_count=int(status.get("favourites_count") or 0),
        reply_count=int(status.get("replies_count") or 0),
        repost_count=int(status.get("reblogs_count") or 0),
    )


def _account_label(account: dict[str, Any]) -> Optional[str]:
    acct = str(account.get("acct") or "").strip()
    return acct or None


def _extract_media(media: Any) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(media, list) or not media or not isinstance(media[0], dict):
        return None, None
    item = media[0]
    return item.get("url"), item.get("preview_url")


def _clean_html(value: str) -> str:
    with_breaks = re.sub(r"</(p|div|li)>\s*", "\n", value, flags=re.IGNORECASE)
    with_breaks = re.sub(r"<br\s*/?>", "\n", with_breaks, flags=re.IGNORECASE)
    without_tags = re.sub(r"<[^>]+>", "", with_breaks)
    lines = [" ".join(line.split()) for line in unescape(without_tags).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _title_from_text(text: str, author: Optional[str]) -> str:
    prefix = f"@{author}: " if author else ""
    compact = " ".join(text.split())
    if not compact:
        return f"{prefix}Mastodon post".strip()
    return f"{prefix}{compact[:80]}".strip()


def _normalize_limit(limit: int) -> int:
    return max(1, min(limit, MAX_POST_LIMIT))


def _normalize_comment_limit(limit: int) -> int:
    return max(0, min(limit, MAX_POST_LIMIT))
