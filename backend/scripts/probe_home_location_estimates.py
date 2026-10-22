#!/usr/bin/env python3
"""Purpose: Check Home location refinement with synthetic public descriptions.
Architecture: Manual dev-only inference probe using Vault and existing providers.
Data sources: Mercury 3 and OpenStreetMap via Geoapify; no user account/chat data.
Tests: Small numeric, qualitative and misleading-location sample, never CI.
Usage: docker exec api python /app/backend/scripts/probe_home_location_estimates.py
Output: Sanitized statuses/counts only, never credentials or provider bodies.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time

from backend.apps.home.location_enrichment import enrich_home_locations
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.secrets_manager import SecretsManager

CASES = [
    ("numeric_de", "Die Wohnung liegt etwa 500 m vom S-Bahnhof Alexanderplatz entfernt.", True),
    ("numeric_en", "The apartment is about 600 m from Berlin Ostbahnhof.", True),
    ("walking", "The apartment is 5 minutes on foot from Berlin Ostbahnhof.", True),
    ("qualitative", "The apartment is close to Alexanderplatz station.", False),
    ("office", "The agency office is 500 m from Alexanderplatz station. The apartment's location is only Berlin.", False),
    ("train", "The apartment is 10 minutes by train from Alexanderplatz station.", False),
]


async def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    secrets = SecretsManager()
    await secrets.initialize()
    cache = CacheService()
    results = []
    try:
        for case_id, description, numeric in CASES:
            item = {"id": f"synthetic-home-location-{case_id}", "provider": "synthetic-probe",
                    "city": "Berlin", "description": description}
            started = time.monotonic()
            await enrich_home_locations([item], city="Berlin", request={}, secrets_manager=secrets, cache_service=cache)
            location = item.get("location") or {}
            area = location.get("area") or {}
            results.append({"case": case_id, "numeric": numeric, "basis": area.get("basis"),
                            "refinement": location.get("refinement_status"),
                            "radius_m": area.get("radius_m"), "exact": location.get("exact_address"),
                            "elapsed_ms": round((time.monotonic() - started) * 1000)})
    finally:
        await cache.close()
        await secrets.aclose()
    safe = all(row["exact"] is False and row["basis"] in {"city", "district", "description"} for row in results)
    safe &= all(row["basis"] != "description" for row in results if not row["numeric"])
    refined = sum(row["basis"] == "description" for row in results if row["numeric"])
    passed = safe and refined > 0
    print(json.dumps({"status": "pass" if passed else "fail", "cases": results,
                      "numeric_refined": refined, "sample_only": True}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
