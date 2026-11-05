"""SDK-required partial same-Rust-read callback; explicit persistence and consent."""

from __future__ import annotations
import asyncio
import inspect
import json
from typing import Any, Awaitable, Callable, Literal, Protocol, TypedDict
from .essential_session import SessionDurableStore


class SessionFirstPageCapacity(TypedDict):
    scope: dict[str, Any]
    checkpoint_json_bytes: int


class SessionFirstPagePublication(TypedDict):
    kind: Literal["first_page"]
    source: Literal["first_page"]
    chat: dict[str, Any]
    cached: Literal[True]
    refreshing: Literal[True]
    history_complete: Literal[False]
    has_more_before: Literal[True]
    pii_restoration: Literal["page_local"]


class SessionFirstPageStore(SessionDurableStore, Protocol):
    async def admit_first_page(self, input: SessionFirstPageCapacity) -> bool:
        """Explicit prospective-total checkpoint admission; False skips optional preview only."""
        ...


SessionFirstPageCallback = Callable[
    [SessionFirstPagePublication], None | Awaitable[None]
]


async def read_chat_with_first_page(
    client,
    chat_id: str,
    store: SessionFirstPageStore,
    *,
    include_secrets: bool,
    include_private_output: bool,
    on_first_page: SessionFirstPageCallback,
) -> dict[str, Any]:
    from .session_client import SessionClientError

    epoch = client._essential_epoch
    if (
        include_secrets is not True
        or include_private_output is not True
        or not callable(on_first_page)
        or not callable(getattr(store, "admit_first_page", None))
        or not callable(getattr(store, "generation", None))
        or not callable(getattr(store, "compare_and_swap", None))
    ):
        raise SessionClientError(
            "invalid_argument",
            "Supply explicit credential/private-output consent, durable store and first-page callback.",
        )
    operation = None
    first_seen = False
    pending_source = None
    capacity_seen = False
    capacity_accepted = False

    def close():
        if operation is not None:
            try:
                client._native.first_page_close(operation)
            except Exception:
                pass

    def valid():
        if epoch != client._essential_epoch:
            raise SessionClientError(
                "cancelled", "The first-page read is no longer current."
            )

    def protocol():
        raise SessionClientError("protocol", "Invalid first-page continuation event.")

    opening = asyncio.create_task(
        client._prepared_call(
            client._native.first_page_open, lambda: (chat_id, True, True), epoch=epoch
        )
    )
    try:
        try:
            opened = json.loads(await asyncio.shield(opening))
        except asyncio.CancelledError:

            async def discard_admitted():
                try:
                    client._native.first_page_close(json.loads(await opening)["id"])
                except Exception:
                    pass

            asyncio.create_task(discard_admitted())
            raise
        if not isinstance(opened.get("id"), str):
            protocol()
        operation = opened["id"]
        valid()
        while True:
            event = json.loads(
                await client._essential_call(
                    lambda: client._native.first_page_next(operation)
                )
            )
            valid()
            if event.get("kind") == "capacity":
                if (
                    capacity_seen
                    or first_seen
                    or pending_source is not None
                    or not isinstance(event.get("id"), str)
                    or type(event.get("checkpoint_json_bytes")) is not int
                    or event["checkpoint_json_bytes"] < 0
                    or not isinstance(event.get("scope"), dict)
                ):
                    protocol()
                capacity_seen = True
                accepted = await store.admit_first_page(
                    {
                        "scope": event["scope"],
                        "checkpoint_json_bytes": event["checkpoint_json_bytes"],
                    }
                )
                valid()
                if type(accepted) is not bool:
                    protocol()
                capacity_accepted = accepted
                await client._call(
                    lambda: _sync_capacity(client, operation, event["id"], accepted)
                )
                valid()
                continue
            if event.get("kind") == "stage":
                source = event.get("source")
                if (
                    pending_source is not None
                    or source
                    not in (
                        "first_page",
                        "canonical",
                        "cache_settled",
                        "cached_offline",
                    )
                    or not isinstance(event.get("id"), str)
                    or not isinstance(event.get("checkpoint_json"), str)
                    or not isinstance(event.get("credentials_json"), str)
                    or not isinstance(event.get("ciphertext_sha256"), str)
                    or type(event.get("credential_revision")) is not int
                    or not isinstance(event.get("scope"), dict)
                ):
                    protocol()
                if source == "first_page" and (
                    not capacity_seen or not capacity_accepted or first_seen
                ):
                    protocol()
                expected = await store.generation(event["scope"])
                valid()
                receipt = await store.compare_and_swap(
                    {
                        "scope": event["scope"],
                        "expected_version": expected,
                        "next_version": event["id"],
                        "checkpoint_json": event["checkpoint_json"],
                        "credentials_json": event["credentials_json"],
                        "ciphertext_sha256": event["ciphertext_sha256"],
                        "credential_revision": event["credential_revision"],
                    }
                )
                valid()
                if not isinstance(receipt, dict) or receipt.get("stored") is not True:
                    raise SessionClientError(
                        "conflict", "The durable chat scope changed before persistence."
                    )
                # Only the actual writer's exact receipt is forwarded.
                actual = {
                    "ciphertext_sha256": receipt.get("ciphertext_sha256"),
                    "credential_revision": receipt.get("credential_revision"),
                }
                await client._call(
                    lambda: _sync_receipt(client, operation, event["id"], actual)
                )
                valid()
                pending_source = source
                continue
            chat = event.get("chat")
            if event.get("kind") == "first_page":
                if (
                    pending_source != "first_page"
                    or first_seen
                    or event.get("source") != "first_page"
                    or not isinstance(chat, dict)
                    or chat.get("id") != chat_id
                    or event.get("cached") is not True
                    or event.get("refreshing") is not True
                    or event.get("history_complete") is not False
                    or event.get("has_more_before") is not True
                    or event.get("pii_restoration") != "page_local"
                ):
                    protocol()
                pending_source = None
                first_seen = True
                result = on_first_page(event)
                if inspect.isawaitable(result):
                    await result
                valid()
                # The next pull resumes the original Rust read after callback.
                continue
            if event.get("kind") == "completed":
                if (
                    pending_source
                    not in ("canonical", "cache_settled", "cached_offline")
                    or event.get("source") != pending_source
                    or not isinstance(chat, dict)
                    or chat.get("id") != chat_id
                    or not isinstance(chat.get("messages"), list)
                    or event.get("refreshing") is not False
                ):
                    protocol()
                if pending_source == "canonical":
                    if (
                        event.get("cached") is not False
                        or event.get("history_complete") is not True
                        or event.get("pii_restoration") != "all_user_rows"
                        or event.get("has_more_before") is not False
                    ):
                        protocol()
                elif (
                    event.get("cached") is not True
                    or event.get("history_complete") is not False
                    or event.get("pii_restoration")
                    != (
                        "all_cached_user_rows"
                        if pending_source == "cache_settled"
                        else "page_local"
                    )
                ):
                    protocol()
                valid()
                return event
            protocol()
    finally:
        close()


async def _sync_receipt(client, operation, stage, receipt):
    client._native.first_page_receipt(
        operation, stage, json.dumps(receipt, allow_nan=False)
    )


async def _sync_capacity(client, operation, stage, accepted):
    client._native.first_page_capacity(operation, stage, accepted)
