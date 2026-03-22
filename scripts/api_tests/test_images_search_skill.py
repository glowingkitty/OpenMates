#!/usr/bin/env python3
"""
Purpose: Test the images search skill via internal REST API (direct container call).
Architecture: Standalone test script calling app-images:8000/skills/search via docker exec.
Tests: N/A (manual CLI verification script)

Usage:
    python3 scripts/api_tests/test_images_search_skill.py

Requires the app-images container to be running.
"""

import json
import subprocess
import sys
from pathlib import Path

ENDPOINT = "http://app-images:8000/skills/search"
TEST_RESULTS_DIR = Path("scripts/api_tests/results")
TEST_RESULTS_DIR.mkdir(exist_ok=True)

PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"


def call_skill(data: dict) -> dict:
    """POST to app-images:8000/skills/search via docker exec api."""
    json_data = json.dumps(data).replace("'", "'\\''")
    cmd = [
        "docker", "exec", "api", "sh", "-c",
        f"curl -s -X POST {ENDPOINT} -H 'Content-Type: application/json' -d '{json_data}'"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"docker exec failed: {result.stderr}")
    return json.loads(result.stdout)


def save(name: str, req: dict, resp: dict):
    path = TEST_RESULTS_DIR / f"images_search_{name}.json"
    path.write_text(json.dumps({"request": req, "response": resp}, indent=2, ensure_ascii=False))
    print(f"  Saved: {path}")


def check(label: str, condition: bool, detail: str = ""):
    icon = PASS if condition else FAIL
    print(f"  {icon} {label}" + (f": {detail}" if detail else ""))
    return condition


def test_single_query():
    print("\n[1] Single text query")
    req = {"requests": [{"id": "1", "query": "MacBook neo photos"}]}
    resp = call_skill(req)
    save("single_query", req, resp)

    ok = True
    ok &= check("no top-level error", resp.get("error") is None, resp.get("error", ""))
    ok &= check("provider is Brave Search", resp.get("provider") == "Brave Search", resp.get("provider"))
    results = resp.get("results", [])
    ok &= check("one result group", len(results) == 1)
    if results:
        imgs = results[0].get("results", [])
        ok &= check(f"has image results ({len(imgs)})", len(imgs) > 0)
        if imgs:
            first = imgs[0]
            ok &= check("type=image_result", first.get("type") == "image_result")
            ok &= check("image_url present", bool(first.get("image_url")))
            ok &= check("thumbnail_url present", bool(first.get("thumbnail_url")))
            ok &= check("source_page_url present", bool(first.get("source_page_url")))
            ok &= check("source present", bool(first.get("source")))
    return ok


def test_multi_query():
    print("\n[2] Multiple parallel queries")
    req = {
        "requests": [
            {"id": "1", "query": "cats playing"},
            {"id": "2", "query": "sunset landscape photography"},
            {"id": "3", "query": "Tokyo street photos"},
        ]
    }
    resp = call_skill(req)
    save("multi_query", req, resp)

    ok = True
    ok &= check("no top-level error", resp.get("error") is None, resp.get("error", ""))
    results = resp.get("results", [])
    ok &= check("three result groups", len(results) == 3, str(len(results)))
    for r in results:
        imgs = r.get("results", [])
        ok &= check(f"req {r['id']}: has results ({len(imgs)})", len(imgs) > 0)
    return ok


def test_custom_count():
    print("\n[3] Custom count (5 results)")
    req = {"requests": [{"id": "1", "query": "Eiffel Tower", "count": 5}]}
    resp = call_skill(req)
    save("custom_count", req, resp)

    ok = True
    ok &= check("no top-level error", resp.get("error") is None, resp.get("error", ""))
    results = resp.get("results", [])
    if results:
        imgs = results[0].get("results", [])
        ok &= check(f"respects count (got {len(imgs)}, want <=5)", len(imgs) <= 5)
        ok &= check("has at least 1 result", len(imgs) >= 1)
    return ok


def test_empty_requests():
    print("\n[4] Empty requests array (error handling)")
    req = {"requests": []}
    resp = call_skill(req)
    save("empty_requests", req, resp)
    ok = check("returns error for empty requests", bool(resp.get("error")), resp.get("error", "no error"))
    return ok


if __name__ == "__main__":
    print("=" * 60)
    print("Images Search Skill -- REST API Tests")
    print(f"Endpoint: {ENDPOINT}")
    print("=" * 60)

    tests = [test_single_query, test_multi_query, test_custom_count, test_empty_requests]
    passed = 0
    for t in tests:
        try:
            if t():
                passed += 1
            else:
                print("  ^ FAILED")
        except Exception as e:
            print(f"  {FAIL} EXCEPTION: {e}")

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{len(tests)} tests passed")
    print("=" * 60)
    sys.exit(0 if passed == len(tests) else 1)
