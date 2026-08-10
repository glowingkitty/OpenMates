# backend/shared/providers/geoapify/__init__.py
#
# Shared Geoapify provider package.
# Keeps Geoapify API access independent from app-specific skill code so Maps,
# future location features, and backend smoke scripts can share one normalized
# provider boundary.

from .places import GeoapifyPlacesProvider, normalize_place_details

__all__ = ["GeoapifyPlacesProvider", "normalize_place_details"]
