"""Provider selector values the jobs search skill interprets itself.

The skill maps these ``provider`` inputs to its built-in source or to automatic
country routing, so an operator-installed app package provider must never use
one as its id (the loader rejects such packages via
``contracts.reserved_provider_ids``).
"""
from __future__ import annotations

from typing import Dict, FrozenSet

PROVIDER_ALIASES: Dict[str, str] = {
    "jobtech": "jobtech", "jobtechdev": "jobtech", "jobtech dev": "jobtech", "auto": "auto",
}


def reserved_provider_ids() -> FrozenSet[str]:
    """Selector values (built-in aliases and ``auto``) reserved by jobs.search."""
    return frozenset(PROVIDER_ALIASES)
