"""Explicit original native startup. Observed count is not store/ACK authority."""
from __future__ import annotations

import asyncio


class SessionInitialSyncOperation:
    def __init__(self, client, monitor, native):
        self._client, self._monitor, self._native = client, monitor, native
        self._started = False

    def __repr__(self):
        return "<openmates.SessionInitialSyncOperation>"

    async def run(self):
        from .session_client import SessionClientError

        if self._started:
            raise SessionClientError("conflict", "The initial sync operation was already consumed.")
        self._started = True
        try:
            self._monitor._valid()
            # Keep actual native IO alive on host cancellation, then cancel its
            # original scope; no abandoned result is treated as a receipt.
            ticket = asyncio.ensure_future(self._native.run())
            try:
                output = await self._client._call(lambda: ticket)
            except BaseException:
                self.cancel()
                raise
            self._monitor._valid()
            return SessionInitialSyncMetadata(self._client, self._monitor, output, self)
        except BaseException:
            self.cancel()
            raise

    def cancel(self):
        self._native.cancel()


class SessionInitialSyncMetadata:
    def __init__(self, client, monitor, native, original):
        self._client, self._monitor, self._native, self._original = client, monitor, native, original

    def __repr__(self):
        return "<openmates.SessionInitialSyncMetadata>"

    async def received_metadata_count(self):
        from .session_client import SessionClientError

        self._monitor._valid()
        count = await self._client._essential_call(self._native.received_metadata_count)
        self._monitor._valid()
        if type(count) is not int or count < 0:
            raise SessionClientError("protocol", "Invalid received metadata count.")
        return count

    def cancel(self):
        self._native.cancel()
        self._original.cancel()
