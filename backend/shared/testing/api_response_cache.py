# backend/shared/testing/api_response_cache.py
# Fingerprinting and JSON file cache for external API responses.
#
# Provides record-and-replay caching for both LLM provider calls and skill HTTP
# requests. Responses are stored as human-readable JSON files, organized by
# group_id (test flow) and category (API provider).
#
# Fingerprinting ignores volatile fields (timestamps, API keys, request IDs)
# to ensure cache hits on semantically identical requests.
#
# Security: All cache files live in testing/ directories, never deployed to production.
#
# Architecture context: See docs/architecture/live-mock-testing.md

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Root directory for cached API responses
CACHE_ROOT = Path(__file__).resolve().parent.parent.parent / "apps" / "ai" / "testing" / "api_cache"

# Fields to strip from LLM call fingerprinting (volatile/auth data)
_LLM_IGNORE_KEYS = {
    "api_key", "api_base", "organization", "timeout", "max_retries",
    "request_id", "x-request-id", "created", "id", "system_fingerprint",
}

# Headers to strip from HTTP request fingerprinting
_HTTP_IGNORE_HEADERS = {
    "authorization", "x-api-key", "cookie", "set-cookie",
    "x-request-id", "x-trace-id", "date", "user-agent",
}


class MockCacheMiss(Exception):
    """Raised when no cached response exists and recording is disabled."""

    def __init__(self, category: str, fingerprint: str, details: str = ""):
        self.category = category
        self.fingerprint = fingerprint
        super().__init__(
            f"No cached response for {category}/{fingerprint}. "
            f"Run with TEST_LIVE_RECORD marker to record real API responses. {details}"
        )


class ApiResponseCache:
    """
    Cache for external API responses, organized by group and category.

    Storage layout:
        api_cache/{group_id}/{category}/{fingerprint}.json

    Each JSON file contains:
        - fingerprint: Hash of the request
        - category: API category (e.g., "llm/openai", "brave", "doctolib")
        - group_id: Test flow namespace
        - recorded_at: ISO timestamp
        - request: Human-readable request summary (for debugging)
        - response: Full response data (status, headers, body)
    """

    def __init__(self, root: Optional[Path] = None):
        self.root = root or CACHE_ROOT

    def _cache_dir(self, group_id: str, category: str) -> Path:
        """Get the cache directory for a given group and category."""
        # Sanitize category for filesystem (replace / with __)
        safe_category = category.replace("/", "__")
        return self.root / group_id / safe_category

    def _cache_path(self, group_id: str, category: str, fingerprint: str) -> Path:
        """Get the full path for a cached response file."""
        return self._cache_dir(group_id, category) / f"{fingerprint}.json"

    def load(self, group_id: str, category: str, fingerprint: str) -> Optional[Dict[str, Any]]:
        """
        Load a cached response by fingerprint.

        Returns:
            The cached response dict, or None if not found.
        """
        path = self._cache_path(group_id, category, fingerprint)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(
                f"[LiveMock] Cache HIT: {category}/{fingerprint} "
                f"(group={group_id}, recorded={data.get('recorded_at', '?')})"
            )
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[LiveMock] Failed to load cache {path}: {e}")
            return None

    def save(
        self,
        group_id: str,
        category: str,
        fingerprint: str,
        request_summary: Dict[str, Any],
        response_data: Dict[str, Any],
    ) -> Path:
        """
        Save an API response to the cache.

        Args:
            group_id: Test flow namespace
            category: API category (e.g., "llm/openai", "brave")
            fingerprint: Hash of the request
            request_summary: Human-readable request data (for debugging)
            response_data: Full response (status_code, headers, body)

        Returns:
            Path to the saved cache file.
        """
        cache_dir = self._cache_dir(group_id, category)
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_entry = {
            "fingerprint": fingerprint,
            "category": category,
            "group_id": group_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "request": request_summary,
            "response": response_data,
        }

        path = self._cache_path(group_id, category, fingerprint)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache_entry, f, indent=2, ensure_ascii=False, default=str)

        logger.info(
            f"[LiveMock] Cache SAVE: {category}/{fingerprint} "
            f"(group={group_id}, path={path})"
        )
        return path

    # ─── Fingerprinting ──────────────────────────────────────────────

    def fingerprint_llm_call(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        tool_choice: Optional[str] = None,
    ) -> str:
        """
        Generate a deterministic fingerprint for an LLM API call.

        Hashes model, message content, tools, and temperature. Ignores API keys,
        timestamps, request IDs, and other volatile fields.
        """
        # Build a canonical representation
        canonical = {
            "model": model,
            "messages": self._normalize_messages(messages),
            "temperature": temperature,
            "tool_choice": tool_choice,
        }
        if tools:
            canonical["tools"] = self._normalize_tools(tools)

        canonical_str = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:16]

    def fingerprint_http_request(
        self,
        method: str,
        url: str,
        body: Optional[Union[bytes, str, Dict]] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Generate a deterministic fingerprint for an HTTP request.

        Hashes method, URL path, query params, and request body.
        Ignores auth headers, cookies, user-agent, and other volatile fields.
        """
        from urllib.parse import urlparse, urlencode

        parsed = urlparse(url)

        canonical = {
            "method": method.upper(),
            "host": parsed.hostname or "",
            "path": parsed.path,
            "query": sorted((params or {}).items()) if params else parsed.query,
        }

        if body is not None:
            if isinstance(body, bytes):
                body_str = body.decode("utf-8", errors="replace")
            elif isinstance(body, dict):
                body_str = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
            else:
                body_str = str(body)

            # Try to parse as JSON and normalize for deterministic hashing
            try:
                body_parsed = json.loads(body_str)
                body_str = json.dumps(body_parsed, sort_keys=True, ensure_ascii=False, default=str)
            except (json.JSONDecodeError, TypeError):
                pass

            canonical["body_hash"] = hashlib.sha256(body_str.encode("utf-8")).hexdigest()

        canonical_str = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:16]

    # ─── Helpers ─────────────────────────────────────────────────────

    def _normalize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize messages for fingerprinting — keep role + content, strip metadata."""
        normalized = []
        for msg in messages:
            entry: Dict[str, Any] = {
                "role": msg.get("role", ""),
            }
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multi-modal content (text + images) — hash each part
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        part_copy = {k: v for k, v in part.items() if k not in _LLM_IGNORE_KEYS}
                        parts.append(part_copy)
                    else:
                        parts.append(part)
                entry["content"] = parts
            else:
                entry["content"] = content

            # Include tool calls if present (important for multi-turn with function calling)
            if "tool_calls" in msg:
                entry["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                entry["tool_call_id"] = msg["tool_call_id"]

            normalized.append(entry)
        return normalized

    def _normalize_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize tool definitions for fingerprinting."""
        normalized = []
        for tool in tools:
            if isinstance(tool, dict):
                # Keep function name and parameters, strip descriptions (which may vary)
                func = tool.get("function", {})
                entry = {
                    "type": tool.get("type", "function"),
                    "function": {
                        "name": func.get("name", ""),
                        "parameters": func.get("parameters", {}),
                    },
                }
                normalized.append(entry)
            else:
                normalized.append(tool)
        return normalized


# Singleton cache instance
_shared_cache: Optional[ApiResponseCache] = None


def get_shared_cache() -> ApiResponseCache:
    """Get or create the shared ApiResponseCache instance."""
    global _shared_cache
    if _shared_cache is None:
        _shared_cache = ApiResponseCache()
    return _shared_cache
