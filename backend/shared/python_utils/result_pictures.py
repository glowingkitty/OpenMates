"""Pictures of search-result cards (image, web, news and video search) as skill inputs.

A search result child carries a public picture address (``image_url`` of an
image result, the flattened ``thumbnail_original`` of a web/news/video result).
The server reads a result's content only through its own Vault-encrypted cache
copy (``embed:<id>`` with ``encrypted_content`` ``vault:...``), which the result
writer stores for the owner; the durable record is client-encrypted and never
decrypted here. The cache copy expires with the embed cache TTL, so a result
older than that cannot be used and fails explicitly.

Reference resolution, exact only:

- same turn: ``collect_result_ref_index`` binds each result's ``embed_ref`` to
  the child UUID the server-side writer returned (same authority rule as the
  web source bindings), and the main processor adds them to the turn's file index;
- earlier turns: the history only indexes the skill-use parent, so
  ``resolve_result_refs`` reads indexed search parents and their children and
  matches the exact ``embed_ref`` (owner-checked).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

PICTURE_RESULT_SKILLS = frozenset({("images", "search"), ("web", "search"), ("news", "search"), ("videos", "search")})
PICTURE_URL_FIELDS = ("image_url", "thumbnail_original", "thumbnail_url", "og_image", "thumbnail_src")
TITLE_FIELDS = ("title", "name", "headline")
MAX_SCANNED_PARENTS = 24
MAX_CHILDREN_PER_PARENT = 50
_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~:-]{0,127}\Z")

# (record, decoded content) of one embed, or None when the server has no readable copy.
ContentReader = Callable[[str], Awaitable[Optional[tuple[Mapping[str, Any], Mapping[str, Any]]]]]


class ResultPictureUnavailable(RuntimeError):
    """A search-result picture could not be read or fetched; nothing is made or charged."""


@dataclass(frozen=True)
class ResultPicture:
    embed_id: str
    url: str
    title: str


def picture_url(content: Mapping[str, Any]) -> Optional[str]:
    for field in PICTURE_URL_FIELDS:
        value = content.get(field)
        if isinstance(value, str) and value.startswith("https://"):
            return value
    thumbnail = content.get("thumbnail")
    if isinstance(thumbnail, Mapping):
        for field in ("original", "src"):
            value = thumbnail.get(field)
            if isinstance(value, str) and value.startswith("https://"):
                return value
    return None


def result_title(content: Mapping[str, Any]) -> str:
    for field in TITLE_FIELDS:
        value = content.get(field)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:200]
    return ""


def collect_result_ref_index(*, app_id: str, skill_id: str, results: Sequence[Mapping[str, Any]],
                             authored_embeds: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Exact ``embed_ref → child UUID`` of this turn's finished search results that may carry a picture.

    The writer must have returned one distinct child UUID per result in result
    order; otherwise nothing is bound.
    """
    if (app_id, skill_id) not in PICTURE_RESULT_SKILLS or not results:
        return {}
    child_ids: list[str] = []
    for embed in authored_embeds:
        if not isinstance(embed, Mapping) or embed.get("status", "finished") != "finished":
            return {}
        ids = embed.get("child_embed_ids")
        if not isinstance(ids, list):
            return {}
        for child_id in ids:
            try:
                child_ids.append(str(uuid.UUID(str(child_id))))
            except (TypeError, ValueError, AttributeError):
                return {}
    if len(child_ids) != len(results) or len(set(child_ids)) != len(child_ids):
        return {}
    index: dict[str, str] = {}
    for result, child_id in zip(results, child_ids):
        ref = result.get("embed_ref") if isinstance(result, Mapping) else None
        if not isinstance(ref, str) or not _REF_PATTERN.fullmatch(ref) or ref in index:
            return {}
        index[ref] = child_id
    return index


def _child_ids(content: Mapping[str, Any]) -> list[str]:
    raw = content.get("embed_ids")
    if isinstance(raw, str):
        return [value.strip() for value in raw.split("|") if value.strip()][:MAX_CHILDREN_PER_PARENT]
    if isinstance(raw, list):
        return [value for value in raw if isinstance(value, str)][:MAX_CHILDREN_PER_PARENT]
    return []


def _owned(record: Mapping[str, Any], owner_hash: str) -> bool:
    return record.get("hashed_user_id") == owner_hash


async def resolve_result_refs(refs: Sequence[str], file_path_index: Mapping[str, str], *, read_content: ContentReader,
                              owner_hash: str) -> dict[str, str]:
    """Find earlier-turn search results by exact ``embed_ref`` under the indexed search parents.

    Returns only the refs that were found; the caller fails the call for the rest.
    """
    wanted = {ref for ref in refs if ref not in file_path_index}
    found: dict[str, str] = {}
    if not wanted:
        return found
    scanned = 0
    for parent_id in dict.fromkeys(file_path_index.values()):
        if scanned >= MAX_SCANNED_PARENTS or len(found) == len(wanted):
            break
        parent = await read_content(parent_id)
        if parent is None:
            continue
        record, content = parent
        if ((content.get("app_id"), content.get("skill_id")) not in PICTURE_RESULT_SKILLS
                or not _owned(record, owner_hash)):
            continue
        scanned += 1
        for child_id in _child_ids(content):
            child = await read_content(child_id)
            if child is None:
                continue
            child_record, child_content = child
            ref = child_content.get("embed_ref")
            if ref in wanted and ref not in found and _owned(child_record, owner_hash):
                found[ref] = child_id
    return found


async def read_result_picture(embed_id: str, *, read_content: ContentReader, owner_hash: str) -> ResultPicture:
    """The public picture address and title of one owned search result; raise when it has none."""
    loaded = await read_content(embed_id)
    if loaded is None:
        raise ResultPictureUnavailable(
            "This search result is no longer readable by the server; search again to use its picture."
        )
    record, content = loaded
    if not _owned(record, owner_hash):
        raise ResultPictureUnavailable("This search result is not available to this caller.")
    url = picture_url(content)
    if url is None:
        raise ResultPictureUnavailable("This search result has no picture.")
    return ResultPicture(embed_id=embed_id, url=url, title=result_title(content))


def vault_content_reader(*, cache_service: Any, encryption_service: Any, user_vault_key_id: str) -> ContentReader:
    """Read an embed's Vault-encrypted cache copy; durable client ciphertext is never decrypted."""
    import json

    from toon_format import decode

    async def read(embed_id: str) -> Optional[tuple[Mapping[str, Any], Mapping[str, Any]]]:
        client = await cache_service.client
        raw = await client.get(f"embed:{embed_id}") if client else None
        if not raw:
            return None
        record = raw if isinstance(raw, dict) else json.loads(raw)
        encrypted = record.get("encrypted_content") if isinstance(record, dict) else None
        if not isinstance(encrypted, str) or not encrypted.startswith("vault:"):
            return None
        plaintext = await encryption_service.decrypt_with_user_key(encrypted, user_vault_key_id)
        if not plaintext:
            return None
        content = decode(plaintext)
        return (record, content) if isinstance(content, dict) else None

    return read
