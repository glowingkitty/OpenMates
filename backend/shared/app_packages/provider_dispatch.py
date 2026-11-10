"""Run installed contract providers for one skill request item.

Used by built-in skills that declare a ``provider_contract`` and by the generic
``InstalledProviderSkill`` delegate (``skill.requests@1``). Each provider is
resolved from the server registry, receives only its declared secrets, runs in
the isolated runner and has its output validated against the contract. A
failing provider yields a safe error for that provider only.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

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


async def run_installed_providers(
    app_id: str,
    skill_id: str,
    provider_ids: Sequence[str],
    input_item: Dict[str, Any],
    secrets_manager: Any,
) -> List[InstalledProviderOutcome]:
    """Run the given installed providers concurrently; order follows ``provider_ids``."""
    unique = list(dict.fromkeys(provider_ids))
    return list(await asyncio.gather(*(
        _run_one(app_id, skill_id, provider_id, input_item, secrets_manager) for provider_id in unique
    )))
