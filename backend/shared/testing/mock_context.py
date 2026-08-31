# backend/shared/testing/mock_context.py
# Per-request context variables and marker detection for live mock testing.
#
# The live mock system runs the full processing pipeline but intercepts external
# API calls (LLM providers, skill HTTP requests) with cached responses. Activation
# is per-request via markers in the user message, so real users on the same server
# are never affected.
#
# Markers:
#   <<<TEST_LIVE_MOCK:group_id>>>    — replay cached API responses (error if cache miss)
#   <<<TEST_LIVE_RECORD:group_id>>>  — call real APIs and record responses for replay
#
# Security: Disabled in production. Requires MOCK_EXTERNAL_APIS=true env var.
#
# Architecture context: See docs/architecture/live-mock-testing.md

import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple, Optional

import yaml

logger = logging.getLogger(__name__)

# Per-task context variables — only set when a TEST_LIVE_MOCK/RECORD marker is detected.
# These use contextvars so each Celery task has its own isolated mock state.
# Default is "off" — all API calls pass through to real providers unchanged.
mock_mode_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "live_mock_mode", default="off"
)
# Values: "off" (real APIs), "mock" (replay from cache), "record" (call real + save)

mock_group_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "live_mock_group", default=""
)
# Namespaces cached responses (e.g., "web_search_flow", "travel_search_flow")

mock_candidate_root_var: contextvars.ContextVar[Optional[Path]] = contextvars.ContextVar(
    "live_mock_candidate_root", default=None
)
# Recordings are isolated from committed cassettes until an explicit promotion step.

class LiveMarker(NamedTuple):
    """Validated, signed live-test marker with an optional candidate run."""

    mode: str
    group_id: str
    run_id: Optional[str]

DEFAULT_REAL_BUDGET_EUR = Decimal("0.25")
MAX_REAL_BUDGET_EUR = Decimal("0.25")
MAX_REAL_LLM_OUTPUT_TOKENS = 1200
USD_TO_EUR_SAFETY_MULTIPLIER = Decimal("1.25")
DAILY_REAL_GROUP_PREFIX = "daily_canary_"
DAILY_BACKFILL_RUN_PATTERN = re.compile(r"^daily-cache-backfill-([0-9]{8})-[a-f0-9]{12}$")


class DailyAITestBudgetExceeded(RuntimeError):
    """Raised before a real test provider call would exceed its budget."""


@dataclass
class _RealBudgetState:
    limit_eur: Decimal
    reserved_eur: Decimal = Decimal("0")
    provider_calls: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class _LiveMockReceiptState:
    mode: str
    run_id: Optional[str]
    task_id: Optional[str]
    cache_hits: int = 0
    cache_misses: int = 0
    real_provider_calls: int = 0


real_budget_state_var: contextvars.ContextVar[Optional[_RealBudgetState]] = contextvars.ContextVar(
    "daily_ai_real_budget_state", default=None
)
live_mock_receipt_var: contextvars.ContextVar[Optional[_LiveMockReceiptState]] = contextvars.ContextVar(
    "live_mock_receipt", default=None
)
_raw_http_guard_lock = threading.Lock()
_raw_http_guard_installed = False

# Regex to detect live mock/record markers in message text.
# Format: <<<TEST_LIVE_MOCK:group_id>>> or <<<TEST_LIVE_RECORD:group_id>>>
_LIVE_MARKER_PATTERN = re.compile(
    r"<<<TEST_LIVE_(MOCK|RECORD|REAL):([a-zA-Z0-9_-]+)"
    r"(?::([a-zA-Z][a-zA-Z0-9_-]{0,79}))?"
    r"(?::([0-9]+):([a-f0-9]{64}))?\s*>>>"
)


def detect_live_marker(content: str, user_id: Optional[str] = None) -> Optional[LiveMarker]:
    """
    Detect a TEST_LIVE_MOCK or TEST_LIVE_RECORD marker in message content.

    Returns:
        LiveMarker with mode, group_id, and optional candidate run identity.
            mode: "mock" or "record"
            group_id: identifier for namespacing cached responses
        Returns None if no marker found, or if in production, or if feature flag not set.
    """
    # SECURITY: Never honor markers in production
    if _is_production_environment():
        return None

    # Feature flag: MOCK_EXTERNAL_APIS must be explicitly enabled
    if os.getenv("MOCK_EXTERNAL_APIS") != "true":
        return None

    match = _LIVE_MARKER_PATTERN.search(content)
    if not match:
        return None

    mode = match.group(1).lower()  # "mock" or "record"
    group_id = match.group(2)
    run_id = match.group(3)
    expiry = match.group(4)
    signature = match.group(5)
    if not user_id or not expiry or not signature:
        return None
    if mode == "record" and not run_id:
        return None
    if int(expiry) < int(time.time()):
        return None
    expected = _live_marker_signature(mode, group_id, run_id, expiry, user_id)
    if not hmac.compare_digest(signature, expected):
        return None

    return LiveMarker(mode, group_id, run_id)


def strip_live_marker(content: str) -> str:
    """Remove the TEST_LIVE_MOCK/TEST_LIVE_RECORD marker from message content."""
    return _LIVE_MARKER_PATTERN.sub("", content).rstrip()


def sign_live_marker(
    marker: str,
    user_id: str,
    *,
    is_allowlisted_test_account: bool = False,
    ttl_seconds: int = 600,
) -> Optional[str]:
    """Sign a sanitized dev test marker for one authenticated account."""
    if _is_production_environment():
        return None
    if os.getenv("MOCK_EXTERNAL_APIS") != "true":
        return None
    if not is_allowlisted_test_account:
        return None
    match = _LIVE_MARKER_PATTERN.fullmatch(marker.strip())
    if not match:
        return None
    mode = match.group(1).lower()
    group_id = match.group(2)
    run_id = match.group(3)
    if mode == "real" and not _is_current_daily_real_group(group_id):
        return None
    if mode == "record" and not run_id:
        return None
    expiry = str(int(time.time()) + ttl_seconds)
    signature = _live_marker_signature(mode, group_id, run_id, expiry, user_id)
    run_segment = f":{run_id}" if run_id else ""
    return f"<<<TEST_LIVE_{mode.upper()}:{group_id}{run_segment}:{expiry}:{signature}>>>"


def _live_marker_signature(
    mode: str, group_id: str, run_id: Optional[str], expiry: str, user_id: str
) -> str:
    secret = os.getenv("DAILY_AI_TEST_CONTEXT_SECRET") or os.getenv("DRAGONFLY_PASSWORD")
    if not secret:
        raise RuntimeError("Daily AI test context signing secret is not configured")
    payload = f"{mode}:{group_id}:{run_id or ''}:{expiry}:{user_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def current_daily_real_group() -> str:
    return f"{DAILY_REAL_GROUP_PREFIX}{time.strftime('%Y%m%d', time.gmtime())}"


def _is_current_daily_real_group(group_id: str) -> bool:
    return group_id == current_daily_real_group()


def _is_production_environment() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "production").strip().lower() in {"production", "prod"}


def should_reject_disabled_live_marker(content: str) -> bool:
    """Fail closed only for non-production test controls without the provider boundary."""
    if _is_production_environment():
        return False
    return os.getenv("MOCK_EXTERNAL_APIS") != "true" and "<<<TEST_LIVE_" in content


def resolve_live_marker_or_raise(
    content: str,
    user_id: Optional[str] = None,
) -> Optional[LiveMarker]:
    """Return a valid signed live marker or fail closed for attempted live controls."""
    if _is_production_environment():
        return None
    if "<<<TEST_LIVE_" not in content:
        return None
    if os.getenv("MOCK_EXTERNAL_APIS") != "true":
        raise RuntimeError("TEST_LIVE marker requires MOCK_EXTERNAL_APIS=true")
    marker = detect_live_marker(content, user_id)
    if marker:
        return marker
    raise RuntimeError("Invalid or unauthorized TEST_LIVE marker")


def activate_mock_mode(
    mode: str,
    group_id: str,
    candidate_root: Optional[Path] = None,
    *,
    candidate_run_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> None:
    """
    Set context vars for current task. Call from ask_skill_task.py after marker detection.

    Args:
        mode: "mock" (replay), "record" (real API + save), or "real" (bounded real API)
        group_id: Namespace for cached responses
        candidate_root: Record task root or selected replay run root.
    """
    resolved_candidate_root = candidate_root.resolve() if candidate_root else None
    budget_state = _new_real_budget_state() if mode in {"record", "real"} else None
    _install_raw_http_guard_once()
    mock_mode_var.set(mode)
    mock_group_var.set(group_id)
    mock_candidate_root_var.set(resolved_candidate_root)
    real_budget_state_var.set(budget_state)
    live_mock_receipt_var.set(
        _LiveMockReceiptState(mode=mode, run_id=candidate_run_id, task_id=task_id)
    )
    logger.info(
        f"[LiveMock] Activated: mode={mode}, group={group_id}"
    )


def deactivate_mock_mode() -> None:
    """Reset context vars. Call at end of task to clean up."""
    mock_mode_var.set("off")
    mock_group_var.set("")
    mock_candidate_root_var.set(None)
    real_budget_state_var.set(None)
    live_mock_receipt_var.set(None)


def is_mock_active() -> bool:
    """Check if live mock mode is active for the current task."""
    return mock_mode_var.get() != "off"


def is_record_mode() -> bool:
    """Check if we're in record mode (call real APIs and save responses)."""
    return mock_mode_var.get() == "record"


def is_real_mode() -> bool:
    """Check if this is a bounded real-provider daily canary request."""
    return mock_mode_var.get() == "real"


def get_mock_group() -> str:
    """Get the current mock group ID for cache namespacing."""
    return mock_group_var.get()


def get_record_candidate_root() -> Optional[Path]:
    """Get the request-scoped root used to isolate recorded cassettes."""
    return mock_candidate_root_var.get()


def get_replay_candidate_root() -> Optional[Path]:
    """Return an explicitly selected candidate-run root for mock replay."""
    return mock_candidate_root_var.get() if mock_mode_var.get() == "mock" else None


def record_cache_hit() -> None:
    state = live_mock_receipt_var.get()
    if state is not None:
        state.cache_hits += 1


def record_cache_miss() -> None:
    state = live_mock_receipt_var.get()
    if state is not None:
        state.cache_misses += 1


def record_real_provider_call() -> None:
    state = live_mock_receipt_var.get()
    if state is not None:
        state.real_provider_calls += 1


def get_live_mock_receipt() -> dict[str, Any]:
    """Return content-free counters for the active live-test task."""
    state = live_mock_receipt_var.get()
    budget = get_real_budget_summary()
    if state is None:
        return {
            "mode": "off",
            "run_id": None,
            "task_id": None,
            "cache_hits": 0,
            "cache_misses": 0,
            "real_provider_calls": 0,
        }
    return {
        "mode": state.mode,
        "run_id": state.run_id,
        "task_id": state.task_id,
        "cache_hits": state.cache_hits,
        "cache_misses": state.cache_misses,
        "real_provider_calls": state.real_provider_calls,
        "estimated_eur": budget.get("reserved_eur", 0.0),
    }


def write_live_mock_receipt() -> Optional[Path]:
    """Persist one content-free receipt under the selected candidate run."""
    state = live_mock_receipt_var.get()
    root = mock_candidate_root_var.get()
    if state is None or root is None or not state.run_id or not state.task_id:
        return None
    run_root = root.parent
    receipt_dir = run_root / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{state.task_id}.json"
    temporary_path = receipt_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(get_live_mock_receipt(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary_path.replace(receipt_path)
    return receipt_path


def _install_raw_http_guard_once() -> None:
    """Reject raw HTTP transports while a live test context is active."""
    global _raw_http_guard_installed
    if _raw_http_guard_installed:
        return
    with _raw_http_guard_lock:
        if _raw_http_guard_installed:
            return
        _install_httpx_transport_guard()
        _install_aiohttp_request_guard()
        _install_requests_request_guard()
        _raw_http_guard_installed = True


def _install_httpx_transport_guard() -> None:
    try:
        import httpx
    except ModuleNotFoundError:
        return
    if getattr(httpx.AsyncHTTPTransport.handle_async_request, "_openmates_live_guard", False):
        return

    original_async = httpx.AsyncHTTPTransport.handle_async_request
    original_sync = httpx.HTTPTransport.handle_request

    async def guarded_async(transport: Any, request: Any) -> Any:
        if is_mock_active():
            raise DailyAITestBudgetExceeded(_raw_http_guard_message(request))
        return await original_async(transport, request)

    def guarded_sync(transport: Any, request: Any) -> Any:
        if is_mock_active():
            raise DailyAITestBudgetExceeded(_raw_http_guard_message(request))
        return original_sync(transport, request)

    guarded_async._openmates_live_guard = True
    guarded_sync._openmates_live_guard = True
    httpx.AsyncHTTPTransport.handle_async_request = guarded_async
    httpx.HTTPTransport.handle_request = guarded_sync


def _install_aiohttp_request_guard() -> None:
    try:
        import aiohttp
    except ModuleNotFoundError:
        return
    client_session = getattr(aiohttp, "ClientSession", None)
    original_request = getattr(client_session, "_request", None)
    if original_request is None:
        return
    if getattr(original_request, "_openmates_live_guard", False):
        return

    async def guarded_request(session: Any, method: Any, url: Any, **kwargs: Any) -> Any:
        if is_mock_active():
            raise DailyAITestBudgetExceeded(_raw_http_guard_message(method, url))
        return await original_request(session, method, url, **kwargs)

    guarded_request._openmates_live_guard = True
    aiohttp.ClientSession._request = guarded_request


def _install_requests_request_guard() -> None:
    try:
        import requests
    except ModuleNotFoundError:
        return
    session = getattr(getattr(requests, "sessions", None), "Session", None)
    original_request = getattr(session, "request", None)
    original_send = getattr(session, "send", None)
    if original_request is None or original_send is None:
        return
    if getattr(original_request, "_openmates_live_guard", False):
        return

    def guarded_request(session: Any, method: Any, url: Any, **kwargs: Any) -> Any:
        if is_mock_active():
            raise DailyAITestBudgetExceeded(_raw_http_guard_message(method, url))
        return original_request(session, method, url, **kwargs)

    def guarded_send(session: Any, request: Any, **kwargs: Any) -> Any:
        if is_mock_active():
            raise DailyAITestBudgetExceeded(_raw_http_guard_message(request))
        return original_send(session, request, **kwargs)

    guarded_request._openmates_live_guard = True
    guarded_send._openmates_live_guard = True
    requests.sessions.Session.request = guarded_request
    requests.sessions.Session.send = guarded_send


def _raw_http_guard_message(request_or_method: Any, raw_url: Any = None) -> str:
    if raw_url is None:
        method = str(getattr(request_or_method, "method", "?")).upper()
        url = getattr(request_or_method, "url", "")
    else:
        method = str(request_or_method).upper()
        url = raw_url
    host = getattr(url, "host", None) or str(url).split("?", 1)[0]
    return (
        "TEST_LIVE context cannot use unregistered raw HTTP provider dispatch "
        f"before a replay/budget boundary: {method} {host}; use create_http_client(...)"
    )


async def reserve_real_provider_call(category: str, amount_eur: Decimal) -> None:
    """Reserve conservative cost before one bounded real provider dispatch."""
    if not (is_real_mode() or is_record_mode()):
        return
    state = real_budget_state_var.get()
    if state is None:
        raise DailyAITestBudgetExceeded("Daily AI real test budget is not initialized")
    if amount_eur <= 0:
        raise ValueError("Provider reservation must be positive")
    if os.getenv("DAILY_AI_TEST_BUDGET_BACKEND", "redis") == "memory":
        next_reserved = _reserve_in_memory(state, category, amount_eur)
    else:
        group_id = get_mock_group()
        receipt = live_mock_receipt_var.get()
        backfill_match = DAILY_BACKFILL_RUN_PATTERN.fullmatch(receipt.run_id or "") if receipt else None
        if backfill_match:
            group_id = f"{DAILY_REAL_GROUP_PREFIX}{backfill_match.group(1)}"
        next_reserved = await _reserve_in_redis(state, group_id, category, amount_eur)
        with state.lock:
            state.reserved_eur = next_reserved
            state.provider_calls += 1


def get_real_budget_summary() -> dict[str, Any]:
    """Return content-free accounting for the active real canary request."""
    state = real_budget_state_var.get()
    if state is None:
        return {"active": False, "provider_calls": 0, "reserved_eur": 0.0}
    with state.lock:
        return {
            "active": True,
            "provider_calls": state.provider_calls,
            "reserved_eur": float(state.reserved_eur),
            "limit_eur": float(state.limit_eur),
        }


def _new_real_budget_state() -> _RealBudgetState:
    limit = _positive_decimal_env("DAILY_AI_TEST_BUDGET_EUR", DEFAULT_REAL_BUDGET_EUR)
    if limit > MAX_REAL_BUDGET_EUR:
        raise ValueError("DAILY_AI_TEST_BUDGET_EUR cannot exceed EUR 0.25")
    return _RealBudgetState(limit_eur=limit)


def _reserve_in_memory(
    state: _RealBudgetState, category: str, amount_eur: Decimal
) -> Decimal:
    with state.lock:
        next_reserved = state.reserved_eur + amount_eur
        if next_reserved > state.limit_eur:
            raise _budget_exceeded(state, category)
        state.reserved_eur = next_reserved
        state.provider_calls += 1
        return next_reserved


async def _reserve_in_redis(
    state: _RealBudgetState, group_id: str, category: str, amount_eur: Decimal
) -> Decimal:
    """Atomically reserve micro-euros across workers for one daily run group."""
    try:
        import redis.asyncio as redis

        raw_url = os.getenv("DRAGONFLY_URL", "cache:6379")
        redis_url = raw_url if raw_url.startswith("redis://") else f"redis://{raw_url}"
        client = redis.from_url(
            redis_url,
            password=os.getenv("DRAGONFLY_PASSWORD"),
            decode_responses=True,
        )
        amount = int((amount_eur * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
        limit = int(state.limit_eur * 1_000_000)
        key = f"daily_ai_test_budget:{group_id}"
        script = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
if current + amount > limit then return -1 end
local next = redis.call('INCRBY', KEYS[1], amount)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return next
"""
        try:
            result = int(await client.eval(script, 1, key, amount, limit, 172800))
        finally:
            await client.aclose()
    except DailyAITestBudgetExceeded:
        raise
    except Exception as exc:
        raise DailyAITestBudgetExceeded(
            f"Daily AI real test budget unavailable before provider dispatch: category={category}"
        ) from exc
    if result < 0:
        raise _budget_exceeded(state, category)
    return Decimal(result) / Decimal(1_000_000)


def conservative_llm_reservation_eur(
    model: str,
    *,
    input_token_upper_bound: int,
    max_output_tokens: int,
) -> Decimal:
    """Upper-bound one LLM call using UTF-8 bytes as the input token bound."""
    costs = _model_costs(model)
    input_cost = costs["input_per_million_token"]
    output_cost = costs["output_per_million_token"]
    if str(input_cost.get("currency", "USD")).upper() != str(
        output_cost.get("currency", "USD")
    ).upper():
        raise ValueError(f"Mixed pricing currencies for real test model: {model}")
    multiplier = (
        USD_TO_EUR_SAFETY_MULTIPLIER
        if str(input_cost.get("currency", "USD")).upper() == "USD"
        else Decimal("1")
    )
    token_cost = (
        Decimal(max(input_token_upper_bound, 1)) * Decimal(str(input_cost["price"]))
        + Decimal(max_output_tokens) * Decimal(str(output_cost["price"]))
    ) / Decimal("1000000")
    return max(token_cost * multiplier, Decimal("0.000001"))


@lru_cache(maxsize=128)
def _model_costs(model: str) -> dict[str, Any]:
    provider_root = Path(__file__).resolve().parents[2] / "providers"
    for path in provider_root.glob("*.yml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for candidate in document.get("models", []):
            if candidate.get("id") == model or model in candidate.get("aliases", []):
                costs = candidate.get("costs", {})
                if "input_per_million_token" in costs and "output_per_million_token" in costs:
                    return costs
    raise ValueError(f"No conservative pricing metadata found for real test model: {model}")


def _budget_exceeded(
    state: _RealBudgetState, category: str
) -> DailyAITestBudgetExceeded:
    return DailyAITestBudgetExceeded(
        "Daily AI real test budget exhausted before provider dispatch: "
        f"category={category}, calls={state.provider_calls}, "
        f"reserved_eur={state.reserved_eur}, limit_eur={state.limit_eur}"
    )


def _positive_decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.getenv(name)
    try:
        value = Decimal(raw) if raw is not None else default
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value
