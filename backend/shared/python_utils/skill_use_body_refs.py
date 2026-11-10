"""The one rule for skill-use embeds in an assistant answer body.

An app skill call is shown once, in the "Used the X app" container at the spot
where the skill ran. Its skill-use embed (``app_skill_use``, including the
generated-media parent ``generated-media-<app>-<id12>``) must never appear in
the answer body, neither as a card (``[!](embed:ref)``, ``[](embed:ref)``) nor
as an inline link (``[text](embed:ref)``). Only result embeds (children such as
``generated-<app>-<id12>`` or search results) may be referenced there.

``remove_skill_use_body_refs`` enforces this on the final answer. A removed
reference whose results are not referenced anywhere else in the answer is
replaced by large cards for those results, so the output stays visible. The
container JSON blocks (fenced ``app_skill_use`` references) are not body
references and are left untouched.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

# Ref form written by generated_media_graph.generated_media_parent_ref.
GENERATED_MEDIA_PARENT_REF = re.compile(r"generated-media-[a-z0-9_]+-[A-Za-z0-9]{12}")

_BODY_EMBED_LINK = re.compile(r"\[([^\]\n]*)\]\(\s*<?embed:([^\s<>)]+)>?\s*\)")
_INLINE_CODE = re.compile(r"(?<!`)`[^`\n]+`(?!`)")
_FENCE_LINE = re.compile(r"^\s*(```|~~~)")


def _base_ref(target: str) -> str:
    """Drop a code-line anchor such as ``#L10-L20``."""
    return target.split("#", 1)[0]


def is_skill_use_ref(ref: Any, skill_use_refs: Mapping[str, Any] | None = None) -> bool:
    """True when ``ref`` names a skill-use embed rather than a result."""
    if not isinstance(ref, str) or not ref:
        return False
    base = _base_ref(ref)
    return bool(GENERATED_MEDIA_PARENT_REF.fullmatch(base)) or base in (skill_use_refs or {})


def is_skill_use_content(decoded: Mapping[str, Any]) -> bool:
    """Classify a decoded embed: a skill-use manifest lists the skill's results.

    Parent manifests (``app_skill_use``) name their app and skill and carry the
    result list (``result_count`` / ``embed_ids``). Result embeds carry their
    own type (``generated_image``, ``website``, a code embed ...) and no result
    list, even when they record which skill produced them.
    """
    if decoded.get("type") == "app_skill_use":
        return True
    return (decoded.get("type") is None
            and isinstance(decoded.get("app_id"), str)
            and isinstance(decoded.get("skill_id"), str)
            and ("result_count" in decoded or isinstance(decoded.get("embed_ids"), (list, str))))


def remove_skill_use_body_refs(
    answer: str, skill_use_children: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, int]:
    """Remove every body reference to a skill-use embed; return text and count.

    ``skill_use_children`` maps known skill-use refs to their result refs, in
    order. Generated-media parent refs are recognised by their form even
    without an entry. Card forms are removed; an inline link keeps its text as
    plain prose. Fenced code and inline code are never rewritten.
    """
    if not answer or "embed:" not in answer:
        return answer, 0
    children: dict[str, list[str]] = {}
    for ref, kids in (skill_use_children or {}).items():
        if isinstance(ref, str) and ref:
            children[ref] = [kid for kid in kids if isinstance(kid, str) and kid
                             and not is_skill_use_ref(kid, skill_use_children)]

    # Results already referenced anywhere in the answer need no substitute card.
    referenced = {
        _base_ref(match.group(2)) for match in _BODY_EMBED_LINK.finditer(answer)
        if not is_skill_use_ref(match.group(2), children)
    }
    removed = 0
    out: list[str] = []
    fence: str | None = None
    for line in answer.splitlines(keepends=True):
        fence_match = _FENCE_LINE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            fence = None if fence == marker else marker if fence is None else fence
            out.append(line)
            continue
        if fence:
            out.append(line)
            continue
        code_spans = [match.span() for match in _INLINE_CODE.finditer(line)]
        substitutes: list[str] = []

        def rewrite(match: re.Match[str]) -> str:
            nonlocal removed
            if any(start <= match.start() < end for start, end in code_spans):
                return match.group(0)
            ref = _base_ref(match.group(2))
            if not is_skill_use_ref(ref, children):
                return match.group(0)
            removed += 1
            for kid in children.get(ref, []):
                if kid not in referenced:
                    referenced.add(kid)
                    substitutes.append(kid)
            label = match.group(1)
            return "" if label.strip() in {"", "!"} else label

        updated = _BODY_EMBED_LINK.sub(rewrite, line)
        if updated == line:
            out.append(line)
            continue
        body = updated.rstrip("\r\n")
        eol = updated[len(body):] or ""
        cards = "\n".join(f"[!](embed:{kid})" for kid in substitutes)
        if not body.strip():
            # The line held only skill-use cards: put their results in place.
            if cards:
                out.append(cards + (eol or ""))
            continue
        if cards:
            # Large cards stand on their own line after the prose.
            out.append(f"{body.rstrip()}\n\n{cards}{eol}")
        else:
            indent = body[:len(body) - len(body.lstrip())]
            out.append(indent + re.sub(r"[ \t]{2,}", " ", body.lstrip()).rstrip() + eol)
    if not removed:
        return answer, 0
    result = "".join(out)
    if not answer.endswith("\n"):
        # A dropped last line must not leave trailing blank lines behind.
        result = result.rstrip("\n")
    return result, removed
