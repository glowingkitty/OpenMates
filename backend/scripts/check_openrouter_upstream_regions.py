#!/usr/bin/env python3
# contract-test-file: tooling
"""Report OpenRouter upstream hosts in CN/HK/MO that the hosting policy must block.

Usage: python backend/scripts/check_openrouter_upstream_regions.py
Reads the public https://openrouter.ai/api/v1/providers list (headquarters and
datacenters) and exits 1 if a CN/HK/MO-linked host is missing from
OPENROUTER_BLOCKED_PROVIDERS in backend/shared/python_utils/server_policy.py.
"""

import sys

import httpx

from backend.shared.python_utils.server_policy import (
    BLOCKED_COUNTRIES,
    OPENROUTER_BLOCKED_PROVIDERS,
)


def main() -> int:
    providers = httpx.get("https://openrouter.ai/api/v1/providers", timeout=30).raise_for_status().json()["data"]
    missing = []
    for provider in providers:
        places = {provider.get("headquarters"), *(provider.get("datacenters") or [])}
        if places & BLOCKED_COUNTRIES and provider["slug"] not in OPENROUTER_BLOCKED_PROVIDERS:
            missing.append(f'{provider["slug"]} ({provider.get("headquarters")}, {provider.get("datacenters")})')
    for entry in missing:
        print(f"NOT BLOCKED: {entry}")
    print("OK" if not missing else f"{len(missing)} host(s) to add to OPENROUTER_BLOCKED_PROVIDERS")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
