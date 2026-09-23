#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Run a small real-provider evaluation of optional search relevance ranking.

Purpose: Compare provider order with Jev order for supported public search skills.
Architecture: Runs inside the API container through SkillRegistry.dispatch_skill().
Data sources: Existing public search providers and the configured Jev provider.
Output: Public titles/hosts plus aggregate candidate, latency, token, and cost data.
Usage: docker exec api python /app/backend/scripts/test_search_relevance_ranking.py [--case maps]
"""

from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timedelta, timezone
import importlib
import json
import logging
import sys
from typing import Any
from urllib.parse import urlsplit

from backend.core.api.app.services.skill_registry import build_skill_registry
from backend.core.api.app.utils.secrets_manager import SecretsManager


FINAL_COUNT = 10
JEV_INPUT_PRICE_PER_MILLION_USD = 0.042


def _event_request() -> dict[str, Any]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=42)
    return {
        "id": "events",
        "query": "AI",
        "location": "Berlin",
        "provider": "luma",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "event_type": "PHYSICAL",
        "count": FINAL_COUNT,
        "relevance_criteria": (
            "AI community events where a software founder could meet potential users, "
            "show a new AI product, and build a relationship for a future talk"
        ),
    }


def _stay_request() -> dict[str, Any]:
    check_in = (datetime.now(timezone.utc) + timedelta(days=35)).date()
    check_out = check_in + timedelta(days=3)
    return {
        "id": "travel-stays",
        "query": "Berlin hotels",
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "adults": 1,
        "max_results": FINAL_COUNT,
        "relevance_criteria": (
            "A work-friendly stay with explicit Wi-Fi and workspace or desk evidence, "
            "prioritizing concrete property details over rating popularity"
        ),
    }


def _fitness_class_request() -> dict[str, Any]:
    start = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    return {
        "id": "fitness-classes",
        "query": "yoga",
        "city": "Berlin",
        "start_date": start.isoformat(),
        "days": 7,
        "limit": FINAL_COUNT,
        "relevance_criteria": (
            "Evening on-site yoga classes with explicit remaining spots and a central Berlin venue"
        ),
    }


CASES: tuple[dict[str, Any], ...] = (
    {
        "app": "web",
        "skill": "search",
        "module": "backend.apps.web.skills.search_skill",
        "request": {
            "id": "web",
            "query": "AI observability tools",
            "count": FINAL_COUNT,
            "relevance_criteria": (
                "Technical evaluations useful for choosing a production AI observability tool, "
                "with concrete benchmarks, implementation details, or primary-source evidence"
            ),
        },
    },
    {
        "app": "news",
        "skill": "search",
        "module": "backend.apps.news.skills.search_skill",
        "request": {
            "id": "news",
            "query": "European AI regulation startups",
            "count": FINAL_COUNT,
            "freshness": "pm",
            "relevance_criteria": (
                "Material recent changes that affect small European AI software companies, "
                "prioritizing concrete obligations, deadlines, and authoritative reporting"
            ),
        },
    },
    {
        "app": "events",
        "skill": "search",
        "module": "backend.apps.events.skills.search_skill",
        "request_factory": _event_request,
    },
    {
        "app": "home",
        "skill": "search",
        "module": "backend.apps.home.skills.search_skill",
        "request": {
            "id": "home",
            "query": "Berlin",
            "listing_type": "rent",
            "property_type": "apartment",
            "max_results": FINAL_COUNT,
            "relevance_criteria": (
                "Apartments whose listing explicitly mentions a balcony or terrace and gives "
                "concrete evidence of a quiet setting; treat missing facts as unknown"
            ),
        },
    },
    {
        "app": "maps",
        "skill": "search",
        "module": "backend.apps.maps.skills.search_skill",
        "request": {
            "id": "maps",
            "query": "cafes in Berlin",
            "includedType": "cafe",
            "pageSize": FINAL_COUNT,
            "osmEnrichment": "disabled",
            "relevance_criteria": (
                "A cafe suitable for focused laptop work, prioritizing explicit Wi-Fi, seating, "
                "opening-hour, or work-friendly evidence and treating missing facts as unknown"
            ),
        },
    },
    {
        "app": "shopping",
        "skill": "search_products",
        "module": "backend.apps.shopping.skills.search_products",
        "request": {
            "id": "shopping",
            "query": "wireless travel mouse",
            "provider": "Amazon",
            "category": "electronics",
            "country": "DE",
            "max_results": FINAL_COUNT,
            "relevance_criteria": (
                "A compact travel mouse with explicit quiet-click, long battery-life, and "
                "multi-device support, prioritizing feature fit over popularity"
            ),
        },
    },
    {
        "app": "travel",
        "skill": "search_stays",
        "module": "backend.apps.travel.skills.search_stays",
        "request_factory": _stay_request,
    },
    {
        "app": "videos",
        "skill": "search",
        "module": "backend.apps.videos.skills.search_skill",
        "request": {
            "id": "videos",
            "query": "local LLM RAG production tutorial",
            "count": FINAL_COUNT,
            "relevance_criteria": (
                "An advanced hands-on tutorial for an experienced Python developer, with explicit "
                "production architecture, evaluation, or deployment depth rather than an introduction"
            ),
        },
    },
    {
        "app": "fitness-locations",
        "registry_app": "fitness",
        "skill": "search_locations",
        "module": "backend.apps.fitness.skills.search_locations",
        "request": {
            "id": "fitness-locations",
            "query": "yoga",
            "city": "Berlin",
            "limit": FINAL_COUNT,
            "relevance_criteria": (
                "A venue with explicit yoga variety and a central Berlin address; do not infer class level"
            ),
        },
    },
    {
        "app": "fitness-classes",
        "registry_app": "fitness",
        "skill": "search_classes",
        "module": "backend.apps.fitness.skills.search_classes",
        "request_factory": _fitness_class_request,
    },
)


def _candidate_summary(candidate: Any) -> dict[str, str]:
    if not isinstance(candidate, dict):
        return {"title": "", "host": ""}
    raw_url = candidate.get("url") or candidate.get("booking_url") or ""
    try:
        host = urlsplit(str(raw_url)).hostname or ""
    except ValueError:
        host = ""
    return {
        "title": str(candidate.get("title") or candidate.get("name") or "")[:180],
        "host": host,
    }


def _response_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    groups = response.get("results")
    if not isinstance(groups, list) or not groups:
        return []
    group = groups[0]
    if not isinstance(group, dict) or not isinstance(group.get("results"), list):
        return []
    return [item for item in group["results"] if isinstance(item, dict)]


async def _run_case(
    registry: Any,
    secrets_manager: SecretsManager,
    case: dict[str, Any],
) -> dict[str, Any]:
    module = importlib.import_module(case["module"])
    original_rank = module.rank_search_candidates
    capture: dict[str, Any] = {}

    async def capturing_rank(**kwargs: Any) -> Any:
        candidates = list(kwargs["candidates"])
        result = await original_rank(**kwargs)
        capture.update({
            "candidate_count": len(candidates),
            "provider_order_top": [_candidate_summary(item) for item in candidates[:FINAL_COUNT]],
            "ranked_order_top": [_candidate_summary(item) for item in result.candidates[:FINAL_COUNT]],
            "applied": result.applied,
            "fallback_reason": result.fallback_reason,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_ms": round(result.latency_ms, 1),
            "estimated_cost_usd": round(
                result.input_tokens * JEV_INPUT_PRICE_PER_MILLION_USD / 1_000_000,
                8,
            ),
        })
        return result

    module.rank_search_candidates = capturing_rank
    request = case.get("request") or case["request_factory"]()
    try:
        response = await registry.dispatch_skill(
            case.get("registry_app", case["app"]),
            case["skill"],
            {"requests": [request], "_secrets_manager": secrets_manager},
        )
    finally:
        module.rank_search_candidates = original_rank

    response_items = _response_items(response)
    capture.update({
        "app": case["app"],
        "requested_count": FINAL_COUNT,
        "returned_count": len(response_items),
        "response_top": [_candidate_summary(item) for item in response_items],
        "response_has_error": bool(response.get("error")) or any(
            bool(group.get("error"))
            for group in response.get("results", [])
            if isinstance(group, dict)
        ),
    })
    capture["status"] = (
        "pass"
        if capture.get("applied") is True
        and 0 < capture["returned_count"] <= FINAL_COUNT
        and capture.get("candidate_count", 0) >= capture["returned_count"]
        else "fail"
    )
    return capture


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        action="append",
        dest="case_names",
        help="Run only this case name (repeatable).",
    )
    args = parser.parse_args()
    selected_cases = tuple(
        case for case in CASES if not args.case_names or case["app"] in args.case_names
    )
    unknown_cases = sorted(set(args.case_names or ()) - {case["app"] for case in CASES})
    if unknown_cases:
        print(json.dumps({"status": "fail", "unknown_cases": unknown_cases}))
        return 2

    logging.basicConfig(level=logging.WARNING)
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    try:
        registry, metadata = build_skill_registry()
        missing = [
            case["app"]
            for case in selected_cases
            if case.get("registry_app", case["app"]) not in metadata
        ]
        if missing:
            print(json.dumps({"status": "fail", "missing_apps": missing}))
            return 1

        results = []
        for case in selected_cases:
            try:
                results.append(await _run_case(registry, secrets_manager, case))
            except Exception as exc:
                results.append({
                    "app": case["app"],
                    "status": "fail",
                    "error_type": type(exc).__name__,
                })

        status = "pass" if all(item["status"] == "pass" for item in results) else "fail"
        print(json.dumps({"status": status, "results": results}, ensure_ascii=False, indent=2))
        return 0 if status == "pass" else 1
    finally:
        await secrets_manager.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
