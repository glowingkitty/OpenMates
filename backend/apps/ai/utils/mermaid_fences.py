# backend/apps/ai/utils/mermaid_fences.py
#
# Helpers for detecting assistant-generated Mermaid fenced blocks that should
# become Diagrams-owned direct embeds instead of generic Code embeds.
# Kept dependency-light so contract tests can validate the streaming behavior
# without loading the full task runtime and provider stack.

from __future__ import annotations

from typing import Optional, TypedDict


MERMAID_FENCE_LANGUAGES = {"mermaid", "mmd"}
MERMAID_KIND_TITLES = {
    "flowchart": "Flowchart",
    "graph": "Graph Diagram",
    "sequenceDiagram": "Sequence Diagram",
    "classDiagram": "Class Diagram",
    "stateDiagram": "State Diagram",
    "stateDiagram-v2": "State Diagram",
    "erDiagram": "Entity Relationship Diagram",
    "journey": "User Journey",
    "gantt": "Gantt Chart",
    "pie": "Pie Chart",
    "quadrantChart": "Quadrant Chart",
    "timeline": "Timeline",
    "mindmap": "Mind Map",
    "gitGraph": "Git Graph",
    "C4Context": "C4 Context Diagram",
}


class MermaidMetadata(TypedDict):
    language: str
    title: str
    diagram_kind: str
    line_count: int


def _is_mermaid_fence(language: Optional[str]) -> bool:
    return (language or "").strip().lower() in MERMAID_FENCE_LANGUAGES


def _extract_mermaid_kind(source: str) -> str:
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        return line.split(None, 1)[0]
    return "mermaid"


def _extract_mermaid_metadata(
    language: Optional[str],
    title: Optional[str],
    source: str,
) -> MermaidMetadata:
    diagram_kind = _extract_mermaid_kind(source)
    return {
        "language": "mermaid" if _is_mermaid_fence(language) else (language or ""),
        "title": (title or MERMAID_KIND_TITLES.get(diagram_kind) or "Mermaid Diagram").strip(),
        "diagram_kind": diagram_kind,
        "line_count": source.count("\n") + 1 if source else 0,
    }
