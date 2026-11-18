"""Explicit Gemini context caching for the Google AI Studio main chat request.

Implicit caching never hits for Gemini 3.8 Flash, so the stable prompt prefix
(system prefix + tools + tool_config) is stored in a Gemini ``cachedContent``
and reused. Cached input is billed at the cache-read rate through the existing
``cached_content_token_count`` -> ``cache_read_input_tokens`` mapping; cache
creation/storage is platform cost and only logged.

Rules that shape this module:
- The API forbids ``system_instruction``, ``tools`` and ``tool_config`` in a
  request that uses ``cached_content``. On a hit those move into the cache and
  the volatile system-prompt suffix becomes the first user-role content.
- No latency on the critical path: a Redis lookup only. A miss sends the normal
  request and creates the cache in a background task, guarded by a Redis
  ``SET NX`` lock so concurrent requests do not create duplicates.
- A missing/expired cache is a real-error recovery path: drop the registry entry
  and retry once without cache.
Prompt text is never logged; cache names only as short hashes.
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from google.genai import errors as google_errors
from google.genai import types
from redis import exceptions as redis_exceptions

from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

# Gemini's explicit-cache minimum is ~4096 tokens; ~4 chars/token, conservative.
MIN_CACHEABLE_CHARS = 16_000
CACHE_TTL_SECONDS = 900
REGISTRY_TTL_SECONDS = 840
CREATE_LOCK_TTL_SECONDS = 60
SUFFIX_CONTEXT_LABEL = "System context for this turn:"
_KEY_PREFIX = "gemini_ctx_cache:v1:"

_cache_service: Optional[CacheService] = None
_background_tasks: "set[asyncio.Task]" = set()


@dataclass
class CachePlan:
    """Outcome of the per-request cache decision."""

    status: str  # hit | miss_creating | miss_locked | skipped
    reason: str = ""
    cached_chars: int = 0
    key: Optional[str] = None
    cached_content_name: Optional[str] = None
    suffix: str = ""
    create_args: dict = field(default_factory=dict)

    @property
    def is_hit(self) -> bool:
        return self.status == "hit" and bool(self.cached_content_name)


def _redis_service() -> CacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _dump_tools(google_tools: Optional[List[Any]]) -> list:
    return [
        t.model_dump(mode="json", exclude_none=True) if hasattr(t, "model_dump") else t
        for t in (google_tools or [])
    ]


def compute_cache_key(model_id: str, cached_text: str, google_tools: Optional[List[Any]],
                      tool_config: Optional[dict]) -> str:
    material = _canonical([model_id, cached_text, _dump_tools(google_tools), tool_config or {}])
    return _KEY_PREFIX + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _log_status(model_id: str, plan: CachePlan) -> None:
    logger.info("GEMINI_EXPLICIT_CACHE model=%s status=%s reason=%s cached_chars=%d",
                model_id, plan.status, plan.reason or "-", plan.cached_chars)


def _decode(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


async def plan_request(
    *, model_id: str, system_prompt: Optional[str], cacheable_system_prefix: Optional[str],
    google_tools: Optional[List[Any]], tool_config: Optional[dict],
) -> CachePlan:
    """Decide hit / background-create / skip for one request. Never raises."""
    plan = _plan(model_id, system_prompt, cacheable_system_prefix, google_tools, tool_config)
    if plan.status == "skipped" or plan.key is None:
        _log_status(model_id, plan)
        return plan
    try:
        client = await _redis_service().client
        if client is None:
            plan = CachePlan(status="skipped", reason="redis_unavailable", cached_chars=plan.cached_chars)
        else:
            name = _decode(await client.get(plan.key))
            if name:
                plan.status, plan.cached_content_name = "hit", name
            elif await client.set(plan.key + ":lock", "1", ex=CREATE_LOCK_TTL_SECONDS, nx=True):
                plan.status = "miss_creating"
            else:
                plan.status = "miss_locked"
    except (redis_exceptions.RedisError, OSError) as exc:
        logger.warning("GEMINI_EXPLICIT_CACHE redis error during lookup: %s", exc)
        plan = CachePlan(status="skipped", reason="redis_error", cached_chars=plan.cached_chars)
    _log_status(model_id, plan)
    return plan


def _plan(model_id: str, system_prompt: Optional[str], prefix: Optional[str],
          google_tools: Optional[List[Any]], tool_config: Optional[dict]) -> CachePlan:
    if not prefix or not system_prompt:
        return CachePlan(status="skipped", reason="no_prefix")
    if not system_prompt.startswith(prefix):
        return CachePlan(status="skipped", reason="prefix_mismatch")
    if len(prefix) < MIN_CACHEABLE_CHARS:
        return CachePlan(status="skipped", reason="below_threshold", cached_chars=len(prefix))
    return CachePlan(
        status="pending", cached_chars=len(prefix), suffix=system_prompt[len(prefix):],
        key=compute_cache_key(model_id, prefix, google_tools, tool_config),
        create_args={"model": model_id, "system_instruction": prefix,
                     "tools": google_tools, "tool_config": tool_config},
    )


def build_hit_request(config: Any, contents: List[Any], plan: CachePlan) -> Tuple[Any, List[Any]]:
    """Config/contents for a cache hit: instructions and tools live in the cache."""
    hit_config = config.model_copy(update={
        "system_instruction": None, "tools": None, "tool_config": None,
        "cached_content": plan.cached_content_name,
    })
    hit_contents = list(contents)
    if plan.suffix.strip():
        hit_contents.insert(0, types.Content(role="user", parts=[
            types.Part(text=f"{SUFFIX_CONTEXT_LABEL}\n{plan.suffix.strip()}")]))
    return hit_config, hit_contents


def is_cached_content_missing(error: Exception) -> bool:
    """True when the provider rejected the request because the cache is gone."""
    if not isinstance(error, google_errors.APIError):
        return False
    code = getattr(error, "code", None)
    text = str(error).lower()
    return code in (400, 403, 404) and ("cachedcontent" in text.replace(" ", "")
                                        or "cached content" in text or "cached_content" in text)


async def drop_entry(plan: CachePlan) -> None:
    """Forget a registry entry whose provider-side cache is missing/expired."""
    if not plan.key:
        return
    try:
        client = await _redis_service().client
        if client is not None:
            await client.delete(plan.key)
    except (redis_exceptions.RedisError, OSError) as exc:
        logger.warning("GEMINI_EXPLICIT_CACHE could not drop registry entry: %s", exc)
    logger.warning("GEMINI_EXPLICIT_CACHE_EXPIRED name_hash=%s; retrying once without cache",
                   _short_hash(plan.cached_content_name or ""))


def schedule_create(
    plan: CachePlan,
    get_client: Callable[[], Awaitable[Tuple[Any, Any]]],
    close_client: Callable[[Any, Any], Awaitable[None]],
) -> Optional["asyncio.Task"]:
    """Fire-and-forget cache creation when this request won the create lock."""
    if plan.status != "miss_creating" or not plan.key:
        return None
    task = asyncio.create_task(_create_cache(plan, get_client, close_client))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _create_cache(plan: CachePlan, get_client, close_client) -> None:
    started = time.monotonic()
    args = plan.create_args
    client = session = None
    try:
        client, session = await get_client()
        cfg = types.CreateCachedContentConfig(
            system_instruction=args["system_instruction"], tools=args["tools"],
            tool_config=types.ToolConfig(**args["tool_config"]) if args["tool_config"] else None,
            ttl=f"{CACHE_TTL_SECONDS}s",
        )
        created = await client.aio.caches.create(model=args["model"], config=cfg)
        name = getattr(created, "name", None)
        if not name:
            logger.warning("GEMINI_EXPLICIT_CACHE create returned no name model=%s", args["model"])
            return
        redis_client = await _redis_service().client
        if redis_client is not None:
            await redis_client.set(plan.key, name, ex=REGISTRY_TTL_SECONDS)
        usage = getattr(created, "usage_metadata", None)
        logger.info("GEMINI_EXPLICIT_CACHE_CREATED model=%s name_hash=%s ms=%d cached_tokens=%s",
                    args["model"], _short_hash(name), int((time.monotonic() - started) * 1000),
                    getattr(usage, "total_token_count", None))
    except (google_errors.APIError, redis_exceptions.RedisError, OSError, ValueError) as exc:
        logger.warning("GEMINI_EXPLICIT_CACHE_CREATE_FAILED model=%s error=%s", args.get("model"), exc)
    finally:
        if client is not None:
            await close_client(client, session)
