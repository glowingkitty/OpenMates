---
status: active
last_verified: 2026-10-24
---

# API Integration — Reference

Provider access policy, test script templates, and documentation format.

## Permitted Access

Implement external data integrations only through a provider-supported documented
API, an explicitly licensed open-data feed, or written authorization covering the
intended automated access and downstream use. Published official API terms or a
feed licence are sufficient when they permit that use. Separate company contact
or a partnership is not required unless the terms require it or the proposed use
remains unclear; do not contact providers without user instruction.

Before implementation, record the documentation/terms/licence URL and review
date, the exact permitted interface and the relevant conditions for commercial
use, display/redistribution, retention, attribution, privacy and rate limits.
An API sold by an intermediary is not evidence of the required source-use rights
by itself. Undocumented browser/mobile endpoints, public availability, browser
automation, low request volume and silence in terms do not establish permission.
Do not bypass source access controls. Platform-specific scraping requires the
written authorization described above.

If no permitted interface exists, report the capability gap and propose a
documented API or licensed-data alternative. Do not replace the missing interface
with a scraper, proxy, browser workflow or platform-specific agent instructions.
Respectful request rates, `robots.txt` and fragility warnings are not permission.

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

## Access and Reuse Permission
- Basis: provider-supported API terms, explicit feed licence, or written authorization
- Documentation/terms/licence URL and review date
- Scope and relevant commercial-use, display, retention and attribution conditions

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
- [ ] Permitted access and downstream use documented with source URL and review date
- [ ] Applicable commercial-use, display, retention, attribution, privacy and rate-limit conditions recorded
- [ ] User confirmed approach
- [ ] Test script at `scripts/api_tests/test_<provider>_api.py`
- [ ] Script supports `--api-key`, `--test`, `--list`
- [ ] All test cases pass
- [ ] Summary at `docs/apis/<provider>.md`
