#!/usr/bin/env python3
"""Live, keyless USPTO contract probe. Run only on explicit provider investigation."""
# contract-test-file: tooling
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.providers.trademarks import USPTOTrademarkClient


async def main():
    client = USPTOTrademarkClient()
    for name, mode, classes, has_matches in [
        ("ADIDAS", "exact", [], True), ("COCA-COLA", "exact", [], True),
        ("ADIDAS", "similar", [25], True),
        ("zzqvopenmatesbrandprobe872641", "exact", [], False),
    ]:
        data = await client.search(name, nice_classes=classes, status="active", match=mode, max_results=3)
        assert bool(data["results"]) is has_matches, name
        assert not data["partial"], name
        assert not classes or all(any(c in row["nice_classes"] for c in classes) for row in data["results"])
        print(json.dumps({"query": name, "match": mode, "nice_classes": classes,
                          "total_matches": data["total_matches"], "checked_at": data["checked_at"]}))


if __name__ == "__main__":
    asyncio.run(main())
