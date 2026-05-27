#!/usr/bin/env python3
"""
Test script for the TI WEBENCH reverse-engineered API integration.

Usage:
    python scripts/api_tests/test_ti_webench_api.py
    python scripts/api_tests/test_ti_webench_api.py --test search_power_solutions
    python scripts/api_tests/test_ti_webench_api.py --list
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.shared.providers.ti_webench import (  # noqa: E402
    TIWebenchPowerSearchRequest,
    search_power_solutions,
)


async def test_search_power_solutions() -> dict:
    """Test: search for 12V to 3.3V, 3A DC/DC power converters."""
    print("\n" + "=" * 60)
    print("TEST: search_power_solutions")
    print("=" * 60)
    start = time.time()
    try:
        request = TIWebenchPowerSearchRequest(
            vinMin=12,
            vinMax=12,
            vout=[3.3],
            iout=[3],
            ambientTemp=30,
            isIsolated=False,
            powerSupply="dc",
            optimizationSetting=3,
        )
        results = await search_power_solutions(request, max_results=5)
        if not results:
            raise AssertionError("Expected at least one WEBENCH solution")
        first = results[0]
        duration = time.time() - start
        print(
            json.dumps(
                {
                    "solution_count": len(results),
                    "first_part": first.info.device.partNumber,
                    "first_solution_id": first.id,
                    "first_topology": first.info.topology,
                },
                indent=2,
            )
        )
        print(f"[OK] Status: success ({duration:.2f}s)")
        return {"status": "pass", "duration": duration}
    except Exception as exc:
        duration = time.time() - start
        error = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] Error: {error} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": error}


TESTS = {"search_power_solutions": test_search_power_solutions}


async def run(args: argparse.Namespace) -> None:
    if args.list:
        for name, fn in TESTS.items():
            print(f"  {name}: {fn.__doc__}")
        return

    tests = {args.test: TESTS[args.test]} if args.test else TESTS
    results = {}
    for name, fn in tests.items():
        results[name] = await fn()

    print("\n" + "=" * 60 + "\nSUMMARY\n" + "=" * 60)
    passed = sum(1 for result in results.values() if result["status"] == "pass")
    print(f"Passed: {passed}/{len(results)}")
    if passed != len(results):
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test TI WEBENCH API integration")
    parser.add_argument("--api-key", help="Unused; WEBENCH endpoint is unauthenticated")
    parser.add_argument("--test", choices=sorted(TESTS), help="Run a specific test")
    parser.add_argument("--list", action="store_true", help="List tests")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
