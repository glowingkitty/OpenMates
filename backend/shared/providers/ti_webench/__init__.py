"""
TI WEBENCH provider exports.

This package wraps the public WEBENCH Power Designer endpoints used by
the Electronics app. It intentionally contains only provider-level HTTP
logic and schemas; OpenMates skill-specific routing lives under
backend/apps/electronics.
"""

from backend.shared.providers.ti_webench.client import search_power_solutions
from backend.shared.providers.ti_webench.models import (
    TIWebenchPowerSearchRequest,
    TIWebenchPowerSolution,
)

__all__ = [
    "TIWebenchPowerSearchRequest",
    "TIWebenchPowerSolution",
    "search_power_solutions",
]
