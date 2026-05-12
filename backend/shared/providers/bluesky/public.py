"""
backend/shared/providers/bluesky/public.py

Public Bluesky provider for read-only social listening. Uses the official
public AppView API for profile feeds and post search without requiring user
credentials for profile feeds. Topic search can use Vault-backed Bluesky app
password credentials when the public AppView rejects unauthenticated search.
The provider normalizes AppView post views into a compact schema shared by the
Social Media app.

Architecture: docs/architecture/apps/social-media.md
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

BLUESKY_PUBLIC_API_BASE_URL = "https://public.api.bsky.app"
BLUESKY_PDS_BASE_URL = "https://bsky.social"
USER_AGENT = "OpenMates/0.1 social-media-get-posts"
REQUEST_TIMEOUT_SECONDS = 20.0
DEFAULT_POST_LIMIT = 10
MAX_POST_LIMIT = 25
AUTHOR_FEED_FILTER = "posts_with_replies"
BLUESKY_VAULT_PATH = "kv/data/providers/bluesky"
IDENTIFIER_VAULT_KEY = "identifier"
APP_PASSWORD_VAULT_KEY = "app_password"
IDENTIFIER_ENV_VAR = "SECRET__BLUESKY__IDENTIFIER"
APP_PASSWORD_ENV_VAR = "SECRET__BLUESKY__APP_PASSWORD"


class BlueskyPost(BaseModel):
    """A normalized Bluesky post returned by public AppView endpoints."""

    id: str = Field(description="AT URI for the post.")
    platform: str = Field(default="bluesky")
    page: str = Field(description="Actor handle for profile feeds or search query for topic search.")
    title: str = Field(description="Short display title for the post.")
    body: str = Field(default="", description="Post text.")
    author: Optional[str] = Field(default=None, description="Bluesky handle.")
    author_display_name: Optional[str] = None
    author_avatar_url: Optional[str] = None
    url: str = Field(description="Canonical bsky.app post URL when derivable.")
    published_at: Optional[str] = Field(default=None, description="Post creation timestamp.")
    indexed_at: Optional[str] = Field(default=None, description="AppView indexing timestamp.")
    reply_count: int = 0
    repost_count: int = 0
    like_count: int = 0
    quote_count: int = 0
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    external_url: Optional[str] = None
    external_title: Optional[str] = None
    comments: list[Any] = Field(default_factory=list)
    fetched_comment_count: int = 0


class BlueskyResult(BaseModel):
    """Result from a Bluesky public AppView request."""

    platform: str = Field(default="bluesky")
    page: str
    sort: str
    posts: list[BlueskyPost] = Field(default_factory=list)
    provider: str = Field(default="bluesky_public")
    request_count: int = 0
    cursor: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


async def fetch_author_posts(
    page: str,
    *,
    limit: int = DEFAULT_POST_LIMIT,
    filter: str = AUTHOR_FEED_FILTER,
) -> BlueskyResult:
    """Fetch recent public posts from a Bluesky actor handle or DID."""
    actor = _normalize_actor(page)
    result = BlueskyResult(page=actor, sort="profile")
    if not actor:
        result.errors.append("Bluesky profile fetch requires a page/actor handle.")
        return result

    params = {
        "actor": actor,
        "limit": str(_normalize_limit(limit)),
        "filter": filter,
    }
    try:
        payload = await _fetch_json("/xrpc/app.bsky.feed.getAuthorFeed", params)
        result.request_count = 1
        result.cursor = payload.get("cursor")
        result.posts = [
            _post_from_view(item.get("post") or {}, page=actor)
            for item in payload.get("feed", [])
            if isinstance(item, dict) and isinstance(item.get("post"), dict)
        ]
    except Exception as exc:
        logger.warning("Bluesky author feed fetch failed for %s: %s", actor, exc)
        result.errors.append(f"Could not fetch Bluesky profile {actor}: {exc}")
    return result


async def search_posts(
    query: str,
    *,
    sort: str = "latest",
    limit: int = DEFAULT_POST_LIMIT,
    author: Optional[str] = None,
    secrets_manager: Optional["SecretsManager"] = None,
) -> BlueskyResult:
    """Search public Bluesky posts around a topic."""
    normalized_query = query.strip()
    result = BlueskyResult(page=normalized_query, sort=_normalize_search_sort(sort))
    if not normalized_query:
        result.errors.append("Bluesky topic search requires a query.")
        return result

    params = {
        "q": normalized_query,
        "sort": result.sort,
        "limit": str(_normalize_limit(limit)),
    }
    if author:
        params["author"] = _normalize_actor(author)

    access_token = await _optional_access_token(secrets_manager=secrets_manager)
    try:
        payload = await _fetch_json(
            "/xrpc/app.bsky.feed.searchPosts",
            params,
            base_url=BLUESKY_PDS_BASE_URL if access_token else BLUESKY_PUBLIC_API_BASE_URL,
            access_token=access_token,
        )
        result.request_count = 1
        result.cursor = payload.get("cursor")
        result.posts = [
            _post_from_view(post, page=normalized_query)
            for post in payload.get("posts", [])
            if isinstance(post, dict)
        ]
    except Exception as exc:
        logger.warning("Bluesky post search failed for %s: %s", normalized_query, exc)
        result.errors.append(f"Could not search Bluesky posts for {normalized_query}: {exc}")
        if not access_token:
            result.warnings.append(
                "Bluesky topic search may require authentication. Configure "
                f"{IDENTIFIER_ENV_VAR} and {APP_PASSWORD_ENV_VAR} with a Bluesky app password."
            )
    return result


async def _fetch_json(
    path: str,
    params: dict[str, str],
    *,
    base_url: str = BLUESKY_PUBLIC_API_BASE_URL,
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    url = f"{base_url}{path}?{urllib.parse.urlencode(params)}"
    return await asyncio.to_thread(_fetch_json_sync, url, access_token)


def _fetch_json_sync(url: str, access_token: Optional[str] = None) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc

async def _optional_access_token(
    secrets_manager: Optional["SecretsManager"] = None,
) -> Optional[str]:
    identifier = await _get_bluesky_secret(IDENTIFIER_VAULT_KEY, IDENTIFIER_ENV_VAR, secrets_manager)
    app_password = await _get_bluesky_secret(APP_PASSWORD_VAULT_KEY, APP_PASSWORD_ENV_VAR, secrets_manager)
    if not identifier or not app_password:
        return None
    return await asyncio.to_thread(_create_session_sync, identifier, app_password)


async def _get_bluesky_secret(
    vault_key: str,
    env_var: str,
    secrets_manager: Optional["SecretsManager"] = None,
) -> Optional[str]:
    if secrets_manager:
        try:
            value = await secrets_manager.get_secret(
                secret_path=BLUESKY_VAULT_PATH,
                secret_key=vault_key,
            )
            if value and value.strip():
                return value.strip()
        except Exception as exc:
            logger.warning(
                "Failed to retrieve Bluesky secret '%s' from Vault: %s. Falling back to env var.",
                vault_key,
                exc,
            )

    env_value = os.environ.get(env_var, "").strip()
    if env_value and env_value != "IMPORTED_TO_VAULT":
        return env_value
    return None


def _create_session_sync(identifier: str, app_password: str) -> str:
    payload = json.dumps({"identifier": identifier, "password": app_password}).encode("utf-8")
    request = urllib.request.Request(
        f"{BLUESKY_PDS_BASE_URL}/xrpc/com.atproto.server.createSession",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            session = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Bluesky auth failed with HTTP {exc.code}: {body[:300]}") from exc

    access_token = session.get("accessJwt")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Bluesky auth response did not include accessJwt.")
    return access_token


def _post_from_view(post: dict[str, Any], *, page: str) -> BlueskyPost:
    record = post.get("record") if isinstance(post.get("record"), dict) else {}
    author = post.get("author") if isinstance(post.get("author"), dict) else {}
    text = str(record.get("text") or "").strip()
    handle = str(author.get("handle") or "").strip() or None
    url = _post_url(post.get("uri"), handle)
    media_url, thumbnail_url, external_url, external_title = _extract_embed_summary(post.get("embed"))

    return BlueskyPost(
        id=str(post.get("uri") or ""),
        page=page,
        title=_title_from_text(text, handle),
        body=text,
        author=handle,
        author_display_name=author.get("displayName"),
        author_avatar_url=author.get("avatar"),
        url=url,
        published_at=record.get("createdAt"),
        indexed_at=post.get("indexedAt"),
        reply_count=int(post.get("replyCount") or 0),
        repost_count=int(post.get("repostCount") or 0),
        like_count=int(post.get("likeCount") or 0),
        quote_count=int(post.get("quoteCount") or 0),
        media_url=media_url,
        thumbnail_url=thumbnail_url,
        external_url=external_url,
        external_title=external_title,
    )


def _extract_embed_summary(embed: Any) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    if not isinstance(embed, dict):
        return None, None, None, None

    images = embed.get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        image = images[0]
        fullsize = image.get("fullsize")
        thumb = image.get("thumb")
        return fullsize, thumb, None, None

    external = embed.get("external")
    if isinstance(external, dict):
        return None, external.get("thumb"), external.get("uri"), external.get("title")

    return None, None, None, None


def _post_url(uri: Any, handle: Optional[str]) -> str:
    if not isinstance(uri, str) or not uri:
        return ""
    record_key = uri.rstrip("/").split("/")[-1]
    actor = handle or uri.removeprefix("at://").split("/")[0]
    if not actor or not record_key:
        return ""
    return f"https://bsky.app/profile/{actor}/post/{record_key}"


def _title_from_text(text: str, handle: Optional[str]) -> str:
    prefix = f"@{handle}: " if handle else ""
    compact = " ".join(text.split())
    if not compact:
        return f"{prefix}Bluesky post".strip()
    return f"{prefix}{compact[:80]}".strip()


def _normalize_actor(actor: str) -> str:
    actor = actor.strip()
    if actor.startswith("@"):
        actor = actor[1:]
    if actor.startswith("https://bsky.app/profile/"):
        actor = actor.removeprefix("https://bsky.app/profile/").split("/")[0]
    return actor


def _normalize_limit(limit: int) -> int:
    return max(1, min(limit, MAX_POST_LIMIT))


def _normalize_search_sort(sort: str) -> str:
    normalized = sort.lower().strip()
    if normalized in {"top", "hot"}:
        return "top"
    return "latest"
