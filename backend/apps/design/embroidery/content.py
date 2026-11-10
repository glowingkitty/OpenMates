"""Result content of a design.embroidery child embed and the assistant-facing summary.

The embed content carries everything the result views need, including the
per-result key and the stored file descriptors. The summary returned to the
assistant carries the numbers, threads and notes only, never keys or storage
details (assertions design-embroidery.result.complete-and-truthful and
design-embroidery.surface.semantic-parity).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

CHILD_TYPE = "embroidery_design"

INVALID_SOURCE_MESSAGE = (
    "Embroidery needs a vector graphic from this chat. Create one first with images.generate "
    "(output_filetype svg) or turn the image into one with images.vectorize, then call design.embroidery "
    "with that graphic's embed_ref."
)

# Fields the assistant receives when the conversion ends (also allowed by generated_media_graph).
SUMMARY_FIELDS: tuple[str, ...] = (
    "title", "width_mm", "height_mm", "stitch_count", "thread_changes", "estimated_minutes",
    "hoop", "fits_hoop", "fabric", "reworked", "threads", "notes",
)


def _number(summary: Mapping[str, Any], key: str) -> float:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Embroidery summary is missing {key}")
    return value


def _threads(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    threads = summary.get("threads")
    if not isinstance(threads, list) or not threads:
        raise ValueError("Embroidery summary has no threads")
    return [
        {"colour_hex": str(row.get("colour_hex") or ""), "name": str(row.get("name") or ""),
         "stitch_count": int(row.get("stitch_count") or 0)}
        for row in threads if isinstance(row, Mapping)
    ]


def _note(row: Mapping[str, Any]) -> dict[str, Any]:
    """Note as ``{code, text}`` plus the whole-number ``count`` that its translation needs."""
    note: dict[str, Any] = {"code": str(row.get("code") or ""), "text": str(row.get("text") or "")}
    count = row.get("count")
    if isinstance(count, int) and not isinstance(count, bool):
        note["count"] = count
    return note


def _notes(summary_notes: Any, extra_notes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [*(summary_notes if isinstance(summary_notes, list) else []), *extra_notes]
    return [note for note in (_note(row) for row in rows if isinstance(row, Mapping)) if note["text"]]


def build_finished_content(
    *,
    skill_id: str,
    title: str,
    summary: Mapping[str, Any],
    extra_notes: Sequence[Mapping[str, Any]],
    hoop: str,
    fabric: str,
    reworked: bool,
    files_metadata: Mapping[str, Any],
    s3_base_url: str,
    aes_key_b64: str,
    nonce_b64: str,
    vault_wrapped_aes_key: str,
    source_embed_ref: str,
    source_embed_id: str,
    billing_status: str,
) -> dict[str, Any]:
    """Every number comes from the sandbox summary of the delivered files, never from the request."""
    fits_hoop = summary.get("fits_hoop")
    if fits_hoop not in ("yes", "no", "not_checked"):
        raise ValueError("Embroidery summary has an invalid fits_hoop value")
    return {
        "app_id": "design",
        "skill_id": skill_id,
        "type": CHILD_TYPE,
        "status": "finished",
        "title": title,
        "width_mm": _number(summary, "width_mm"),
        "height_mm": _number(summary, "height_mm"),
        "stitch_count": int(_number(summary, "stitch_count")),
        "thread_changes": int(_number(summary, "thread_changes")),
        "estimated_minutes": int(round(_number(summary, "estimated_minutes"))),
        "hoop": hoop,
        "fits_hoop": fits_hoop,
        "fabric": fabric,
        "reworked": reworked,
        "threads": _threads(summary),
        "notes": _notes(summary.get("notes"), extra_notes),
        "files": dict(files_metadata),
        "s3_base_url": s3_base_url,
        "aes_key": aes_key_b64,
        "aes_nonce": nonce_b64,
        "vault_wrapped_aes_key": vault_wrapped_aes_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_embed_ref": source_embed_ref,
        "input_embed_ids": [source_embed_id],
        "billing_status": billing_status,
    }


def build_failed_content(
    *, skill_id: str, title: str, hoop: str, fabric: str, error_code: str, user_message: str,
    source_embed_ref: str, source_embed_id: str,
) -> dict[str, Any]:
    """A failed result: the reason in plain words, no files and no charge."""
    return {
        "app_id": "design",
        "skill_id": skill_id,
        "type": CHILD_TYPE,
        "status": "error",
        "title": title,
        "hoop": hoop,
        "fabric": fabric,
        "reworked": False,
        "threads": [],
        "notes": [],
        "files": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_embed_ref": source_embed_ref,
        "input_embed_ids": [source_embed_id] if source_embed_id else [],
        "billing_status": "not_charged",
        "error": user_message,
        "error_code": error_code,
    }


def assistant_summary(content: Mapping[str, Any]) -> dict[str, Any]:
    """The numbers, threads and notes the assistant may tell the user about."""
    return {key: content[key] for key in SUMMARY_FIELDS if key in content}
