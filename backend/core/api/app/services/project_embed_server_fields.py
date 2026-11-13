"""Narrow server-owned refreshes for Project-linked application and test-result embeds.

A Project-linked embed is fenced: legacy writers get `project_context_required`
and changes go through the Project file operations. Two server writers still
own non-content fields of non-file links and publish a new version without a
client revision:

- application: `latest_screenshot` (thumbnail / preview frame reference),
  written by `EmbedService.update_application_embed_thumbnail`;
- test_result: run status (`is_current`, `stale_reason`, `run_status`), written by
  `refresh_test_result_currency`.

The server publishes the plaintext to the owning client, which encrypts it with
the embed key and stores it through `store_embed`. The ciphertext is opaque to
the server, so the allow-list is enforced where the server builds the update:
`grant_server_owned_refresh` refuses any change outside the kind's fields and
records a short-lived grant for exactly that embed and version. The store
handler passes the grant to the transaction extension, which admits it only for
links of that kind (never `file`) and only as the next version of the head.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

SERVER_OWNED_FIELDS: dict[str, frozenset[str]] = {
    "application": frozenset({"latest_screenshot", "latest_screenshot_url"}),
    "test_result": frozenset({"is_current", "stale_reason", "run_status"}),
}
# Bookkeeping the writers always change together with an allowed field.
_VERSION_FIELDS = frozenset({"version_number"})
GRANT_TTL_SECONDS = 60 * 60


class ServerOwnedFieldError(ValueError):
    """A server refresh tried to change a field outside its kind's allow-list."""


def _grant_key(embed_id: str) -> str:
    return f"embed:{embed_id}:server_owned_refresh"


def changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> set[str]:
    return {key for key in set(before) | set(after) if before.get(key) != after.get(key)}


def assert_server_owned_change(kind: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    """Raise unless `after` differs from `before` only in the kind's server-owned fields."""
    allowed = SERVER_OWNED_FIELDS.get(kind)
    if allowed is None:
        raise ServerOwnedFieldError(f"No server-owned fields for link kind {kind!r}")
    outside = changed_fields(before, after) - allowed - _VERSION_FIELDS
    if outside:
        raise ServerOwnedFieldError(f"Server refresh changes non-owned fields: {sorted(outside)}")


async def grant_server_owned_refresh(
    cache_service: Any, *, embed_id: str, kind: str, version_number: int,
    before: Mapping[str, Any], after: Mapping[str, Any],
) -> None:
    """Validate the change and allow the client to store exactly this version."""
    assert_server_owned_change(kind, before, after)
    if type(version_number) is not int or version_number < 2:
        raise ServerOwnedFieldError("A server refresh is always a later version")
    client = await cache_service.client
    if not client:
        raise RuntimeError("Redis is required to grant a server-owned embed refresh")
    await client.set(
        _grant_key(embed_id),
        json.dumps({"link_kind": kind, "version_number": version_number}),
        ex=GRANT_TTL_SECONDS,
    )


async def find_server_owned_refresh(
    cache_service: Any, embed_id: str, version_number: object,
) -> dict[str, Any] | None:
    """Return the grant for exactly this embed version, or None."""
    if type(version_number) is not int:
        return None
    client = await cache_service.client
    if not client:
        return None
    raw = await client.get(_grant_key(embed_id))
    if not raw:
        return None
    grant = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if (not isinstance(grant, dict) or grant.get("version_number") != version_number
            or grant.get("link_kind") not in SERVER_OWNED_FIELDS):
        return None
    return {"link_kind": grant["link_kind"], "version_number": version_number}


async def clear_server_owned_refresh(cache_service: Any, embed_id: str) -> None:
    client = await cache_service.client
    if client:
        await client.delete(_grant_key(embed_id))
