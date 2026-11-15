"""Bounded-concurrency URL safeguard for preprocessing history messages.

Each message keeps its own verdict (the per-message safeguard call is unchanged);
only the serial awaiting is replaced. The first failure propagates exactly as in
the serial loop and cancels the checks still running.
"""

import asyncio
from typing import Awaitable, Callable, Sequence

URL_SAFEGUARD_CONCURRENCY = 4


async def sanitize_texts_parallel(
    texts: Sequence[str],
    sanitize_one: Callable[[str], Awaitable[str]],
    *,
    concurrency: int = URL_SAFEGUARD_CONCURRENCY,
) -> list[str]:
    """Return sanitize_one(text) for every text, in input order, at most `concurrency` at once."""
    if len(texts) <= 1:
        return [await sanitize_one(text) for text in texts]
    gate = asyncio.Semaphore(max(1, concurrency))

    async def run(text: str) -> str:
        async with gate:
            return await sanitize_one(text)

    tasks = [asyncio.ensure_future(run(text)) for text in texts]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
