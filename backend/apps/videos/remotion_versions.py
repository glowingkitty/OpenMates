# backend/apps/videos/remotion_versions.py
#
# Linear source-version helpers for videos.create Remotion embeds. Restoring an
# older version truncates later versions instead of creating branches so the
# product remains simple and predictable.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RestoredRemotionVersion:
    current_source_version: int
    source: str
    remaining_versions: list[dict[str, Any]]
    truncated_versions: list[int]
    status: str = "needs_rerender"


def restore_remotion_source_version(*, versions: list[dict[str, Any]], target_version: int) -> RestoredRemotionVersion:
    sorted_versions = sorted(versions, key=lambda item: int(item.get("version") or 0))
    target = next((item for item in sorted_versions if int(item.get("version") or 0) == target_version), None)
    if target is None:
        raise ValueError(f"Remotion source version {target_version} does not exist")

    remaining = [item for item in sorted_versions if int(item.get("version") or 0) <= target_version]
    truncated = [int(item.get("version") or 0) for item in sorted_versions if int(item.get("version") or 0) > target_version]
    source = str(target.get("source") or target.get("remotion_source") or "")
    return RestoredRemotionVersion(
        current_source_version=target_version,
        source=source,
        remaining_versions=remaining,
        truncated_versions=truncated,
    )
