"""Fetch aggregate growth counts from the Admin Debug API (read-only) for the daily meeting.

Runs inside the api container (the admin API keys live in Vault):
  docker exec -i api python /app/backend/scripts/growth_metrics_query.py --prod < request.json
stdin: {"since": "<ISO timestamp>", "exclude_email_hashes": ["<base64 sha256>", ...]}
stdout: the endpoint's JSON ({"success": true, "metrics": {...}}): counts only, no per-user data.
Endpoint: POST /v1/admin/debug/growth-metrics (backend/core/api/app/routes/admin_growth_metrics.py)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import aiohttp

sys.path.insert(0, "/app/backend/scripts")
from debug_utils import get_admin_debug_api_key  # noqa: E402 - container script path set above

BASES = {"prod": "https://api.openmates.org/v1/admin/debug",
         "dev": "https://api.dev.openmates.org/v1/admin/debug"}


async def fetch(target: str, request: dict) -> dict:
    api_key = await get_admin_debug_api_key(target)
    if not api_key:
        raise RuntimeError(f"no {target} admin debug API key in Vault")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
        async with session.post(f"{BASES[target]}/growth-metrics", json=request,
                                headers={"Authorization": f"Bearer {api_key}"}) as response:
            if response.status != 200:
                raise RuntimeError(f"growth-metrics HTTP {response.status}: {(await response.text())[:200]}")
            return await response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--prod", action="store_const", const="prod", dest="target")
    target.add_argument("--dev", action="store_const", const="dev", dest="target")
    args = parser.parse_args()
    request = json.load(sys.stdin)
    try:
        print(json.dumps(asyncio.run(fetch(args.target, request))))
    except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
