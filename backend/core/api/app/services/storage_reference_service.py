"""Build an authoritative view of S3 references stored in Directus rows.

The collector is intentionally pure: callers fetch bounded rows, then use this
module to merge current embed and upload metadata. Malformed legacy references
remain explicit ambiguity and must never become deletion authority.
See contracts/architecture/storage-lifecycle/contract.yml.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_UPLOAD_BUCKET = "chatfiles"


@dataclass(frozen=True)
class StorageReferenceInventory:
    references: set[tuple[str, str]]
    ambiguous: list[dict[str, str]]


def collect_storage_references(
    *,
    embeds: Iterable[dict[str, Any]],
    uploads: Iterable[dict[str, Any]],
) -> StorageReferenceInventory:
    """Merge valid object references and retain malformed records as ambiguity."""
    references: set[tuple[str, str]] = set()
    ambiguous: list[dict[str, str]] = []

    for embed in embeds:
        record_id = str(embed.get("id") or "unknown")
        entries = embed.get("s3_file_keys")
        if not isinstance(entries, list):
            if entries is not None:
                ambiguous.append(_ambiguity("embed", record_id, "invalid_reference_list"))
            continue
        for entry in entries:
            bucket = entry.get("bucket") if isinstance(entry, dict) else None
            key = entry.get("key") if isinstance(entry, dict) else None
            if not _non_empty(bucket) or not _non_empty(key):
                ambiguous.append(_ambiguity("embed", record_id, "missing_object_key"))
                continue
            references.add((bucket, key))

    for upload in uploads:
        record_id = str(upload.get("id") or "unknown")
        metadata = upload.get("files_metadata")
        if not isinstance(metadata, dict):
            if metadata is not None:
                ambiguous.append(_ambiguity("upload", record_id, "invalid_files_metadata"))
            continue
        for variant in metadata.values():
            key = variant.get("s3_key") if isinstance(variant, dict) else None
            if not _non_empty(key):
                ambiguous.append(_ambiguity("upload", record_id, "missing_object_key"))
                continue
            references.add((DEFAULT_UPLOAD_BUCKET, key))

    return StorageReferenceInventory(references=references, ambiguous=ambiguous)


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ambiguity(source: str, record_id: str, reason: str) -> dict[str, str]:
    return {"source": source, "record_id": record_id, "reason": reason}
