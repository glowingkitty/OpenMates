#!/usr/bin/env python3
"""
Low-cost live probes for the Iconify public API integration.

Usage:
    python3 scripts/api_tests/test_iconify_api.py
    python3 scripts/api_tests/test_iconify_api.py --test search
    python3 scripts/api_tests/test_iconify_api.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.shared.providers.iconify.client import IconifyClient, is_permissive_license  # noqa: E402


async def test_search() -> dict[str, object]:
    """Test: search for home icons and confirm permissive metadata."""
    print("\n" + "=" * 60)
    print("TEST: search")
    print("=" * 60)
    start = time.time()
    try:
        results = await IconifyClient().search_icons("home", count=8)
        if not results:
            raise AssertionError("Expected at least one permissively licensed home icon")
        first = results[0]
        if not is_permissive_license(first.license_spdx or first.license_title):
            raise AssertionError(f"Expected permissive license, got {first.license_spdx or first.license_title}")
        duration = time.time() - start
        print(json.dumps({"result_count": len(results), "first_icon": first.icon_id, "license": first.license_spdx}, indent=2))
        print(f"[OK] Status: success ({duration:.2f}s)")
        return {"status": "pass", "duration": duration}
    except Exception as exc:
        duration = time.time() - start
        error = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] Error: {error} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": error}


async def test_svg() -> dict[str, object]:
    """Test: fetch and sanitize a known SVG."""
    print("\n" + "=" * 60)
    print("TEST: svg")
    print("=" * 60)
    start = time.time()
    try:
        svg = await IconifyClient().fetch_svg("lucide", "home")
        if "<svg" not in svg or "script" in svg.lower():
            raise AssertionError("Expected sanitized SVG markup")
        duration = time.time() - start
        print(json.dumps({"svg_length": len(svg)}, indent=2))
        print(f"[OK] Status: success ({duration:.2f}s)")
        return {"status": "pass", "duration": duration}
    except Exception as exc:
        duration = time.time() - start
        error = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] Error: {error} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": error}


async def test_no_match() -> dict[str, object]:
    """Test: no-match searches return an empty result list, not a provider failure."""
    print("\n" + "=" * 60)
    print("TEST: no_match")
    print("=" * 60)
    start = time.time()
    try:
        results = await IconifyClient().search_icons("zzzz-no-icon-openmates-test", count=4)
        if results:
            raise AssertionError(f"Expected no results, got {len(results)}")
        duration = time.time() - start
        print(json.dumps({"result_count": len(results)}, indent=2))
        print(f"[OK] Status: success ({duration:.2f}s)")
        return {"status": "pass", "duration": duration}
    except Exception as exc:
        duration = time.time() - start
        error = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] Error: {error} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": error}


TESTS = {"search": test_search, "svg": test_svg, "no_match": test_no_match}


async def run(args: argparse.Namespace) -> None:
    if args.list:
        for name, fn in TESTS.items():
            print(f"  {name}: {fn.__doc__}")
        return

    tests = {args.test: TESTS[args.test]} if args.test else TESTS
    results = {name: await fn() for name, fn in tests.items()}
    print("\n" + "=" * 60 + "\nSUMMARY\n" + "=" * 60)
    passed = sum(1 for result in results.values() if result["status"] == "pass")
    print(f"Passed: {passed}/{len(results)}")
    if passed != len(results):
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Iconify public API integration")
    parser.add_argument("--api-key", help="Unused; Iconify public API is unauthenticated")
    parser.add_argument("--test", choices=sorted(TESTS), help="Run a specific test")
    parser.add_argument("--list", action="store_true", help="List tests")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
