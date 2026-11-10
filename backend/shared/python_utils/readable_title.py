# backend/shared/python_utils/readable_title.py
#
# Turn a label that may be a filename or slug into a short readable title.

from __future__ import annotations

import re

MAX_TITLE_CHARS = 48
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_SLUG = re.compile(r"^[^\s\-_]+(?:[-_][^\s\-_]+)+$")


def readable_title(label: str, max_chars: int = MAX_TITLE_CHARS) -> str:
    """Return ``label`` as natural text of at most ``max_chars`` characters.

    Slugs and filenames (no spaces, words joined by ``-``/``_``, optional
    extension) lose the extension and separators and get a leading capital.
    Natural text is kept. Long text is cut at a word boundary, no ellipsis.
    """
    text = " ".join(str(label or "").split())
    stem = _EXTENSION.sub("", text)
    if stem and " " not in stem and _SLUG.match(stem):
        text = re.sub(r"[-_]+", " ", stem)
        text = text[:1].upper() + text[1:]
    elif " " not in text and _EXTENSION.search(text):
        text = stem
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if text[max_chars] != " ":
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut.rstrip(" ,.;:-_")
