"""Chat search grants carried by an approved Memory response (app-memories.references.embeds-and-chats).

Referencing a chat in a Memory is the user's consent for the main processor to
search that chat while the Memory is loaded. The client resolves references with
the reader's own keys and returns the referenced chat ids as
``approved_search_chat_ids`` next to the approved Memory entries. The server
cannot read the Memory, so it only accepts ids that arrive with an approved
response for a Memory id it actually requested, caps them, drops the current
chat and keeps only chats the user owns. No other chat becomes searchable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

MAX_APPROVED_SEARCH_CHATS = 10
MEMORY_RESPONSE_APP_ID = "memory"
_REQUEST_KEY_PREFIXES = ("memory:", "memory-")


def requested_memory_ids(requested_keys: Iterable[object]) -> set[str]:
    """Memory ids named by the pending request keys (``memory:<id>`` or ``memory-<id>``)."""
    ids: set[str] = set()
    for key in requested_keys:
        if not isinstance(key, str):
            continue
        for prefix in _REQUEST_KEY_PREFIXES:
            if key.startswith(prefix) and len(key) > len(prefix):
                ids.add(key[len(prefix):])
                break
    return ids


def confirmed_memory_ids(entries: object) -> set[str]:
    """Memory ids the client actually answered with content."""
    if not isinstance(entries, list):
        return set()
    return {
        item["item_key"] for item in entries
        if isinstance(item, dict) and item.get("app_id") == MEMORY_RESPONSE_APP_ID
        and isinstance(item.get("item_key"), str) and item.get("content") is not None
    }


def candidate_chat_ids(raw: object, *, current_chat_id: str) -> list[str]:
    """Deduplicated, bounded string ids; the current chat is never a grant."""
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for value in raw:
        if isinstance(value, str) and value and len(value) <= 240 and value != current_chat_id and value not in seen:
            seen.append(value)
        if len(seen) >= MAX_APPROVED_SEARCH_CHATS:
            break
    return seen


async def approved_search_chat_ids(
    raw: object, *, entries: object, requested_keys: Iterable[object], current_chat_id: str,
    is_owned: Callable[[str], Awaitable[bool]],
) -> list[str]:
    """Grant only for a response that answers a requested Memory id; owned chats only."""
    if not (confirmed_memory_ids(entries) & requested_memory_ids(requested_keys)):
        return []
    granted: list[str] = []
    for chat_id in candidate_chat_ids(raw, current_chat_id=current_chat_id):
        if await is_owned(chat_id):
            granted.append(chat_id)
    return granted


def is_chat_searchable(approved_ids: Iterable[str] | None, chat_id: str) -> bool:
    """Single gate for chat search in a turn: only chats in the approved set."""
    return bool(chat_id) and chat_id in set(approved_ids or ())
