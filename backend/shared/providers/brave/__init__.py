# backend/shared/providers/brave/__init__.py
#
# Brave Search API provider functions.
# This module provides functions for interacting with the Brave Search API.

from .brave_search import search_web

__all__ = ['search_web']

