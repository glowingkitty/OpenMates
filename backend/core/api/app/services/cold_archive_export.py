"""Shared bounded ciphertext export for authorized cold archive manifests."""

from __future__ import annotations

import base64
from typing import Any, AsyncIterator

from backend.core.api.app.services.bounded_archive_io import read_verified_bytes
from backend.core.api.app.services.cold_archive_service import MAX_ARCHIVE_PART_BYTES


class ColdArchiveExportError(ValueError):
    """A required cold archive cannot be exported completely."""


def cold_archive_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: manifest.get(key) for key in (
        "archive_id", "resource_type", "resource_id", "active_generation",
        "encrypted_listing_metadata", "graph_checksum", "part_count", "archived_at",
    )}


async def iter_cold_archive_parts(export: Any, manifest: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Read a previously authorized generation without decrypting or expanding it.

    The returned part bytes are the immutable gzip representation of client
    ciphertext records. Object keys and regional routing remain server-private.
    """
    archive_id = manifest.get("archive_id")
    generation = manifest.get("active_generation")
    expected_parts = manifest.get("part_count")
    if (not isinstance(archive_id, str) or not archive_id
            or type(generation) is not int or generation < 1
            or type(expected_parts) is not int or expected_parts < 1):
        raise ColdArchiveExportError("cold_archive_metadata_invalid")
    count = 0
    parts = export._iter_items_bounded(
        collection="cold_archive_parts",
        params={"filter[archive_id][_eq]": archive_id, "filter[generation][_eq]": generation, "sort": "part_number"},
        admin_required=True,
    )
    async for part in parts:
        if (part.get("archive_id") != archive_id or type(part.get("generation")) is not int
                or part["generation"] != generation or type(part.get("part_number")) is not int
                or part["part_number"] != count + 1
                or count >= expected_parts):
            raise ColdArchiveExportError("cold_archive_metadata_invalid")
        try:
            if export.s3_service is None or part.get("logical_bucket") != "cold_archives":
                raise ValueError("Archive storage unavailable or invalid")
            states = part.get("regional_states")
            if not isinstance(states, dict) or type(part.get("size_bytes")) is not int:
                raise ValueError("Archive metadata invalid")
            content = await read_verified_bytes(
                export.s3_service, part["object_key"], checksum=part["checksum"],
                size_bytes=part["size_bytes"], max_bytes=MAX_ARCHIVE_PART_BYTES,
                regions=[region for region, state in states.items() if state == "verified"],
            )
        except Exception as exc:
            raise ColdArchiveExportError("cold_archive_integrity_failed") from exc
        count += 1
        yield {
            "part_id": part.get("part_id"), "part_number": part["part_number"],
            "generation": generation, "checksum": part["checksum"], "size_bytes": len(content),
            "encoding": "base64-gzip", "ciphertext": base64.b64encode(content).decode("ascii"),
        }
    if count != expected_parts:
        raise ColdArchiveExportError("missing_cold_archive_part")


async def export_cold_archive(export: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    """Compatibility artifact for the existing aggregate Team export surface."""
    item = cold_archive_metadata(manifest)
    item["parts"] = [part async for part in iter_cold_archive_parts(export, manifest)]
    return item
