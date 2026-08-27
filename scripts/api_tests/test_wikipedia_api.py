#!/usr/bin/env python3
"""Live dev-API smoke checks for the approved Wikipedia mention REST contract.

Purpose: exercise authentication, deterministic first-result ordering, visible
disambiguation, and summary response boundaries against the real dev API.
Security: accepts a supplied test API key but never prints it or raw response bodies.
Run: python3 scripts/api_tests/test_wikipedia_api.py --base-url https://api.dev.openmates.org --test all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError


DEFAULT_BASE_URL = "https://api.dev.openmates.org"
DEFAULT_TIMEOUT_SECONDS = 30


class SmokeFailure(RuntimeError):
    """An assertion against the deployed Wikipedia REST contract failed."""


def _request_json(base_url: str, path: str, api_key: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json", "X-OpenMates-SDK": "rest_api"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib_request.Request(f"{base_url.rstrip('/')}{path}", headers=headers)
    try:
        with urllib_request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"detail": "non-JSON error response"}
        return error.code, payload


def _require_api_key(args: argparse.Namespace) -> str:
    api_key = args.api_key or os.environ.get("OPENMATES_API_KEY")
    if not api_key:
        raise SmokeFailure("Provide --api-key or OPENMATES_API_KEY for authenticated Wikipedia smoke checks.")
    return api_key


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.provider.bounded-access
def test_unauthorized_search(args: argparse.Namespace) -> dict[str, Any]:
    status, _payload = _request_json(args.base_url, "/v1/wikipedia/search?query=AlbertEinstein&language=en")
    if status != 401:
        raise SmokeFailure(f"Expected unauthenticated search to return 401, got {status}.")
    return {"status": "pass", "case": "unauthorized_search", "http_status": status}


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.resolution.first-result,wikipedia-mentions.privacy.explicit-third-party-query
def test_search_first_result(args: argparse.Namespace) -> dict[str, Any]:
    status, payload = _request_json(
        args.base_url,
        "/v1/wikipedia/search?query=AlbertEinstein&language=en&limit=2",
        _require_api_key(args),
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(results, list) or not results:
        raise SmokeFailure(f"Expected authenticated title search result, got HTTP {status}.")
    first = results[0]
    if first.get("title") != "Albert Einstein" or first.get("disambiguation") is not False:
        raise SmokeFailure("Expected Albert Einstein as the first non-disambiguation result.")
    forbidden = {"wikidata", "wikibase_item", "claims", "qid"}
    if forbidden.intersection(first):
        raise SmokeFailure("Search response exposes forbidden Wikidata fields.")
    return {"status": "pass", "case": "first_result", "result_count": len(results)}


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.resolution.disambiguation-visible
def test_disambiguation(args: argparse.Namespace) -> dict[str, Any]:
    status, payload = _request_json(
        args.base_url,
        "/v1/wikipedia/search?query=Mercury&language=en&limit=5",
        _require_api_key(args),
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(results, list) or not results:
        raise SmokeFailure(f"Expected Mercury search results, got HTTP {status}.")
    if results[0].get("disambiguation") is not True:
        raise SmokeFailure("Expected first Mercury result to be marked as a disambiguation page.")
    return {"status": "pass", "case": "disambiguation", "result_count": len(results)}


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.context.summary-only,wikipedia-mentions.safety.fail-closed
def test_summary_boundary(args: argparse.Namespace) -> dict[str, Any]:
    status, payload = _request_json(
        args.base_url,
        "/v1/wikipedia/summary?title=Albert_Einstein&language=en",
        _require_api_key(args),
    )
    if status != 200:
        raise SmokeFailure(f"Expected authenticated article summary, got HTTP {status}.")
    forbidden = {"wikidata", "wikibase_item", "claims", "originalimage", "html"}
    if forbidden.intersection(payload):
        raise SmokeFailure("Selected-summary response exposes context forbidden by the Wikipedia mention contract.")
    if not isinstance(payload.get("extract"), str) or not payload["extract"]:
        raise SmokeFailure("Selected-summary response lacks a lead extract for fail-closed safety processing.")
    return {"status": "pass", "case": "summary_boundary"}


TESTS = {
    "unauthorized": test_unauthorized_search,
    "search": test_search_first_result,
    "disambiguation": test_disambiguation,
    "summary": test_summary_boundary,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the Wikipedia mention REST API against dev.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", help="Test API key; defaults to OPENMATES_API_KEY.")
    parser.add_argument("--test", choices=[*TESTS, "all"], default="all")
    args = parser.parse_args()
    selected = TESTS if args.test == "all" else {args.test: TESTS[args.test]}
    try:
        results = {name: test(args) for name, test in selected.items()}
    except SmokeFailure as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(results, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
