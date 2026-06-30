"""Directus service package exports.

Keep the heavy DirectusService import lazy so focused helper tests can import
method modules without initializing Redis/httpx-dependent service wiring.
"""

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "DirectusService":
        from backend.core.api.app.services.directus.directus import DirectusService

        return DirectusService
    raise AttributeError(name)

__all__ = ["DirectusService"]
