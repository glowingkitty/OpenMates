#!/usr/bin/env python3
"""Verify four concurrent Brave searches on the deployed development backend.

Runs inside the api container with the normal Vault-backed credential routing.
Uses no model inference, credential overrides, replay or account setting changes.
Prints only source hashes, result counts, elapsed time and fixed error classes.
Requires the expected deployed provider hashes before making external requests.
Usage: docker exec api python /app/backend/scripts/test_brave_concurrent_pacing.py
    --provider-sha256 <hash> --rate-limit-sha256 <hash>
"""
# contract-test-file: tooling

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import time

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.brave import brave_search, rate_limit
from backend.shared.testing.mock_context import is_mock_active


async def main(provider_sha256: str, rate_limit_sha256: str) -> int:
    logging.disable(logging.CRITICAL)
    source = {
        "provider": hashlib.sha256(Path(brave_search.__file__).read_bytes()).hexdigest(),
        "rate_limit": hashlib.sha256(Path(rate_limit.__file__).read_bytes()).hexdigest(),
    }
    if (os.getenv("SERVER_ENVIRONMENT") != "development"
            or os.getenv("GITHUB_ACTIONS") == "true"
            or os.getenv("OPENMATES_CI_ISOLATED") == "1" or is_mock_active()
            or source != {"provider": provider_sha256, "rate_limit": rate_limit_sha256}):
        print(json.dumps({"status": "fail", "category": "development_source_precondition"}))
        return 1
    queries = (
        "OpenMates open source assistant",
        "Brave Search API documentation",
        "Python asyncio documentation",
        "Redis rate limiting documentation",
    )
    secrets = SecretsManager()
    started = time.monotonic()
    try:
        await secrets.initialize()
        outcomes = await asyncio.wait_for(asyncio.gather(*(
            brave_search.search_web(query, secrets, count=1, sanitize_output=False)
            for query in queries
        ), return_exceptions=True), timeout=90)
        rows = []
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                rows.append({"results": 0, "error_class": type(outcome).__name__})
            else:
                results = outcome.get("results") or []
                rows.append({"results": len(results), "error_class": "provider_error"
                             if outcome.get("error") else None})
        passed = len(rows) == 4 and all(row["results"] > 0 and not row["error_class"] for row in rows)
        print(json.dumps({"status": "pass" if passed else "fail", "provider": "brave",
                          "logical_requests": len(rows), "outcomes": rows, "source_sha256": source,
                          "elapsed_seconds": round(time.monotonic() - started, 3)}))
        return 0 if passed else 1
    except Exception as exc:
        print(json.dumps({"status": "fail", "category": "provider_probe",
                          "error_class": type(exc).__name__}))
        return 1
    finally:
        await secrets.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-sha256", required=True)
    parser.add_argument("--rate-limit-sha256", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.provider_sha256, args.rate_limit_sha256)))
