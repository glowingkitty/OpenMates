"""Search-result cards (image, web, news and video search) as skill inputs.

A search result child carries its text (title, description, source, address,
date) and often a public picture address (``image_url`` of an image result, the
flattened ``thumbnail_original`` of a web/news/video result). A result without
a picture is still a valid input through its text (``read_result_reference``);
a whole search (the skill-use parent) expands to its owned results
(``expand_search_parent``).
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
  matches the exact ``embed_ref`` of a child or of the parent itself (owner-checked).

The text of a result is third-party data: ``result_text`` keeps only known
plain fields, removes invisible (ASCII-smuggling) characters, collapses
whitespace and bounds every field and the whole block. Callers that hand it to
a model must still delimit it as untrusted data.
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
# Text fields of a (flattened) result card, first match wins per label.
TEXT_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Source", ("profile_name", "source", "source_name", "site_name", "og_sitename", "channel_title",
                "meta_url_hostname", "source_domain")),
    ("Published", ("page_age", "published_at", "published", "date", "age", "upload_date")),
    ("URL", ("url", "source_page_url", "page_url", "link")),
    ("Description", ("description", "snippet", "summary")),
    ("More", ("extra_snippets",)),
)
MAX_TITLE_CHARS = 200
MAX_TEXT_FIELD_CHARS = 400  # one field of a result's text block
MAX_RESULT_TEXT_CHARS = 900  # the whole text block of one result
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


@dataclass(frozen=True)
class ResultReference:
    """One owned search result: its picture address (``None`` when it has none), title and bounded text."""

    embed_id: str
    url: Optional[str]
    title: str
    text: str  # "Label: value" lines (source, published, URL, description, more); third-party data


def _clean(value: Any, limit: int) -> str:
    """Plain, single-spaced, invisible-character-free text of at most ``limit`` characters."""
    from backend.core.api.app.utils.text_sanitization import sanitize_text_simple

    if isinstance(value, (list, tuple)):
        value = " | ".join(str(item) for item in value if isinstance(item, (str, int, float)))
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = " ".join(sanitize_text_simple(str(value)).replace("|", " | ").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


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
            return _clean(value, MAX_TITLE_CHARS)
    return ""


def result_text(content: Mapping[str, Any]) -> str:
    """The bounded text block of one result card (title apart), e.g. "Source: …\\nURL: …"."""
    lines: list[str] = []
    for label, fields in TEXT_FIELDS:
        for field in fields:
            raw = content.get(field)
            if label == "URL" and not (isinstance(raw, str) and raw.startswith(("https://", "http://"))):
                continue
            value = _clean(raw, MAX_TEXT_FIELD_CHARS)
            if value:
                lines.append(f"{label}: {value}")
                break
    text = "\n".join(lines)
    return text if len(text) <= MAX_RESULT_TEXT_CHARS else text[:MAX_RESULT_TEXT_CHARS - 1].rstrip() + "…"


def search_parent_children(content: Mapping[str, Any]) -> list[str]:
    """The result ids of a whole search (skill-use parent of a search skill); empty for anything else."""
    if (content.get("app_id"), content.get("skill_id")) not in PICTURE_RESULT_SKILLS:
        return []
    return _child_ids(content)


def is_search_result(content: Mapping[str, Any]) -> bool:
    """A single search-result card: no stored file of its own, from a search skill or carrying a picture address."""
    if content.get("files") or content.get("s3_base_url") or _child_ids(content):
        return False
    from_search = (content.get("app_id"), content.get("skill_id")) in PICTURE_RESULT_SKILLS
    return from_search or picture_url(content) is not None


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
        parent_ref = content.get("embed_ref")
        if parent_ref in wanted and parent_ref not in found:
            found[parent_ref] = parent_id  # the whole search; it expands to its results when used
        for child_id in _child_ids(content):
            child = await read_content(child_id)
            if child is None:
                continue
            child_record, child_content = child
            ref = child_content.get("embed_ref")
            if ref in wanted and ref not in found and _owned(child_record, owner_hash):
                found[ref] = child_id
    return found


def owns(record: Mapping[str, Any], owner_hash: str) -> bool:
    """Whether the embed record belongs to the caller (hashed user id)."""
    return _owned(record, owner_hash)


async def read_result_reference(embed_id: str, *, read_content: ContentReader, owner_hash: str
                                ) -> ResultReference:
    """Picture address (if any), title and text of one owned search result; raise when it is not readable."""
    loaded = await read_content(embed_id)
    if loaded is None:
        raise ResultPictureUnavailable(
            "This search result is no longer readable by the server; search again to use it."
        )
    record, content = loaded
    if not _owned(record, owner_hash):
        raise ResultPictureUnavailable("This search result is not available to this caller.")
    return ResultReference(embed_id=embed_id, url=picture_url(content), title=result_title(content),
                           text=result_text(content))


async def read_result_picture(embed_id: str, *, read_content: ContentReader, owner_hash: str) -> ResultPicture:
    """The public picture address and title of one owned search result; raise when it has none."""
    reference = await read_result_reference(embed_id, read_content=read_content, owner_hash=owner_hash)
    if reference.url is None:
        raise ResultPictureUnavailable("This search result has no picture.")
    return ResultPicture(embed_id=embed_id, url=reference.url, title=reference.title)


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
