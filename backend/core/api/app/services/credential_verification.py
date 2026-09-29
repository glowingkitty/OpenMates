"""Server-owned method binding for lookup credentials.

Legacy ``lookup_hashes`` are deliberately untyped.  They can keep an ordinary
login working during migration, but cannot grant a method-specific exemption.
"""

from __future__ import annotations

import json
from typing import Mapping
from fastapi import HTTPException


def typed_lookup_method(record: object, lookup_hash: str) -> str | None:
    if not isinstance(lookup_hash, str) or not lookup_hash:
        return None
    """Return the enrolled method only for a well-formed server-stored binding."""
    if isinstance(record, str):
        try:
            record = json.loads(record)
        except ValueError:
            return None
    if not isinstance(record, Mapping):
        return None
    matched = [method for method, value in record.items()
               if isinstance(method, str) and (
                   value == lookup_hash if isinstance(value, str) else
                   isinstance(value, Mapping) and value.get("lookup_hash") == lookup_hash
               )]
    return matched[0] if len(matched) == 1 else None


def typed_lookup_wrapper(record: object, method: str, lookup_hash: str) -> str | None:
    """Resolve only a matching typed credential's committed wrapper pointer."""
    if isinstance(record, str):
        try:
            record = json.loads(record)
        except ValueError:
            return None
    if not isinstance(record, Mapping) or typed_lookup_method(record, lookup_hash) != method:
        return None
    value = record.get(method)
    if isinstance(value, str):
        return method
    wrapper = value.get("wrapper_method") if isinstance(value, Mapping) else None
    return wrapper if isinstance(wrapper, str) and wrapper else None


def replace_typed_lookup(record: object, method: str, lookup_hash: str, *, wrapper_method: str | None = None) -> dict:
    """Prepare a replacement mapping without modifying the source record."""
    if isinstance(record, str):
        try:
            record = json.loads(record)
        except ValueError:
            record = None
    result = {key: value for key, value in record.items()
              if isinstance(key, str) and (isinstance(value, str) or isinstance(value, Mapping))} if isinstance(record, Mapping) else {}
    result[method] = {"lookup_hash": lookup_hash, "wrapper_method": wrapper_method} if wrapper_method else lookup_hash
    return result


async def acquire_credential_change_lock(cache, user_id: str, method: str):
    """Serialize all credential-map writes for an account across API workers."""
    client = await cache.client
    if client is None:
        raise HTTPException(503, "Credential storage unavailable")
    # Password, recovery, and passkey changes all rewrite the same users-row
    # lookup array and typed map; method-specific locks can lose each other's
    # updates even when each individual write is atomic.
    lock = client.lock(f"auth:credential-change:{user_id}", timeout=60)
    if not await lock.acquire(blocking=False):
        raise HTTPException(409, "Credential update already in progress")
    return lock


async def release_credential_change_lock(lock) -> None:
    if lock is None:
        return
    try:
        await lock.release()
    except Exception:
        # An expired lock cannot be released by this worker.
        pass
