"""Resolve operator-configured secrets declared by installed providers.

A provider declaring ``secrets: [api_key]`` reads Vault
``kv/data/providers/<provider_id>`` key ``api_key`` (imported from
``SECRET__<PROVIDER_ID>__API_KEY``), with the same environment fallback the
built-in provider checks use. Only declared names are resolved, values are
never logged, and a provider with any missing secret is unavailable.

``optional_secrets`` resolve from the same place, are included in the call's
secrets map only when set and never affect availability.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Set

from backend.shared.app_packages.loader import (
    InstalledProvider,
    get_installed_packages,
    get_installed_provider,
)

logger = logging.getLogger(__name__)

IMPORTED_TO_VAULT_PLACEHOLDER = "IMPORTED_TO_VAULT"


def provider_secret_env_var(provider_id: str, secret_name: str) -> str:
    return f"SECRET__{provider_id.upper()}__{secret_name.upper()}"


def _usable(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip() != IMPORTED_TO_VAULT_PLACEHOLDER


async def _resolve_one(provider_id: str, name: str, secrets_manager: Any) -> Optional[str]:
    if secrets_manager is not None and getattr(secrets_manager, "vault_token", None) and getattr(secrets_manager, "vault_url", None):
        value = await secrets_manager.get_secret(
            secret_path=f"kv/data/providers/{provider_id}", secret_key=name, log_missing=False,
        )
        if _usable(value):
            return value.strip()
    value = os.getenv(provider_secret_env_var(provider_id, name))
    return value.strip() if _usable(value) else None


async def resolve_declared_secrets(provider: InstalledProvider, secrets_manager: Any, *,
                                   include_optional: bool = True) -> Optional[Dict[str, str]]:
    """Return ``{name: value}`` for every declared secret plus each configured optional one.

    None when any required secret is missing; optional secrets never cause None.
    """
    resolved: Dict[str, str] = {}
    for name in provider.secrets:
        value = await _resolve_one(provider.provider_id, name, secrets_manager)
        if value is None:
            logger.warning("[AppPackages] Provider '%s' is missing declared secret '%s'", provider.provider_id, name)
            return None
        resolved[name] = value
    for name in provider.optional_secrets if include_optional else ():
        value = await _resolve_one(provider.provider_id, name, secrets_manager)
        if value is not None:
            resolved[name] = value
    return resolved


async def installed_provider_ready(app_id: str, skill_id: str, provider_id: str, secrets_manager: Any) -> bool:
    """True when the registry lists this provider and all of its declared secrets resolve."""
    provider = get_installed_provider(app_id, skill_id, provider_id)
    if provider is None:
        return False
    return await resolve_declared_secrets(provider, secrets_manager, include_optional=False) is not None


async def ready_installed_provider_ids(secrets_manager: Any) -> Set[str]:
    """Provider ids of every installed contribution whose declared secrets resolve."""
    ready: Set[str] = set()
    for provider in get_installed_packages().providers:
        if await resolve_declared_secrets(provider, secrets_manager, include_optional=False) is not None:
            ready.add(provider.provider_id)
    return ready
