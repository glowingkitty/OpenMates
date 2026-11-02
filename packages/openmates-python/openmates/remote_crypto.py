"""Pure local Rust crypto. Explicit byte keys; no profile/network/consent authority."""

from __future__ import annotations
import json
from typing import Literal, TypedDict
from .session_client import SessionClientError, _failure

RemoteRole = Literal["requester", "source"]


class _RequiredIdentity(TypedDict):
    ownerId: str
    projectId: str
    sourceId: str
    sourceSessionId: str
    requestingClientId: str
    keyEpoch: int


class RemoteIdentity(_RequiredIdentity, total=False):
    contextType: Literal["personal", "team"]
    contextId: str
    hostMemberId: str
    hostDeviceId: str
    requesterMemberId: str
    requesterDeviceId: str


class RemoteHandshakeWire(TypedDict):
    version: int
    role: RemoteRole
    publicKey: str
    authenticationTag: str


class RemoteEnvelope(TypedDict):
    version: int
    nonce: str
    ciphertext: str


class RemoteCryptoError(SessionClientError):
    pass


def _error(error: Exception) -> RemoteCryptoError:
    value = _failure(error)
    return RemoteCryptoError(value.code, str(value))


def _wire(value) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise RemoteCryptoError(
            "invalid_argument", "Invalid remote crypto wire data."
        ) from None


def _bytes(value: bytes) -> None:
    if type(value) is not bytes:
        raise RemoteCryptoError("invalid_argument", "Supply caller-owned bytes.")


class RemoteHandshake:
    __slots__ = ("__native",)
    """Single-use opaque exchange. close/drop erases native ephemeral/key state."""

    def __init__(self, key: bytes, identity: RemoteIdentity, role: RemoteRole):
        _bytes(key)
        try:
            from ._native import NativeRemoteHandshake
        except ImportError:
            raise RemoteCryptoError(
                "native_binding_unavailable",
                "Install a native SDK build containing remote crypto.",
            ) from None
        try:
            self.__native = NativeRemoteHandshake(key, _wire(identity), role)
        except Exception as error:
            raise _error(error) from None

    def handshake(self) -> RemoteHandshakeWire:
        try:
            return json.loads(self.__native.handshake_json())
        except Exception as error:
            raise _error(error) from None

    def finish(self, remote: RemoteHandshakeWire) -> RemoteSession:
        try:
            encoded = _wire(remote)
        except BaseException as error:
            try:
                self.__native.close()
            except BaseException:
                pass
            if not isinstance(error, Exception):
                raise
            original = error if isinstance(error, RemoteCryptoError) else _error(error)
            raise original from None
        try:
            return RemoteSession(self.__native.finish(encoded))
        except Exception as error:
            raise _error(error) from None

    def close(self) -> None:
        try:
            self.__native.close()
        except Exception as error:
            raise _error(error) from None

    def __repr__(self) -> str:
        return "<RemoteHandshake>"


class RemoteSession:
    __slots__ = ("__native",)
    """Opaque Core session. Plaintext outputs belong to the caller."""

    def __init__(self, handle):
        self.__native = handle

    def seal(self, request_id: str, plaintext: bytes) -> RemoteEnvelope:
        _bytes(plaintext)
        try:
            return json.loads(self.__native.seal(request_id, plaintext))
        except Exception as error:
            raise _error(error) from None

    def open(self, request_id: str, envelope: RemoteEnvelope) -> bytes:
        try:
            return self.__native.open(request_id, _wire(envelope))
        except Exception as error:
            raise _error(error) from None

    def open_json_text(self, request_id: str, envelope: RemoteEnvelope) -> str:
        """Core-validated JSON serialization. open() preserves original bytes."""
        try:
            return self.__native.open_json_text(request_id, _wire(envelope))
        except Exception as error:
            raise _error(error) from None

    def close(self) -> None:
        try:
            self.__native.close()
        except Exception as error:
            raise _error(error) from None

    def __repr__(self) -> str:
        return "<RemoteSession>"
