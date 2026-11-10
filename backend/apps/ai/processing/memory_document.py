# backend/apps/ai/processing/memory_document.py
#
# Canonical personal Memory documents built from model fields. Shared by the
# reviewed create-draft action and the main-processor save_memory tool so both
# produce and validate exactly the same document. Pure: no I/O, no logging.
# Spec: app-memories (document format, load modes)
# test-file: backend/tests/test_memory_write_tool.py

from __future__ import annotations

import re
from typing import Any, Dict, Optional

import yaml

from backend.apps.ai.processing.postprocessing_recommendations import clean_text, contains_secret
from backend.shared.python_utils.memory_loader import MAX_MEMORY_CHARS, parse_memory_md

MAX_TITLE_CHARS = 120
MAX_WHEN_TO_USE_CHARS = 400
MAX_BODY_CHARS = 8_000
LOAD_MODES = ("auto_include", "ask_first", "mention_only")

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+\-Zz]+)?$")


class MemoryDocumentError(ValueError):
    """A field set cannot become a canonical Memory. Messages never echo field text."""


def build_memory_document(title: str, when_to_use: str, content: str, valid_from: str = "",
                          valid_until: str = "", load_mode: str = "ask_first") -> str:
    """Canonical Markdown memory: YAML frontmatter (title, when_to_use, load_mode, dates) plus body."""
    header: Dict[str, Any] = {"title": title, "when_to_use": when_to_use, "load_mode": load_mode}
    if valid_from:
        header["valid_from"] = valid_from
    if valid_until:
        header["valid_until"] = valid_until
    front = yaml.safe_dump(header, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10_000).strip()
    return f"---\n{front}\n---\n\n{content.strip()}\n"


def validated_memory_document(arguments: Optional[Dict[str, Any]], *, load_mode: str = "ask_first") -> Dict[str, str]:
    """Validate fields into {title, when_to_use, body}; raises MemoryDocumentError, never repairs secrets."""
    if not isinstance(arguments, dict):
        raise MemoryDocumentError("no usable fields")
    if load_mode not in LOAD_MODES:
        raise MemoryDocumentError("unknown load mode")
    title = clean_text(arguments.get("title"), MAX_TITLE_CHARS)
    when_to_use = clean_text(arguments.get("when_to_use"), MAX_WHEN_TO_USE_CHARS)
    content = arguments.get("content")
    if not title or not when_to_use or not isinstance(content, str) or not content.strip():
        raise MemoryDocumentError("title, when_to_use and content are required")
    if len(content) > MAX_BODY_CHARS:
        raise MemoryDocumentError("content is too long")
    content = _CONTROL_CHARS.sub("", content)
    if any(contains_secret(value) for value in (title, when_to_use, content)):
        raise MemoryDocumentError("secret detected")
    dates: Dict[str, str] = {}
    for key in ("valid_from", "valid_until"):
        value = arguments.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str) or not _ISO_DATE.match(value.strip()):
            raise MemoryDocumentError("invalid date")
        dates[key] = value.strip()
    document = build_memory_document(title, when_to_use, content, load_mode=load_mode, **dates)
    if len(document) > MAX_MEMORY_CHARS:
        raise MemoryDocumentError("document is too long")
    try:
        parse_memory_md(document, memory_id="draft", source="personal")
    except ValueError as exc:
        raise MemoryDocumentError("non-canonical document") from exc
    return {"title": title, "when_to_use": when_to_use, "body": document}
