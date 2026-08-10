#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compare Firecrawl and Brave search results on a fixed query set.

This is an exploratory provider-quality harness, not a product benchmark command.
It reads provider keys from Vault when run inside the API container, or from
environment variables in a developer shell. Output intentionally excludes raw
credentials and focuses on latency, cost units, result shape, and excerpts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.brave.brave_search import _get_brave_api_key_candidates
from backend.shared.providers.firecrawl.firecrawl_scrape import _get_firecrawl_api_key


Provider = Literal["firecrawl", "brave"]

DEFAULT_QUERIES: list[dict[str, str]] = [
    {"id": "factual-regulatory", "kind": "web", "query": "EU AI Act enforcement timeline 2026 GPAI obligations August 2026"},
    {"id": "company-pricing", "kind": "web", "query": "OpenAI API pricing GPT-5.4 input output tokens July 2026"},
    {"id": "technical-docs", "kind": "web", "query": "Svelte 5 use effect cleanup runes official docs"},
    {"id": "local-current", "kind": "web", "query": "Berlin public transport strike latest official announcement"},
    {"id": "research-paper", "kind": "web", "query": "latest retrieval augmented generation benchmark 2026 paper"},
    {"id": "financial-news", "kind": "news", "query": "Nvidia latest earnings guidance 2026 revenue data center news"},
    {"id": "policy-news", "kind": "news", "query": "European Commission AI Act code of practice latest news"},
    {"id": "security-news", "kind": "news", "query": "latest Chrome zero day security update July 2026"},
    {"id": "product-launch", "kind": "news", "query": "latest Apple AI product announcement 2026 news"},
    {"id": "climate-news", "kind": "news", "query": "latest IPCC climate report announcement news 2026"},
]

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v2/search"


@dataclass
class SearchComparisonResult:
    provider: Provider
    query_id: str
    kind: str
    query: str
    ok: bool
    latency_ms: int
    result_count: int
    estimated_provider_cost_usd: float | None
    provider_credits_used: int | None
    top_results: list[dict[str, Any]]
    error: str | None = None


def _compact_text(value: Any, *, limit: int = 900) -> str:
    text = str(value or "").replace("\r", " ").strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text[:limit]


def _term_overlap_score(query: str, text: str) -> float:
    query_terms = {term.lower() for term in query.replace("-", " ").split() if len(term) > 3}
    if not query_terms:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for term in query_terms if term in text_lower)
    return round(hits / len(query_terms), 3)


async def _get_secrets_manager() -> SecretsManager:
    secrets_manager = SecretsManager()
    initialize = getattr(secrets_manager, "initialize", None)
    if initialize:
        maybe = initialize()
        if hasattr(maybe, "__await__"):
            await maybe
    return secrets_manager


async def _search_firecrawl(
    client: httpx.AsyncClient,
    api_key: str,
    query_item: dict[str, str],
    limit: int,
) -> SearchComparisonResult:
    started = time.perf_counter()
    kind = query_item["kind"]
    query = query_item["query"]
    payload: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "sources": [{"type": kind}],
        "highlights": True,
    }

    try:
        response = await client.post(
            FIRECRAWL_SEARCH_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        data = response.json()
        results = data.get("data", {}).get(kind, []) or []
        top_results = []
        for result in results[:3]:
            excerpt = result.get("description") if kind == "web" else result.get("snippet")
            compact_excerpt = _compact_text(excerpt)
            top_results.append(
                {
                    "title": result.get("title"),
                    "url": result.get("url"),
                    "date": result.get("date"),
                    "excerpt": compact_excerpt,
                    "excerpt_chars": len(compact_excerpt),
                    "term_overlap": _term_overlap_score(query, compact_excerpt),
                    "position": result.get("position"),
                }
            )
        credits_used = data.get("creditsUsed")
        return SearchComparisonResult(
            provider="firecrawl",
            query_id=query_item["id"],
            kind=kind,
            query=query,
            ok=True,
            latency_ms=latency_ms,
            result_count=len(results),
            estimated_provider_cost_usd=None,
            provider_credits_used=credits_used if isinstance(credits_used, int) else None,
            top_results=top_results,
        )
    except Exception as exc:  # noqa: BLE001 - exploratory script should capture all provider failures.
        latency_ms = int((time.perf_counter() - started) * 1000)
        return SearchComparisonResult(
            provider="firecrawl",
            query_id=query_item["id"],
            kind=kind,
            query=query,
            ok=False,
            latency_ms=latency_ms,
            result_count=0,
            estimated_provider_cost_usd=None,
            provider_credits_used=None,
            top_results=[],
            error=str(exc),
        )


async def _search_brave(
    client: httpx.AsyncClient,
    api_keys: list[tuple[str, str]],
    query_item: dict[str, str],
    limit: int,
) -> SearchComparisonResult:
    started = time.perf_counter()
    kind = query_item["kind"]
    query = query_item["query"]
    url = BRAVE_NEWS_URL if kind == "news" else BRAVE_SEARCH_URL
    params = {
        "q": query,
        "count": min(limit, 20),
        "country": "US",
        "search_lang": "en",
        "safesearch": "moderate",
        "spellcheck": "1",
        "extra_snippets": "1",
    }
    if kind == "web":
        params["result_filter"] = "web"
    if kind == "news":
        params["freshness"] = "pw"

    last_error: str | None = None
    for label, api_key in api_keys:
        try:
            response = await client.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code == 429:
                last_error = f"{label}: {response.status_code} {response.text[:300]}"
                continue
            response.raise_for_status()
            data = response.json()
            results = data.get("results", []) if kind == "news" else data.get("web", {}).get("results", [])
            top_results = []
            for result in results[:3]:
                snippets = result.get("extra_snippets") if isinstance(result.get("extra_snippets"), list) else []
                excerpt = "\n".join([result.get("description", ""), *snippets]).strip()
                compact_excerpt = _compact_text(excerpt)
                top_results.append(
                    {
                        "title": result.get("title"),
                        "url": result.get("url"),
                        "date": result.get("age") or result.get("page_age"),
                        "excerpt": compact_excerpt,
                        "excerpt_chars": len(compact_excerpt),
                        "term_overlap": _term_overlap_score(query, compact_excerpt),
                    }
                )
            return SearchComparisonResult(
                provider="brave",
                query_id=query_item["id"],
                kind=kind,
                query=query,
                ok=True,
                latency_ms=latency_ms,
                result_count=len(results),
                estimated_provider_cost_usd=0.005,
                provider_credits_used=None,
                top_results=top_results,
            )
        except Exception as exc:  # noqa: BLE001 - try fallback key candidates before failing.
            last_error = f"{label}: {exc}"

    latency_ms = int((time.perf_counter() - started) * 1000)
    return SearchComparisonResult(
        provider="brave",
        query_id=query_item["id"],
        kind=kind,
        query=query,
        ok=False,
        latency_ms=latency_ms,
        result_count=0,
        estimated_provider_cost_usd=0.005,
        provider_credits_used=None,
        top_results=[],
        error=last_error,
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    providers: list[Provider]
    if args.provider == "both":
        providers = ["firecrawl", "brave"]
    else:
        providers = [args.provider]

    secrets_manager = await _get_secrets_manager()
    try:
        firecrawl_key = await _get_firecrawl_api_key(secrets_manager) if "firecrawl" in providers else None
        brave_keys = await _get_brave_api_key_candidates(secrets_manager) if "brave" in providers else []
    finally:
        close = getattr(secrets_manager, "close", None)
        if close:
            maybe = close()
            if hasattr(maybe, "__await__"):
                await maybe

    queries = DEFAULT_QUERIES[: args.query_count]
    timeout = httpx.Timeout(args.timeout)
    results: list[SearchComparisonResult] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for query_item in queries:
            if "firecrawl" in providers:
                if firecrawl_key:
                    results.append(await _search_firecrawl(client, firecrawl_key, query_item, args.limit))
                else:
                    results.append(
                        SearchComparisonResult(
                            provider="firecrawl",
                            query_id=query_item["id"],
                            kind=query_item["kind"],
                            query=query_item["query"],
                            ok=False,
                            latency_ms=0,
                            result_count=0,
                            estimated_provider_cost_usd=None,
                            provider_credits_used=None,
                            top_results=[],
                            error="Firecrawl API key not configured",
                        )
                    )
            if "brave" in providers:
                if brave_keys:
                    results.append(await _search_brave(client, brave_keys, query_item, args.limit))
                else:
                    results.append(
                        SearchComparisonResult(
                            provider="brave",
                            query_id=query_item["id"],
                            kind=query_item["kind"],
                            query=query_item["query"],
                            ok=False,
                            latency_ms=0,
                            result_count=0,
                            estimated_provider_cost_usd=0.005,
                            provider_credits_used=None,
                            top_results=[],
                            error="Brave API key not configured",
                        )
                    )

    by_provider: dict[str, dict[str, Any]] = {}
    for provider in providers:
        provider_results = [result for result in results if result.provider == provider]
        successful = [result for result in provider_results if result.ok]
        provider_costs = [result.estimated_provider_cost_usd for result in successful if result.estimated_provider_cost_usd is not None]
        by_provider[provider] = {
            "queries": len(provider_results),
            "successful": len(successful),
            "average_latency_ms": round(sum(result.latency_ms for result in successful) / len(successful), 1) if successful else None,
            "average_result_count": round(sum(result.result_count for result in successful) / len(successful), 1) if successful else None,
            "provider_credits_used": sum(result.provider_credits_used or 0 for result in successful) or None,
            "estimated_provider_cost_usd": round(sum(provider_costs), 4) if provider_costs else None,
        }

    return {
        "query_count": len(queries),
        "limit": args.limit,
        "summary": by_provider,
        "results": [asdict(result) for result in results],
        "notes": [
            "Brave cost estimate uses public Search pricing: $5 per 1,000 successful requests.",
            "Firecrawl search provider credits are reported from API creditsUsed when available; Search is billed at 2 credits per 10 results before optional scraping.",
            "term_overlap is a crude lexical heuristic for triage, not a final quality score.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Firecrawl and Brave search provider output on fixed queries.")
    parser.add_argument("--provider", choices=["both", "firecrawl", "brave"], default="both")
    parser.add_argument("--query-count", type=int, default=10, choices=range(1, len(DEFAULT_QUERIES) + 1))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    output = asyncio.run(run(args))
    print(json.dumps(output, indent=2 if args.pretty else None, sort_keys=True))


if __name__ == "__main__":
    main()
