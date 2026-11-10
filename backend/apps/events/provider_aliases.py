"""Provider selector values the events search skill interprets itself.

The skill maps these ``provider`` inputs to its built-in modes, so an installed
app package provider must never use one as its id (the loader rejects such
packages via ``contracts.reserved_provider_ids``).
"""
from __future__ import annotations

from typing import Dict, FrozenSet

from backend.apps.events.providers import pretalx as pretalx_provider

VALID_PROVIDERS: FrozenSet[str] = frozenset({"auto", "pretalx"})
PROVIDER_ALIASES: Dict[str, str] = {
    "none": "auto", "pretalx": "pretalx", "conference schedule": "pretalx",
    **{key: "pretalx" for key in pretalx_provider.CONFERENCES},
}


def reserved_provider_ids() -> FrozenSet[str]:
    """Selector values (aliases, conference keys, ``auto``, ``none``) reserved by events.search."""
    return frozenset(VALID_PROVIDERS | set(PROVIDER_ALIASES) | set(pretalx_provider.CONFERENCES))
