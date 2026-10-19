"""Normalize image URLs already supplied by shopping search providers.

Keep one URL per supplied photo in provider order, without fetching images or
making product-details requests. Providers retain image_url for existing embeds
and expose image_urls in their structured results for gallery-aware consumers.
Tests: backend/tests/test_shopping_product_images.py.
"""

from collections.abc import Iterable
from urllib.parse import urlsplit


def normalize_image_urls(candidates: Iterable[object]) -> list[str]:
    """Keep distinct HTTP(S) image URLs, skipping malformed provider entries."""
    urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        url = candidate.strip()
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls
