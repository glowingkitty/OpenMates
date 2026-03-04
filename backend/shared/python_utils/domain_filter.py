# backend/shared/python_utils/domain_filter.py
#
# Shared domain filtering utility for search skills.
# Loads a YAML blocklist of tabloid/boulevard domains and provides
# a function to filter search results by URL hostname.
#
# Architecture context: See docs/architecture/app-skills.md
# Used by: news-search skill, web-search skill
# Tests: (none yet)

import logging
import os
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import yaml

logger = logging.getLogger(__name__)

# Module-level cache for the blocklist — loaded once, reused across requests.
_tabloid_blocklist_cache: Optional[Set[str]] = None

# Path to the shared blocklist config (relative to this file's location)
_BLOCKLIST_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "config",
    "tabloid_blocklist.yml"
)


def load_tabloid_blocklist() -> Set[str]:
    """
    Load and cache the tabloid domain blocklist from YAML config.

    Returns a set of lowercase domain strings (e.g., {"bild.de", "tmz.com"}).
    The set is loaded once from disk and cached in module-level state for
    subsequent calls.

    If the config file is missing or malformed, returns an empty set
    and logs a warning (graceful degradation — filtering is simply skipped).

    Returns:
        Set of blocked domain strings (lowercase, no www prefix).
    """
    global _tabloid_blocklist_cache

    if _tabloid_blocklist_cache is not None:
        return _tabloid_blocklist_cache

    config_path = os.path.normpath(_BLOCKLIST_CONFIG_PATH)

    try:
        if not os.path.exists(config_path):
            logger.warning(
                f"Tabloid blocklist config not found at {config_path}. "
                "Domain filtering will be disabled."
            )
            _tabloid_blocklist_cache = set()
            return _tabloid_blocklist_cache

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config or not isinstance(config.get("domains"), list):
            logger.warning(
                f"Tabloid blocklist config at {config_path} is empty or malformed. "
                "Expected a 'domains' list. Domain filtering will be disabled."
            )
            _tabloid_blocklist_cache = set()
            return _tabloid_blocklist_cache

        domains = {d.strip().lower() for d in config["domains"] if isinstance(d, str) and d.strip()}
        _tabloid_blocklist_cache = domains
        logger.info(f"Loaded tabloid blocklist: {len(domains)} domains from {config_path}")
        return _tabloid_blocklist_cache

    except Exception as e:
        logger.error(
            f"Failed to load tabloid blocklist from {config_path}: {e}",
            exc_info=True
        )
        _tabloid_blocklist_cache = set()
        return _tabloid_blocklist_cache


def _extract_domain(url: str) -> str:
    """
    Extract the bare domain from a URL, stripping www. prefix.

    Args:
        url: Full URL string (e.g., "https://www.bild.de/article/123")

    Returns:
        Lowercase domain without www. prefix (e.g., "bild.de").
        Returns empty string if URL cannot be parsed.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        hostname = hostname.lower()
        # Strip leading www. prefix for consistent matching
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname
    except Exception:
        return ""


def is_domain_blocked(url: str, blocked_domains: Set[str]) -> bool:
    """
    Check if a URL's domain matches any entry in the blocked domains set.

    Uses suffix matching: a blocklist entry "bild.de" will match
    "bild.de", "sport.bild.de", "m.bild.de", etc.

    Args:
        url: Full URL to check.
        blocked_domains: Set of blocked domain strings (lowercase).

    Returns:
        True if the URL's domain matches a blocked domain, False otherwise.
    """
    if not blocked_domains or not url:
        return False

    hostname = _extract_domain(url)
    if not hostname:
        return False

    # Check exact match first (most common case)
    if hostname in blocked_domains:
        return True

    # Check suffix match for subdomains (e.g., "sport.bild.de" ends with ".bild.de")
    for blocked in blocked_domains:
        if hostname.endswith(f".{blocked}"):
            return True

    return False


def filter_results_by_domain(
    results: List[Dict[str, Any]],
    blocked_domains: Set[str],
    url_key: str = "url"
) -> List[Dict[str, Any]]:
    """
    Filter out search results whose URL matches a blocked domain.

    Args:
        results: List of result dicts, each containing a URL field.
        blocked_domains: Set of blocked domain strings (lowercase).
        url_key: Key name for the URL field in each result dict (default: "url").

    Returns:
        Filtered list with blocked domains removed. Original order preserved.
    """
    if not blocked_domains:
        return results

    filtered = []
    blocked_count = 0

    for result in results:
        url = result.get(url_key, "")
        if is_domain_blocked(url, blocked_domains):
            blocked_count += 1
            logger.debug(f"Filtered out tabloid result: {url}")
        else:
            filtered.append(result)

    if blocked_count > 0:
        logger.info(
            f"Domain filter: removed {blocked_count}/{len(results)} results "
            f"from tabloid/boulevard domains"
        )

    return filtered
