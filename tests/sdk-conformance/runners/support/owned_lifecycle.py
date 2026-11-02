"""Bounded independent peer teardown, with no SDK or listener dependency."""

import asyncio


async def cleanup_owned(peer, client, *, close_seconds=2, grace_seconds=0.3):
    async def terminate():
        if peer is None or peer.returncode is not None:
            return
        try:
            peer.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(peer.wait(), grace_seconds)
        except asyncio.TimeoutError:
            try:
                peer.kill()
            except ProcessLookupError:
                pass
            await asyncio.wait_for(peer.wait(), 2)

    async def close():
        if client is not None:
            await asyncio.wait_for(client.close(), close_seconds)

    # Schedule peer termination FIRST; close cannot hold it behind a native lock.
    termination = asyncio.create_task(terminate())
    closing = asyncio.create_task(close())
    results = await asyncio.gather(termination, closing, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
