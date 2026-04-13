# backend/shared/providers/wikipedia/wikipedia_api.py
#
# Wikipedia and Wikidata API provider for topic validation and content retrieval.
# Used by the AI post-processor to validate LLM-generated topic candidates against
# real Wikipedia articles, and by the frontend fullscreen view to fetch rich summaries.
#
# No API key required. Rate limit ~200 req/s per IP.
# Must set User-Agent header per Wikimedia policy:
# https://meta.wikimedia.org/wiki/User-Agent_policy

import logging
from typing import Optional

import httpx
from pydantic import BaseModel

from backend.shared.testing.caching_http_transport import create_http_client

logger = logging.getLogger(__name__)

# Wikimedia API base URLs (language-parameterized)
WIKIPEDIA_ACTION_API_TEMPLATE = "https://{lang}.wikipedia.org/w/api.php"
WIKIPEDIA_REST_API_TEMPLATE = "https://{lang}.wikipedia.org/api/rest_v1"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"

# Required by Wikimedia User-Agent policy
USER_AGENT = "OpenMates/1.0 (https://<PLACEHOLDER>; contact@<PLACEHOLDER>)"

# Limits
MAX_TOPICS_PER_BATCH = 20
MAX_429_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
REQUEST_TIMEOUT = 15.0


class WikipediaTopic(BaseModel):
    """A validated Wikipedia topic with metadata from the batch lookup."""
    topic: str                        # Original phrase from the LLM
    wiki_title: str                   # Canonical Wikipedia article title
    wikidata_id: Optional[str] = None # Wikidata QID, e.g. "Q42"
    thumbnail_url: Optional[str] = None
    description: Optional[str] = None # Short Wikidata description


async def batch_validate_topics(
    topics: list[str],
    language: str = "en",
) -> list[WikipediaTopic]:
    """
    Validate up to 20 topic strings against the Wikipedia Action API batch endpoint.

    Uses action=query with pipe-delimited titles to check which topics have real
    Wikipedia articles. Returns only confirmed matches with metadata (canonical title,
    Wikidata QID, thumbnail, short description).

    The Action API supports up to 50 titles per request; we cap at 20 per the feature spec.

    Args:
        topics: List of topic phrases from the LLM (max 20).
        language: Wikipedia language code (e.g. "en", "de", "ja").

    Returns:
        List of WikipediaTopic for topics with confirmed Wikipedia articles.
    """
    if not topics:
        return []

    # Enforce limit and deduplicate while preserving order
    seen = set()
    unique_topics = []
    for t in topics[:MAX_TOPICS_PER_BATCH]:
        stripped = t.strip()
        if stripped and stripped.lower() not in seen and len(stripped) >= 3:
            seen.add(stripped.lower())
            unique_topics.append(stripped)

    if not unique_topics:
        return []

    action_api_url = WIKIPEDIA_ACTION_API_TEMPLATE.format(lang=language)
    titles_param = "|".join(unique_topics)

    params = {
        "action": "query",
        "titles": titles_param,
        "prop": "pageprops|pageimages|description",
        "ppprop": "wikibase_item",
        "piprop": "thumbnail",
        "pithumbsize": 300,
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
    }

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    try:
        async with create_http_client("wikipedia", timeout=REQUEST_TIMEOUT) as client:
            response = await _request_with_retry(client, action_api_url, params, headers)
            data = response.json()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning(f"Wikipedia batch validation failed: {e}")
        return []

    pages = data.get("query", {}).get("pages", [])
    redirects = data.get("query", {}).get("redirects", [])

    # Build redirect map: original title -> canonical title
    redirect_map = {}
    for r in redirects:
        redirect_map[r.get("from", "").lower()] = r.get("to", "")

    # Build a lookup from canonical title (lowercase) -> page data
    page_by_title: dict[str, dict] = {}
    for page in pages:
        if page.get("missing"):
            continue
        page_by_title[page.get("title", "").lower()] = page

    # Match original topics to validated pages (via redirects or direct match)
    results = []
    for original_topic in unique_topics:
        lower = original_topic.lower()

        # Check direct match
        page = page_by_title.get(lower)

        # Check via redirect
        if page is None:
            redirected_title = redirect_map.get(lower, "")
            page = page_by_title.get(redirected_title.lower())

        if page is None:
            continue

        # Extract metadata
        pageprops = page.get("pageprops", {})
        thumbnail = page.get("thumbnail", {})

        results.append(WikipediaTopic(
            topic=original_topic,
            wiki_title=page.get("title", original_topic),
            wikidata_id=pageprops.get("wikibase_item"),
            thumbnail_url=thumbnail.get("source"),
            description=page.get("description"),
        ))

    logger.info(
        f"Wikipedia batch validation: {len(results)}/{len(unique_topics)} topics confirmed "
        f"(lang={language})"
    )
    return results


async def fetch_page_summary(
    title: str,
    language: str = "en",
) -> Optional[dict]:
    """
    Fetch a rich page summary from the Wikipedia REST API.

    Returns title, description, extract (plain text summary), thumbnail, original image,
    Wikidata QID, and content URLs. Used on-demand by the frontend fullscreen component.

    Args:
        title: Canonical Wikipedia article title (e.g. "Albert_Einstein").
        language: Wikipedia language code.

    Returns:
        Summary dict or None if article not found.
    """
    rest_api_url = WIKIPEDIA_REST_API_TEMPLATE.format(lang=language)
    url = f"{rest_api_url}/page/summary/{title}"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    try:
        async with create_http_client("wikipedia", timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 404:
                logger.info(f"Wikipedia summary not found: {title}")
                return None
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning(f"Wikipedia summary fetch failed for '{title}': {e}")
        return None


async def fetch_wikidata_entity(
    qid: str,
) -> Optional[dict]:
    """
    Fetch structured entity data from Wikidata by QID (e.g. "Q42").

    Returns labels, descriptions, and claims (structured key-value facts like
    birth date, nationality, population). Used optionally by the frontend
    fullscreen view for the "Key Facts" section.

    Args:
        qid: Wikidata entity ID (e.g. "Q42" for Douglas Adams).

    Returns:
        Entity dict or None on failure.
    """
    if not qid or not qid.startswith("Q"):
        return None

    params = {
        "action": "wbgetentities",
        "ids": qid,
        "props": "labels|descriptions|claims",
        "languages": "en",
        "format": "json",
    }

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    try:
        async with create_http_client("wikidata", timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(WIKIDATA_API_URL, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            entities = data.get("entities", {})
            return entities.get(qid)
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning(f"Wikidata entity fetch failed for '{qid}': {e}")
        return None


async def _request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    headers: dict,
) -> httpx.Response:
    """
    Make a GET request with automatic retry on 429 rate limiting.

    Wikipedia's rate limits are generous (~200 req/s) so 429s are rare,
    but we handle them gracefully with exponential backoff.
    """
    import asyncio

    for attempt in range(1, MAX_429_RETRIES + 1):
        response = await client.get(url, params=params, headers=headers)

        if response.status_code != 429:
            response.raise_for_status()
            return response

        if attempt >= MAX_429_RETRIES:
            logger.warning(f"Wikipedia rate limit: exhausted {MAX_429_RETRIES} retries for {url}")
            response.raise_for_status()

        retry_after = response.headers.get("Retry-After")
        wait = float(retry_after) if retry_after else DEFAULT_RETRY_DELAY * attempt

        logger.info(
            f"Wikipedia rate limited (429), attempt {attempt}/{MAX_429_RETRIES}. "
            f"Waiting {wait:.1f}s..."
        )
        await asyncio.sleep(wait)

    raise RuntimeError("Wikipedia rate limit retries exhausted")  # pragma: no cover
