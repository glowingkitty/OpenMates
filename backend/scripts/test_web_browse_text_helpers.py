#!/usr/bin/env python3
"""Dev-only native completion controls from a retained public Example capture.

Run inside the API container with --execute --observation-json <file>. The input
is the saved public observation, including its screenshot; no new website visit
or user account is needed. No model/provider overrides are accepted. This tests
the configured Browse specialists, not ordinary chat routing or SDK transport.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.browser_models import BrowserModels
from backend.shared.python_utils.private_inference_logging import (
    private_inference_logging,
)

STATEMENT = (
    "This domain is for use in documentation examples without needing permission. "
    "This is not a service; avoid relying on it for testing and monitoring purposes."
)
GOAL = "Extract the full visible English statement verbatim including its caveats and the current page URL."


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data,web-browse.cost-accounting
async def test_live_quotation_controls(observation: dict) -> dict:
    assert observation.get("url") == "https://example.com/"
    assert STATEMENT in " ".join(observation.get("document_text", "").split())
    manager = SecretsManager()
    await manager.initialize()
    cases = [
        ("complete", GOAL, STATEMENT, True),
        ("omitted_caveat", GOAL, STATEMENT.split(". ")[0] + ".", False),
        ("invented", GOAL, "This domain processes bank payments.", False),
        (
            "unfinished_navigation",
            "Click Learn more and read the IANA page it opens.",
            STATEMENT,
            False,
        ),
        (
            "inverted_relationship",
            "State whether using this domain requires permission, with the current page URL.",
            "needing permission",
            False,
        ),
    ]
    results = []
    try:
        with private_inference_logging():
            for name, goal, text, expected in cases:
                models = BrowserModels(manager)
                data = {"purpose": text, "source_url": observation["url"]}
                if name == "inverted_relationship":
                    data = {
                        "permission_requirement": text,
                        "source_url": observation["url"],
                    }
                error = None
                actual = None
                try:
                    actual = await models.verify(goal, observation, data)
                except Exception as exc:
                    error = type(exc).__name__
                results.append(
                    {
                        "case": name,
                        "expected": expected,
                        "actual": actual,
                        "error_class": error,
                        "passed": error is None and actual is expected,
                        "verification": models.verification,
                        "supplier_cost_usd": str(models.cost),
                        "calls": [
                            {
                                k: a.get(k)
                                for k in (
                                    "model",
                                    "elapsed_seconds",
                                    "complete",
                                    "cost_usd",
                                    "missing",
                                )
                            }
                            for a in models.attempts
                        ],
                    }
                )
        return {
            "status": "passed" if all(r["passed"] for r in results) else "failed",
            "cases": results,
        }
    finally:
        await manager.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--observation-json", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for native model usage")
    result = asyncio.run(
        test_live_quotation_controls(json.loads(args.observation_json.read_text()))
    )
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "passed" else 1)
