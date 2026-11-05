"""Explicit cookie authentication; only Rust-owned volatile opaque metadata."""

from __future__ import annotations
import asyncio
import json
from typing import TypedDict
from .session_client import SessionClientError, _failure


class MetadataCookieCredentials(TypedDict):
    sessionId: str
    cookies: dict[str, str]


class MetadataAuthenticationOptions(MetadataCookieCredentials):
    apiUrl: str
    appUrl: str


class MetadataEphemeralError(SessionClientError):
    pass


def _error(error: Exception) -> MetadataEphemeralError:
    value = _failure(error)
    return MetadataEphemeralError(value.code, str(value))


class MetadataAuthentication:
    """Pending input only. Core actual HTTP identity issues the opaque context."""

    __slots__ = ("__native",)

    def __init__(self, options: MetadataAuthenticationOptions):
        try:
            from . import _native

            self.__native = _native.NativeMetadataAuthentication(
                json.dumps(options, allow_nan=False, separators=(",", ":"))
            )
        except Exception as error:
            raise _error(error) from None

    async def authenticate(self) -> EphemeralMetadataClient:
        try:
            return EphemeralMetadataClient(await self.__native.authenticate())
        except asyncio.CancelledError:
            self.__native.cancel()
            raise
        except Exception as error:
            raise _error(error) from None

    def credential_snapshot(self) -> MetadataCookieCredentials:
        try:
            return json.loads(self.__native.credential_snapshot_json())
        except Exception as error:
            raise _error(error) from None

    def cancel(self) -> None:
        self.__native.cancel()

    async def cancel_and_drain(self) -> None:
        try:
            await self.__native.cancel_and_drain()
        except Exception as error:
            raise _error(error) from None


class EphemeralMetadataClient:
    """Core memory only, with no durable/profile/browser or crypto authority."""

    __slots__ = ("_native_handle",)

    def __init__(self, handle):
        self._native_handle = handle

    def prepare_initial_sync(self) -> EphemeralMetadataStartup:
        try:
            return EphemeralMetadataStartup(self._native_handle.prepare_initial_sync())
        except Exception as error:
            raise _error(error) from None

    def credential_snapshot(self) -> MetadataCookieCredentials:
        try:
            return json.loads(self._native_handle.credential_snapshot_json())
        except Exception as error:
            raise _error(error) from None

    async def close(self) -> None:
        try:
            await self._native_handle.close()
        except Exception as error:
            raise _error(error) from None


class EphemeralMetadataStartup:
    __slots__ = ("__native",)

    def __init__(self, handle):
        self.__native = handle

    async def run(self) -> EphemeralMetadataSnapshot:
        try:
            return EphemeralMetadataSnapshot(await self.__native.run())
        except asyncio.CancelledError:
            self.__native.cancel()
            raise
        except Exception as error:
            raise _error(error) from None

    def cancel(self) -> None:
        self.__native.cancel()


class EphemeralMetadataSnapshot:
    __slots__ = ("__native",)

    def __init__(self, handle):
        self.__native = handle

    def received_metadata_count(self, client: EphemeralMetadataClient) -> int:
        if not isinstance(client, EphemeralMetadataClient):
            raise MetadataEphemeralError(
                "forbidden", "Use the original metadata context."
            )
        try:
            return self.__native.received_metadata_count(client._native_handle)
        except Exception as error:
            raise _error(error) from None

    def cancel(self) -> None:
        self.__native.cancel()
