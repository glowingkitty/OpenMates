"""Bounded, anonymous reads of the USPTO trademark search website's JSON API.

This is a website endpoint, not the documented/keyed TSDR API. Its stability and
coverage limits are documented in docs/apis/trademark-search.md. Never solve an
access challenge or retry through a proxy. Only requested names and filters are
sent; raw records, owner addresses and query-bearing diagnostics are not logged.
"""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

import httpx

SEARCH_URL = "https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch"
USER_AGENT = "OpenMates/1.0 (https://openmates.org; trademark search)"
SOURCE_FIELDS = [
    "id", "wordmark", "ownerName", "statusDescription", "statusCode", "alive",
    "registered", "registrationId", "internationalClass", "goodsAndServices",
    "filedDate", "registrationDate", "recordLoadDate",
]
_request_lock = asyncio.Lock()
_last_request_at = 0.0


class TrademarkProviderError(Exception):
    """Safe provider failure; never contains submitted queries or raw responses."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _text(value: Any, limit: int = 500) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:limit] if isinstance(value, str) else ""


def _texts(value: Any, limit: int = 500, count: int = 8) -> list[str]:
    return [_text(item, limit) for item in value[:count] if _text(item, limit)] if isinstance(value, list) else []


def _name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _record(source: dict[str, Any], query: str) -> dict[str, Any] | None:
    serial = source.get("id")
    mark = _text(source.get("wordmark"), 256)
    if not isinstance(serial, str) or not re.fullmatch(r"\d{8}", serial) or not mark:
        return None
    classes: list[int] = []
    raw_classes = source.get("internationalClass")
    for value in raw_classes if isinstance(raw_classes, list) else []:
        if not isinstance(value, str):
            continue
        match = re.search(r"\d{1,3}", value)
        if match and 1 <= int(match[0]) <= 45 and int(match[0]) not in classes:
            classes.append(int(match[0]))
    alive = source.get("alive") if isinstance(source.get("alive"), bool) else None
    registered = source.get("registered") if isinstance(source.get("registered"), bool) else None
    status = "ended" if alive is False else (
        "registered" if alive is True and registered is True else
        "pending" if alive is True and registered is False else "unknown"
    )
    return {
        "query": query, "mark": mark, "region": "US", "provider": "USPTO",
        "application_number": serial,
        "registration_number": _text(source.get("registrationId"), 32) or None,
        "owners": _texts(source.get("ownerName"), 360),
        "nice_classes": classes, "goods_services": _texts(source.get("goodsAndServices"), 3000),
        "status": status, "status_description": _text(source.get("statusDescription"), 300),
        "active": alive, "registered": registered,
        "filing_date": _text(source.get("filedDate"), 32) or None,
        "registration_date": _text(source.get("registrationDate"), 32) or None,
        "source_updated_at": _text(source.get("recordLoadDate"), 32) or None,
        "name_match": "exact" if _name(mark) == _name(query) else "similar",
        "source_url": "https://tsdr.uspto.gov/#caseNumber=" + serial
        + "&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch",
    }


class USPTOTrademarkClient:
    """Read only the first bounded search page; preserve truncation and failures."""

    provider_name = "USPTO"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client

    async def search(
        self, query: str, *, nice_classes: list[int], status: str,
        match: str, max_results: int,
    ) -> dict[str, Any]:
        normalized = _name(query)
        name_clause = (
            {"term": {"wordmarkExact": {"value": normalized}}} if match == "exact" else
            {"match": {"WM": {"query": normalized, "fuzziness": "AUTO", "operator": "and"}}}
        )
        filters: list[dict[str, Any]] = []
        if status == "active":
            filters.append({"term": {"LD": "true"}})
        if nice_classes:
            filters.append({"terms": {"IC": [f"{value:03d}" for value in nice_classes]}})
        payload = {
            "query": {"bool": {"must": [name_clause], "filter": filters}},
            "size": max_results, "from": 0, "track_total_hits": True, "_source": SOURCE_FIELDS,
        }
        data = await self._post(payload)
        hits = data.get("hits")
        if not isinstance(hits, dict) or not isinstance(hits.get("hits"), list):
            raise TrademarkProviderError("invalid_response", "USPTO returned an invalid search response")
        total = hits.get("totalValue")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise TrademarkProviderError("invalid_response", "USPTO did not return a valid match count")
        results: list[dict[str, Any]] = []
        rejected = 0
        for hit in hits["hits"][:max_results]:
            record = _record(hit["source"], query) if isinstance(hit, dict) and isinstance(hit.get("source"), dict) else None
            if record is None:
                rejected += 1
            else:
                results.append(record)
        if total and not results:
            raise TrademarkProviderError("invalid_response", "USPTO returned no readable records for its match count")
        incomplete = bool(data.get("timedOut")) or bool(data.get("shardsFailed")) or rejected > 0 or hits.get("totalRelation") != "eq"
        return {
            "results": results, "total_matches": total,
            "more_results": total > len(results), "partial": incomplete,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        global _last_request_at
        client = self._http_client or httpx.AsyncClient(timeout=20.0)
        try:
            # One request per second per worker, with no stored query/result cache.
            async with _request_lock:
                await asyncio.sleep(max(0.0, 1.0 - (time.monotonic() - _last_request_at)))
                _last_request_at = time.monotonic()
                response = await client.post(SEARCH_URL, json=payload, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            if response.status_code == 429:
                raise TrademarkProviderError("rate_limited", "USPTO rate limit reached; try again later")
            if response.status_code in {202, 401, 403}:
                raise TrademarkProviderError("access_restricted", "USPTO requires an interactive access check")
            if response.status_code != 200:
                raise TrademarkProviderError("provider_unavailable", "USPTO search is currently unavailable")
            if len(response.content) > 2_000_000:
                raise TrademarkProviderError("invalid_response", "USPTO returned an oversized response")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise TrademarkProviderError("provider_unavailable", "USPTO search could not be read") from exc
        finally:
            if self._http_client is None:
                await client.aclose()
