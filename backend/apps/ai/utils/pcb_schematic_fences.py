# backend/apps/ai/utils/pcb_schematic_fences.py
#
# Helpers for detecting assistant-generated atopile fenced blocks that should
# become Electronics-owned PCB schematic embeds instead of generic Code embeds.
# Kept dependency-light so unit tests can validate the contract without loading
# the full streaming task runtime and its Celery dependencies.

from __future__ import annotations

import re
from typing import Optional, TypedDict


PCB_SCHEMATIC_FENCE_LANGUAGES = {"atopile", "ato", "pcb_schematic"}
DEFAULT_PCB_SCHEMATIC_FILENAME = "board.ato"


class PcbSchematicMetadata(TypedDict):
    language: str
    filename: str
    module_name: str | None
    title: str | None
    line_count: int


def _is_pcb_schematic_fence(language: Optional[str]) -> bool:
    return (language or "").strip().lower().replace("-", "_") in PCB_SCHEMATIC_FENCE_LANGUAGES


def _safe_pcb_schematic_filename(filename: Optional[str], module_name: Optional[str]) -> str:
    raw = (filename or "").strip()
    if raw:
        raw = raw.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
        if raw and not raw.lower().endswith(".ato"):
            raw = f"{raw}.ato"
        if raw:
            return raw[:120]

    if module_name:
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", module_name).lower()
        snake = re.sub(r"[^a-z0-9_]+", "_", snake).strip("_")
        if snake:
            return f"{snake}.ato"

    return DEFAULT_PCB_SCHEMATIC_FILENAME


def _extract_pcb_schematic_module_name(source: str) -> str | None:
    match = re.search(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", source, re.MULTILINE)
    return match.group(1) if match else None


def _extract_pcb_schematic_metadata(
    language: Optional[str],
    filename: Optional[str],
    source: str,
) -> PcbSchematicMetadata:
    module_name = _extract_pcb_schematic_module_name(source)
    normalized_language = "atopile" if _is_pcb_schematic_fence(language) else (language or "")
    return {
        "language": normalized_language,
        "filename": _safe_pcb_schematic_filename(filename, module_name),
        "module_name": module_name,
        "title": module_name,
        "line_count": source.count("\n") + 1 if source else 0,
    }
