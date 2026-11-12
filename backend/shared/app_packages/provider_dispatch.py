"""Run installed contract providers for one skill request item.

Used by built-in skills that declare a ``provider_contract`` and by the generic
``InstalledProviderSkill`` delegate (``skill.requests@1``). Each provider is
resolved from the server registry, receives only its declared secrets, runs in
the isolated runner and has its output validated against the contract. A
failing provider yields a safe error for that provider only.

Duplicate results of one request item are returned once (``drop_duplicate_results``):
results with identical content apart from the provider attribution, and results
that carry the same ``dedupe_key`` (a provider-chosen identity such as a
normalized listing or departure). Of several results with one key the highest
``dedupe_priority`` wins (default 0, ties keep the first); both fields are
removed before the results leave this module.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from backend.shared.app_packages.contracts import validate_contract_results
from backend.shared.app_packages.loader import get_installed_provider
from backend.shared.app_packages.runner_client import run_provider
from backend.shared.app_packages.secrets import resolve_declared_secrets

logger = logging.getLogger(__name__)

SAFE_ERROR_MESSAGES = {
    "PACKAGE_UNAVAILABLE": "is unavailable",
    "TIMEOUT": "did not respond in time",
    "PROVIDER_ERROR": "reported an error",
}
DEFAULT_SAFE_ERROR = "failed"
DEDUPE_KEY_FIELD = "dedupe_key"
DEDUPE_PRIORITY_FIELD = "dedupe_priority"
MAX_DEDUPE_KEY_CHARS = 300
# Fields that never make two results different: attribution and the dedupe hints.
_IDENTITY_IGNORED_FIELDS = frozenset({"provider", "provider_id", DEDUPE_KEY_FIELD, DEDUPE_PRIORITY_FIELD})


@dataclass
class InstalledProviderOutcome:
    provider_id: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


async def _run_one(app_id: str, skill_id: str, provider_id: str, input_item: Dict[str, Any],
                   secrets_manager: Any) -> InstalledProviderOutcome:
    provider = get_installed_provider(app_id, skill_id, provider_id)
    if provider is None:
        return InstalledProviderOutcome(provider_id, error="Selected provider is unavailable.")
    secrets = await resolve_declared_secrets(provider, secrets_manager)
    if secrets is None:
        return InstalledProviderOutcome(provider_id, error=f"{provider.name} is not configured on this server.")
    outcome = await run_provider(provider, input_item, secrets)
    if not outcome.ok:
        logger.warning("[AppPackages] Provider '%s' (%s@%s) failed with %s", provider_id, provider.package_id,
                       provider.package_version, outcome.error_code)
        reason = SAFE_ERROR_MESSAGES.get(outcome.error_code or "", DEFAULT_SAFE_ERROR)
        return InstalledProviderOutcome(provider_id, error=f"{provider.name} {reason}.")
    results = validate_contract_results(provider.contract, outcome.results,
                                        provider_id=provider.provider_id, provider_name=provider.name)
    discarded = len(outcome.results) - len(results)
    if discarded > 0:
        logger.info("[AppPackages] Discarded %d contract-invalid result(s) from '%s'", discarded, provider_id)
    return InstalledProviderOutcome(provider_id, results=results)


def _result_identity(result: Dict[str, Any]) -> Tuple[str, str]:
    key = result.get(DEDUPE_KEY_FIELD)
    if isinstance(key, str) and key.strip() and len(key) <= MAX_DEDUPE_KEY_CHARS:
        return "key", key.strip().casefold()
    content = {name: value for name, value in result.items() if name not in _IDENTITY_IGNORED_FIELDS}
    return "content", json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)


def _result_priority(result: Dict[str, Any]) -> int:
    priority = result.get(DEDUPE_PRIORITY_FIELD)
    return priority if isinstance(priority, int) and not isinstance(priority, bool) else 0


def drop_duplicate_results(outcomes: Sequence[InstalledProviderOutcome]) -> int:
    """Keep each distinct result once across (and inside) the outcomes; return how many were dropped.

    The kept result stays at its own position in its own provider's list, so the
    later merge order is unchanged for everything that is not a duplicate.
    """
    kept: Dict[Tuple[str, str], Tuple[int, int, int]] = {}
    dropped: set[Tuple[int, int]] = set()
    for outcome_index, outcome in enumerate(outcomes):
        for result_index, result in enumerate(outcome.results):
            identity = _result_identity(result)
            priority = _result_priority(result)
            previous = kept.get(identity)
            if previous is None:
                kept[identity] = (outcome_index, result_index, priority)
            elif priority > previous[2]:
                dropped.add(previous[:2])
                kept[identity] = (outcome_index, result_index, priority)
            else:
                dropped.add((outcome_index, result_index))
    for outcome_index, outcome in enumerate(outcomes):
        remaining = [result for result_index, result in enumerate(outcome.results)
                     if (outcome_index, result_index) not in dropped]
        for result in remaining:
            result.pop(DEDUPE_KEY_FIELD, None)
            result.pop(DEDUPE_PRIORITY_FIELD, None)
        outcome.results = remaining
    return len(dropped)


async def _run_one_reporting(app_id: str, skill_id: str, provider_id: str, input_item: Dict[str, Any],
                             secrets_manager: Any,
                             on_provider_done: Optional[Callable[[InstalledProviderOutcome], Awaitable[None]]],
                             ) -> InstalledProviderOutcome:
    outcome = await _run_one(app_id, skill_id, provider_id, input_item, secrets_manager)
    if on_provider_done is not None:
        try:
            await on_provider_done(outcome)
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            logger.warning("[AppPackages] Progress callback for '%s' failed: %s", provider_id, exc)
    return outcome

async def run_installed_providers(
    app_id: str,
    skill_id: str,
    provider_ids: Sequence[str],
    input_item: Dict[str, Any],
    secrets_manager: Any,
    on_provider_done: Optional[Callable[[InstalledProviderOutcome], Awaitable[None]]] = None,
) -> List[InstalledProviderOutcome]:
    """Run the given installed providers concurrently; order follows ``provider_ids``.

    ``on_provider_done`` is awaited as each provider finishes (before de-duplication);
    a failing callback never fails the provider.
    """
    unique = list(dict.fromkeys(provider_ids))
    outcomes = list(await asyncio.gather(*(
        _run_one_reporting(app_id, skill_id, provider_id, input_item, secrets_manager, on_provider_done)
        for provider_id in unique
    )))
    dropped = drop_duplicate_results(outcomes)
    if dropped:
        logger.info("[AppPackages] Dropped %d duplicate result(s) for %s.%s", dropped, app_id, skill_id)
    return outcomes
