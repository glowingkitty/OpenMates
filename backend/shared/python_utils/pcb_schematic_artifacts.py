# backend/shared/python_utils/pcb_schematic_artifacts.py
#
# Small pure helpers for PCB schematic compile artifact records. The FastAPI
# route owns authentication and cache lookup; this module only finds a named
# artifact in a cached compile record and sanitizes its download filename. It is
# dependency-free so contract tests can exercise artifact behavior without
# importing the full API app stack.

from __future__ import annotations

from typing import Any


def get_cached_pcb_schematic_artifact(
    record: dict[str, Any],
    artifact_id: str,
) -> tuple[str, bytes] | None:
    for artifact in record.get("artifacts") or []:
        if not isinstance(artifact, dict) or artifact.get("id") != artifact_id:
            continue
        filename = str(artifact.get("name") or artifact_id).replace('"', "")
        content = str(artifact.get("content") or "")
        return filename, content.encode("utf-8")
    return None
