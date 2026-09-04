# backend/shared/providers/wikipedia/__init__.py
#
# Wikipedia / Wikidata API provider functions.
# Provides topic validation, page summaries, and structured entity data
# from the Wikimedia APIs. No API key required — public endpoints.

from .wikipedia_api import (
    WikipediaSearchResult,
    batch_validate_topics,
    fetch_page_summary,
    fetch_wikidata_entity,
    search_wikipedia_titles,
)

__all__ = [
    'WikipediaSearchResult',
    'batch_validate_topics',
    'fetch_page_summary',
    'fetch_wikidata_entity',
    'search_wikipedia_titles',
]
