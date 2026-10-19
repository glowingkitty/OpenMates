#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Live, bounded Jev shopping-image module probe with public fabric photos.

Runs in the deployed api container with Vault-backed SecretsManager credentials.
Downloads real product photos through the production image fetch/preparation code.
One evaluation batch checks a matching fabric against a visually conflicting photo
whose description falsely claims the desired pattern. No search or upload is mocked.
This proves module/provider integration, not authenticated upload or chat execution.
Usage: docker exec api python /app/backend/scripts/verify_shopping_visual_relevance.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
import time

from backend.apps.shopping import visual_ranking
from backend.core.api.app.utils.secrets_manager import SecretsManager


PUBLIC_IMAGE_BASE = "https://cdn02.plentyone.com/5rtbqcd0flq3/item/images/"
MATCH_IMAGE = PUBLIC_IMAGE_BASE + "68090083/full/Baumwoll-Popeline-Digital-Zitronen-Gestreift-Beige_2.jpg"
MATCH_REFERENCE = PUBLIC_IMAGE_BASE + "68090083/full/Baumwoll-Popeline-Digital-Zitronen-Gestreift-Beige_3.jpg"
CONFLICT_IMAGE = PUBLIC_IMAGE_BASE + "68085736/full/Baumwoll-Voile-Enjoy-Kollektion-Zebra-Blau.jpg"


async def evaluate_probe(secrets_manager: SecretsManager) -> dict:
    """Use the normal image downloader and one real ranking call, without patches."""
    first, second = await asyncio.gather(
        visual_ranking.download_public_product_image(MATCH_REFERENCE),
        visual_ranking.download_public_product_image(MATCH_IMAGE),
    )
    # Repeat one known public view to exercise the three-reference upper bound.
    # There are two distinct views; this is not evidence for three-view diversity.
    references = [first, second, first]
    candidates = [
        {"id": "public-lemon-beige", "title": "Cotton poplin with lemons and beige stripes",
         "description": "100% cotton, 120 g/m², yellow lemons on beige striped fabric.",
         "image_url": MATCH_IMAGE},
        {"id": "visual-conflict-misleading-description", "title": "Cotton poplin with lemons and beige stripes",
         "description": "100% cotton, 120 g/m², yellow lemons on beige striped fabric.",
         "image_url": CONFLICT_IMAGE},
    ]
    started = time.perf_counter()
    result = await visual_ranking.rank_products_visually(
        candidates=candidates, reference_images=references,
        relevance_criteria=("Match the visible yellow lemon pattern and beige stripes in the reference photos. "
                            "Reject blue zebra patterns even if the description claims lemons. "
                            "The product description should specify 100% cotton."),
        query="100% cotton fabric with yellow lemons on beige stripes",
        secrets_manager=secrets_manager,
    )
    selected = [{"id": item["id"], **item.get("visual_match", {})} for item in result.candidates]
    checks = {
        "ranking_applied": result.applied,
        "all_candidates_evaluated": result.summary.get("status") == "evaluated"
            and result.summary.get("evaluated_count") == 2,
        "three_references_used": result.summary.get("reference_count") == 3,
        "matching_photo_retained": any(item["id"] == "public-lemon-beige"
            and item.get("status") == "evaluated" and item.get("product_image_count", 0) >= 1
            for item in selected),
        "conflicting_photo_filtered": not any(item["id"] == "visual-conflict-misleading-description"
            for item in selected) and result.summary.get("filtered_count") == 1,
    }
    return {"status": "pass" if all(checks.values()) else "fail",
            "scope": "live_shopping_visual_module", "provider": "jev",
            "reference_count": 3, "distinct_reference_count": 2,
            "candidate_count": len(candidates), "ranking_ms": round((time.perf_counter() - started) * 1000),
            "checks": checks, "summary": result.summary, "selected": selected}


async def main() -> int:
    logging.basicConfig(level=logging.CRITICAL)
    started = time.perf_counter()
    manager = SecretsManager()
    try:
        await manager.initialize()
        result = await asyncio.wait_for(evaluate_probe(manager), timeout=40)
    except Exception as error:
        # Exception messages can contain request bodies or sensitive URLs.
        result = {"status": "fail", "scope": "live_shopping_visual_module",
                  "failure_code": type(error).__name__}
    finally:
        await manager.aclose()
    result["total_ms"] = round((time.perf_counter() - started) * 1000)
    result["module_sha256"] = hashlib.sha256(Path(visual_ranking.__file__).read_bytes()).hexdigest()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
