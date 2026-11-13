# backend/apps/ai/tasks/loose_application_files.py
"""Recover generated app files that a model wrote outside any code fence.

Models sometimes close a combined application-preview block early and stream the
remaining script sources as plain text sections that start with a file header
line (``javascript:src/main.jsx``). The stream consumer only turns fenced files
into file embeds, so these sources stayed chat text and the Project app had no
entry script. Once an application embed exists, the consumer uses this splitter
to turn such sections into late application files. Spec: feature.projects.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

FileHeaderParser = Callable[[str], Optional[Dict[str, str]]]


def split_loose_application_files(
    text: str,
    parse_header: FileHeaderParser,
) -> Tuple[List[Dict[str, str]], str]:
    """Return the unfenced file sections of ``text`` and the text without them.

    A section starts at a line outside a fence that ``parse_header`` accepts and
    runs until the next such header, the next fence line or the end of the text.
    Lines inside fenced blocks (embed references included) are never touched.
    Sections without content are kept as text. Each file is
    ``{"language", "filename", "content"}``; the first section of a path wins.
    """
    files: List[Dict[str, str]] = []
    seen: set[str] = set()
    kept: List[str] = []
    current: Optional[Dict[str, str]] = None
    current_lines: List[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal current, current_lines
        if current is not None:
            content = "\n".join(current_lines).strip("\n")
            if content.strip() and current["filename"] not in seen:
                seen.add(current["filename"])
                files.append({**current, "content": content})
            elif not content.strip():
                kept.append(current["header_line"])
                kept.extend(current_lines)
        current = None
        current_lines = []

    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            flush()
            in_fence = not in_fence
            kept.append(line)
            continue
        if not in_fence:
            header = parse_header(line)
            if header:
                flush()
                current = {"language": header["language"], "filename": header["filename"], "header_line": line}
                continue
        if current is not None:
            current_lines.append(line)
        else:
            kept.append(line)
    flush()

    for file in files:
        file.pop("header_line", None)
    if not files:
        return [], text
    remaining = "\n".join(kept)
    while "\n\n\n" in remaining:
        remaining = remaining.replace("\n\n\n", "\n\n")
    return files, remaining.strip()
