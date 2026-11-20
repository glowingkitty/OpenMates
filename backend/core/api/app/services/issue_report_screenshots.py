"""Helpers for the several screenshots attached to one issue report.

Screenshots are stored unencrypted in the private issue_logs S3 bucket; only
their keys are encrypted in Directus. Newer rows keep every key as an encrypted
JSON array in `encrypted_screenshot_s3_keys`; the legacy single-key field
`encrypted_screenshot_s3_key` always holds the first key, so older readers and
rows written before the list field existed keep working.
"""

import base64
import binascii
import json
from typing import Any, List, Optional, Sequence, Tuple

MAX_ISSUE_SCREENSHOTS = 5
MAX_SCREENSHOT_B64_CHARS = 3_000_000
MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024


def combine_screenshot_inputs(
    legacy: Optional[str], items: Optional[Sequence[str]]
) -> List[str]:
    """Legacy single screenshot counts as the first item, then the list."""
    combined: List[str] = []
    if legacy:
        combined.append(legacy)
    if items:
        combined.extend(item for item in items if item)
    return combined


def decode_screenshot(raw: str) -> Optional[bytes]:
    """Decode one base64 PNG (data URL prefix allowed).

    Returns None when the payload is not valid base64 or exceeds 2 MB decoded.
    """
    value = raw.strip()
    if value.startswith("data:"):
        value = value.split(",", 1)[1] if "," in value else ""
    try:
        data = base64.b64decode(value)
    except (binascii.Error, ValueError):
        return None
    if not data or len(data) > MAX_SCREENSHOT_BYTES:
        return None
    return data


def decode_screenshots(raw_items: Sequence[str]) -> Tuple[List[bytes], int]:
    """Decode all items; returns (decoded images, number skipped)."""
    decoded: List[bytes] = []
    skipped = 0
    for raw in raw_items:
        data = decode_screenshot(raw)
        if data is None:
            skipped += 1
        else:
            decoded.append(data)
    return decoded, skipped


async def decrypt_screenshot_keys(issue: dict[str, Any], encryption_service: Any) -> List[str]:
    """Return all screenshot S3 keys of an issue row (new list field, else legacy)."""
    encrypted_list = issue.get("encrypted_screenshot_s3_keys")
    if encrypted_list:
        decrypted = await encryption_service.decrypt_issue_report_data(encrypted_list)
        if decrypted:
            parsed = json.loads(decrypted)
            if isinstance(parsed, list):
                return [key for key in parsed if isinstance(key, str) and key]
    legacy = issue.get("encrypted_screenshot_s3_key")
    if legacy:
        key = await encryption_service.decrypt_issue_report_data(legacy)
        if key:
            return [key]
    return []


def issue_has_screenshots(issue: dict[str, Any]) -> bool:
    """True when the row references at least one screenshot (either field)."""
    return bool(
        issue.get("encrypted_screenshot_s3_keys") or issue.get("encrypted_screenshot_s3_key")
    )
