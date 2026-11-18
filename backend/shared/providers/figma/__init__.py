# backend/shared/providers/figma/__init__.py
#
# Pure Figma REST API wrapper exports. Callers supply short-lived access tokens.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from .client import FigmaClient, FigmaInputError, parse_figma_reference
from .errors import FigmaProviderError, classify_status_error

__all__ = [
    "FigmaClient",
    "FigmaInputError",
    "FigmaProviderError",
    "classify_status_error",
    "parse_figma_reference",
]
