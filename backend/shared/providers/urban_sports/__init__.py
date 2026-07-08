# backend/shared/providers/urban_sports/__init__.py
#
# Shared Urban Sports Club public-web provider package.
#
# The provider parses logged-out public discovery pages only. Fitness app skills
# use this package for venue and class search without importing from each other.

from backend.shared.providers.urban_sports.client import UrbanSportsClient

__all__ = ["UrbanSportsClient"]
