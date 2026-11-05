---
status: active
last_verified: 2026-11-03
---

# API Integration — Reference

Provider access policy, test script templates, and documentation format.

## Official APIs Only

Implement provider-specific data integrations only through the provider's
official, documented API or an official open-data feed. Before implementation,
record the API documentation URL and review date, the exact interface used and
its usage, attribution, privacy and rate-limit conditions. Do not contact
providers without user instruction.

Do not use undocumented browser/mobile endpoints, browser automation,
platform-specific scraping, proxies or third-party resellers of another
platform's data, and do not bypass access controls.

If no official interface exists, report the capability gap and propose an
official API alternative. Do not replace the missing interface with a scraper,
proxy, browser workflow or platform-specific agent instructions.

## General public-page reading

The generic `web.read` capability may read selected public pages for a user task,
including links found through search. It does not require a provider API for
every ordinary page. Identify the reader, honor applicable `robots.txt` rules
before fetching a page and again for redirected targets, and stop when crawler
policy cannot be established or access is denied.

Use verified TLS and bounded public-address requests without proxies, cookies,
authentication, CAPTCHA solving, browser impersonation or retries that evade a
block. Do not crawl whole sites, call hidden website/mobile APIs or recreate a
retired platform connector through the reader. Keep the complete extracted text,
source metadata and existing safety processing in encrypted saved embeds and
history; this capability does not change retention or delete existing results.

---

## Test Script Template

Location: `scripts/api_tests/test_<provider>_api.py`

```python
#!/usr/bin/env python3
"""
Test script for <Provider Name> API integration.

Usage:
    python scripts/api_tests/test_<provider>_api.py              # vault
    python scripts/api_tests/test_<provider>_api.py --api-key "key"  # manual
    python scripts/api_tests/test_<provider>_api.py --test <name>    # specific test
    python scripts/api_tests/test_<provider>_api.py --list           # list tests
"""
import argparse, json, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

def load_api_key(manual_key=None):
    if manual_key:
        print("[AUTH] Using manually provided API key")
        return manual_key
    try:
        print("[AUTH] Loading API key from vault...")
        # ... vault loading logic ...
    except Exception as e:
        print(f"[AUTH ERROR] Failed to load from vault: {e}")
        print("[AUTH] Provide key manually with: --api-key <your-key>")
        sys.exit(1)

def test_example(api_key):
    """Test: description of what this test does."""
    print("\n" + "=" * 60)
    print("TEST: example")
    print("=" * 60)
    start = time.time()
    try:
        # ... API call ...
        duration = time.time() - start
        print(f"[OK] Status: success ({duration:.2f}s)")
        return {"status": "pass", "duration": duration}
    except Exception as e:
        duration = time.time() - start
        print(f"[FAIL] Error: {e} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(e)}

TESTS = {"example": test_example}

def main():
    parser = argparse.ArgumentParser(description="Test <Provider> API")
    parser.add_argument("--api-key", help="Manual API key override")
    parser.add_argument("--test", help="Run specific test")
    parser.add_argument("--list", action="store_true", help="List tests")
    args = parser.parse_args()
    if args.list:
        for name, fn in TESTS.items():
            print(f"  {name}: {fn.__doc__}")
        return
    api_key = load_api_key(args.api_key)
    tests = {args.test: TESTS[args.test]} if args.test else TESTS
    results = {}
    for name, fn in tests.items():
        results[name] = fn(api_key)
    print("\n" + "=" * 60 + "\nSUMMARY\n" + "=" * 60)
    passed = sum(1 for r in results.values() if r["status"] == "pass")
    print(f"Passed: {passed}/{len(results)}")

if __name__ == "__main__":
    main()
```

---

## Documentation Template (`docs/apis/<provider>.md`)

```markdown
# <Provider Name> API Integration Summary

## Overview
Brief description of what the API does and why we're using it.

## Official API
- Official API documentation URL and review date
- Interface used and its usage, attribution and rate-limit conditions

## Authentication
- Type: (API key / OAuth2 / etc.)
- Vault key name: `<VAULT_KEY_NAME>`

## Endpoints Used

### <Endpoint 1>
- **URL:** `GET/POST https://api.example.com/v1/resource`
- **Purpose:** What this endpoint does

## Input / Output Structure

### Input
| Parameter | Type | Required | Description |
|---|---|---|---|

### Output
| Field | Type | Description |
|---|---|---|

## Pricing
- **Free tier:** X requests/month
- **Paid tier:** $X per 1,000 requests
- **Estimated cost:** Based on expected volume

## Limitations
- Rate limits, data freshness, geographic restrictions, response size limits

## Scaling Considerations
- Pricing at scale, bulk/batch endpoints, caching strategy, failover options
```

---

## Checklist

- [ ] Research completed (or user provided details)
- [ ] Official API documented with source URL and review date
- [ ] Usage, attribution, privacy and rate-limit conditions recorded
- [ ] User confirmed approach
- [ ] Test script at `scripts/api_tests/test_<provider>_api.py`
- [ ] Script supports `--api-key`, `--test`, `--list`
- [ ] All test cases pass
- [ ] Summary at `docs/apis/<provider>.md`
