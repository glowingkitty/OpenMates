"""Installed Python native facade exits right after a burst of native completions.

Regression for TASK-1968: tokio completion threads re-attached to the
interpreter while it finalized and crashed the process with SIGSEGV after the
awaited results had already been delivered. Pre-cancelled requests need no IO.
"""

import asyncio
import json
import sys
from pathlib import Path

from openmates import RustApiKeyClient

fixture = sys.argv[1]
suite = json.loads(Path(fixture).read_text())["capabilities"]["sdk.configuration"]
BURST = 64


async def main():
    client = RustApiKeyClient(
        api_key=suite["account"]["api_key"],
        # Unroutable on purpose: a pre-cancelled request must never dispatch.
        api_url="http://127.0.0.1:9",
        app_url="http://127.0.0.1:9",
        device_id=suite["account"]["device_id"],
        enhanced_privacy=False,
        allow_private_operations=True,
    )

    async def pre_cancelled():
        request = client._native.request()
        request.cancel()
        try:
            await request.run_skill_prepare(
                suite["request"]["app"],
                suite["request"]["skill"],
                json.dumps(suite["request"]["input"]),
            )
        except RuntimeError as error:
            return json.loads(str(error))["code"]
        return "value"

    try:
        codes = await asyncio.gather(*(pre_cancelled() for _ in range(BURST)))
    finally:
        client.close()
    assert codes == ["cancelled"] * BURST, codes


# The interpreter exits immediately after the last completion, on purpose.
asyncio.run(main())
