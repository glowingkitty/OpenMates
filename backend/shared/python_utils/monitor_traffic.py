"""Operator-controlled recognition of external status-monitor traffic.

Both secrets live in Vault at ``kv/data/providers/status_monitor``:
``probe_token`` (anonymous probe header value) and ``account_user_ids``
(comma-separated monitoring account user ids). Nothing client-supplied can
grant the exemption except presenting the secret token; a missing secret turns
the feature off.
"""

import hmac
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

MONITOR_VAULT_PATH = "kv/data/providers/status_monitor"
MONITOR_TOKEN_HEADER = "X-OpenMates-Monitor-Token"
MONITOR_REQUEST_PREFIX = "monitor-probe:"
_CACHE_TTL_SECONDS = 300.0
_cache: dict[str, tuple[float, Optional[str]]] = {}


async def _cached_secret(secrets_manager: Any, key: str) -> Optional[str]:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    if secrets_manager is None:
        return None
    value = await secrets_manager.get_secret(MONITOR_VAULT_PATH, key, log_missing=False)
    value = value.strip() if isinstance(value, str) and value.strip() else None
    _cache[key] = (now, value)
    return value


def clear_monitor_cache() -> None:
    _cache.clear()


def parse_user_ids(raw: Optional[str]) -> frozenset[str]:
    return frozenset(part.strip() for part in (raw or "").split(",") if part.strip())


async def is_monitor_probe(secrets_manager: Any, presented_token: Optional[str]) -> bool:
    """True only when the presented header equals the Vault probe token."""
    if not presented_token:
        return False
    expected = await _cached_secret(secrets_manager, "probe_token")
    if not expected:
        return False
    return hmac.compare_digest(presented_token.encode(), expected.encode())


async def monitor_account_ids(secrets_manager: Any) -> frozenset[str]:
    """All operator-listed monitoring account user ids (empty when unset)."""
    return parse_user_ids(await _cached_secret(secrets_manager, "account_user_ids"))


async def is_monitor_account(secrets_manager: Any, user_id: Optional[str]) -> bool:
    """True when the user id is listed by the operator in Vault."""
    if not user_id:
        return False
    return user_id in await monitor_account_ids(secrets_manager)


def is_monitor_request_id(request_id: Optional[str]) -> bool:
    """Server-generated ids of admitted monitor probes (never client supplied)."""
    return isinstance(request_id, str) and request_id.startswith(MONITOR_REQUEST_PREFIX)
