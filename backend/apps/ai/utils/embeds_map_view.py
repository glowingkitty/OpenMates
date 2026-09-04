"""Helpers for the virtual ``embeds_results_view`` assistant block.

The block is a message-level rendering instruction over existing embeds. These
helpers intentionally operate on text only; they never dispatch app skills,
providers, or enrichment calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable


ALLOWED_EMBEDS_MAP_VIEW_FIELDS = {"title", "embeds", "sources", "highlight"}
EMBEDS_RESULTS_VIEW_FENCE_LANGUAGE = "embeds_results_view"
LEGACY_EMBEDS_MAP_VIEW_FENCE_LANGUAGE = "embeds_map_view"
EMBEDS_MAP_VIEW_FENCE_LANGUAGE = EMBEDS_RESULTS_VIEW_FENCE_LANGUAGE
EMBEDS_RESULTS_VIEW_FENCE_LANGUAGES = {
    EMBEDS_RESULTS_VIEW_FENCE_LANGUAGE,
    LEGACY_EMBEDS_MAP_VIEW_FENCE_LANGUAGE,
}
MAP_VIEW_CAPABLE_SKILLS = {
    ("events", "search"),
    ("fitness", "search_classes"),
    ("fitness", "search_locations"),
    ("health", "search_appointments"),
    ("home", "search"),
    ("maps", "search"),
    ("travel", "search_connections"),
    ("travel", "search_stays"),
}
MAP_VIEW_CAPABLE_PRESELECTED_SKILL_IDS = {
    f"{app_id}-{skill_id}" for app_id, skill_id in MAP_VIEW_CAPABLE_SKILLS
}
_MAP_VIEW_REQUEST_RE = re.compile(r"\b(map|map/list|mapped|route|routes|locations?|nearby)\b", re.IGNORECASE)
_INLINE_EMBED_REF_RE = re.compile(r"\]\(embed:([^\s)]+)\)")
_MAP_VIEW_SUPPRESS_RE = re.compile(
    r"\b(?:no|without|skip|hide|exclude|don't|dont|do not)\s+(?:a\s+)?(?:map|calendar|map/list|mapped\s+view|results\s+view)\b"
    r"|\b(?:text|list)\s+only\b"
    r"|\bcompact\s+answer\s+only\b",
    re.IGNORECASE,
)

EMBEDS_MAP_VIEW_INSTRUCTION = """**Embeds Results View**

When location-capable, route-capable, or schedule-capable embed refs are
available, include exactly one compact results-view block by default unless the
view would clearly not make sense for the user's request or the user explicitly
asks for text/list-only output. Use direct child refs when those are the only
refs available:

```embeds_results_view
title: Berlin AI events
embeds: ai-founders-meetup-7f3a91, llm-hack-night-22b8c0
```

For full app-skill source results, prefer referencing the parent source and
optionally highlight selected child refs:

```embeds_results_view
title: Berlin AI events
sources: events-search-12ab34
highlight: ai-founders-meetup-7f3a91, llm-hack-night-22b8c0
```

Rules:
- Only include these fields: title, embeds, sources, highlight.
- Do not include filters, provider, enrichment, route geometry, prices, or JSON in the block.
- Do not call or imply automatic paid enrichment such as travel.flight_details, booking details, Flightradar24, or FlightAware.
- Only use embed_ref values that already appear in the conversation context.
- Prefer adding this block for map-capable or schedule-capable app-skill results even when the user did not explicitly ask for a map or calendar.
- Omit it only when the request explicitly asks for no map/calendar, text-only/list-only output, or the result has no usable spatial or schedule data.
"""

_MAP_VIEW_FENCE_RE = re.compile(
    r"```(?P<language>embeds_results_view|embeds_map_view)\s*\n(?P<body>.*?)\n?```",
    re.DOTALL,
)
_JSON_FENCE_RE = re.compile(
    r"```json\s*\n(?P<body>.*?)\n?```",
    re.DOTALL | re.IGNORECASE,
)


def _normalize_refs(value: str) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for raw_ref in value.split(","):
        ref = raw_ref.strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _dedupe_refs(refs: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw_ref in refs:
        ref = raw_ref.strip() if isinstance(raw_ref, str) else ""
        if not ref or ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped


def is_embeds_map_view_fence_language(language: str | None) -> bool:
    """Return whether a markdown fence language targets the map-view renderer."""

    if not isinstance(language, str):
        return False
    stripped_language = language.strip()
    if not stripped_language:
        return False
    fence_language = stripped_language.split(maxsplit=1)[0].lower()
    return fence_language in EMBEDS_RESULTS_VIEW_FENCE_LANGUAGES


def should_include_embeds_map_view_hint(app_id: str, skill_id: str, user_texts: Iterable[str]) -> bool:
    """Return whether a tool result should remind the model to emit a results view."""

    if (app_id, skill_id) not in MAP_VIEW_CAPABLE_SKILLS:
        return False
    return not is_map_view_suppressed_request(user_texts)


def content_has_map_view_capable_skill_marker(content: str) -> bool:
    """Return whether prior content appears to contain visual-capable embed results."""

    if not isinstance(content, str) or not content:
        return False
    if content_has_map_capable_app_skill_use(content):
        return True
    compact = "".join(content.split())
    for app_id, skill_id in MAP_VIEW_CAPABLE_SKILLS:
        if f"app_id: {app_id}" in content and f"skill_id: {skill_id}" in content:
            return True
        if f'"app_id":"{app_id}"' in compact and f'"skill_id":"{skill_id}"' in compact:
            return True
    return False


def should_include_embeds_results_view_instruction(
    preselected_skill_ids: Iterable[str] | None,
    user_texts: Iterable[str],
    history_texts: Iterable[str],
) -> bool:
    """Return whether the model should see map/calendar results-view syntax."""

    if is_map_view_suppressed_request(user_texts):
        return False
    if set(preselected_skill_ids or []) & MAP_VIEW_CAPABLE_PRESELECTED_SKILL_IDS:
        return True
    return any(content_has_map_view_capable_skill_marker(text) for text in history_texts)


def is_map_view_request(user_texts: Iterable[str]) -> bool:
    """Return whether user text explicitly asks for mapped or route output."""

    return any(_MAP_VIEW_REQUEST_RE.search(text) for text in user_texts if isinstance(text, str))


def is_map_view_suppressed_request(user_texts: Iterable[str]) -> bool:
    """Return whether user text explicitly opts out of a map/calendar results view."""

    return any(_MAP_VIEW_SUPPRESS_RE.search(text) for text in user_texts if isinstance(text, str))


def extract_map_capable_source_refs(content: str) -> list[str]:
    """Return ordered source embed IDs for map-capable app-skill fences."""

    if not content or "app_skill_use" not in content:
        return []
    seen: set[str] = set()
    refs: list[str] = []
    for match in _JSON_FENCE_RE.finditer(content):
        try:
            payload = json.loads(match.group("body").strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("type") != "app_skill_use":
            continue
        app_id = payload.get("app_id")
        skill_id = payload.get("skill_id")
        embed_id = payload.get("embed_id")
        if not (
            isinstance(app_id, str)
            and isinstance(skill_id, str)
            and isinstance(embed_id, str)
            and (app_id, skill_id) in MAP_VIEW_CAPABLE_SKILLS
        ):
            continue
        ref = embed_id.strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def content_has_map_capable_app_skill_use(content: str) -> bool:
    """Return whether assistant text contains a map-capable app-skill embed."""

    if not content or "app_skill_use" not in content:
        return False
    for match in _JSON_FENCE_RE.finditer(content):
        try:
            payload = json.loads(match.group("body").strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("type") != "app_skill_use":
            continue
        app_id = payload.get("app_id")
        skill_id = payload.get("skill_id")
        if isinstance(app_id, str) and isinstance(skill_id, str) and (app_id, skill_id) in MAP_VIEW_CAPABLE_SKILLS:
            return True
    return False


def extract_inline_embed_refs(content: str) -> list[str]:
    """Return ordered unique embed refs already present in Markdown links."""

    seen: set[str] = set()
    refs: list[str] = []
    for match in _INLINE_EMBED_REF_RE.finditer(content or ""):
        ref = match.group(1).strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def append_missing_embeds_map_view_block(
    content: str,
    *,
    title: str = "Mapped results",
    source_refs: Iterable[str] | None = None,
) -> tuple[str, bool]:
    """Append a minimal map-view block from existing source or inline refs."""

    if not content or any(f"```{language}" in content for language in EMBEDS_RESULTS_VIEW_FENCE_LANGUAGES):
        return content, False
    known_source_refs = _dedupe_refs(
        [*extract_map_capable_source_refs(content), *(source_refs or [])]
    )
    inline_refs = extract_inline_embed_refs(content)
    if not known_source_refs and not inline_refs:
        return content, False

    block_lines = [
        f"```{EMBEDS_RESULTS_VIEW_FENCE_LANGUAGE}",
        f"title: {title}",
    ]
    if known_source_refs:
        block_lines.append(f"sources: {_join_refs(known_source_refs)}")
        highlighted_refs = [ref for ref in inline_refs if ref not in known_source_refs]
        if highlighted_refs:
            block_lines.append(f"highlight: {_join_refs(highlighted_refs)}")
    else:
        block_lines.append(f"embeds: {_join_refs(inline_refs)}")
    block_lines.append("```")
    block = "\n".join(block_lines)
    return f"{content.rstrip()}\n\n{block}", True


def _join_refs(refs: Iterable[str]) -> str:
    return ", ".join(refs)


def _plain_text_fallback_from_json(body: str) -> str:
    try:
        parsed = json.loads(body.strip())
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    title = parsed.get("title")
    return str(title).strip() if isinstance(title, str) else ""


def _normalize_single_map_view_block(
    match: re.Match[str],
    source_parent_refs: set[str],
) -> tuple[str, bool]:
    body = match.group("body")
    json_fallback = _plain_text_fallback_from_json(body)
    if json_fallback:
        return json_fallback, True

    fields: dict[str, str] = {}
    changed = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            changed = True
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        if normalized_key not in ALLOWED_EMBEDS_MAP_VIEW_FIELDS:
            changed = True
            continue
        value = value.strip()
        if value:
            fields[normalized_key] = value

    embed_refs = _normalize_refs(fields.get("embeds", ""))
    source_refs = _normalize_refs(fields.get("sources", ""))
    highlight_refs = _normalize_refs(fields.get("highlight", ""))
    promoted_source_refs = [ref for ref in embed_refs if ref in source_parent_refs]
    if promoted_source_refs:
        child_refs = [ref for ref in embed_refs if ref not in source_parent_refs]
        source_refs = _dedupe_refs([*source_refs, *promoted_source_refs])
        highlight_refs = _dedupe_refs([*highlight_refs, *child_refs])
        embed_refs = []
        changed = True

    if not embed_refs and not source_refs:
        return fields.get("title", "").strip(), True

    title = fields.get('title', 'Results view').strip() or 'Results view'
    lines = [f"```{EMBEDS_RESULTS_VIEW_FENCE_LANGUAGE}", f"title: {title}"]
    if embed_refs:
        lines.append(f"embeds: {_join_refs(embed_refs)}")
    if source_refs:
        lines.append(f"sources: {_join_refs(source_refs)}")
    if highlight_refs:
        lines.append(f"highlight: {_join_refs(highlight_refs)}")
    lines.append("```")
    normalized = "\n".join(lines)
    return normalized, changed or normalized != match.group(0)


def normalize_embeds_map_view_blocks(
    content: str,
    *,
    source_refs: Iterable[str] | None = None,
) -> tuple[str, bool]:
    """Normalize all results-view fences in assistant-visible text.

    Returns the normalized content and whether any block changed. Unsupported
    fields are dropped, duplicate refs are removed, and JSON-like attempts are
    downgraded to plain text so the frontend never receives provider/enrichment
    instructions through this block.
    """

    changed = False
    source_parent_refs = set(extract_map_capable_source_refs(content))
    if source_refs:
        source_parent_refs.update(_dedupe_refs(source_refs))

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        replacement, block_changed = _normalize_single_map_view_block(match, source_parent_refs)
        changed = changed or block_changed
        return replacement

    normalized = _MAP_VIEW_FENCE_RE.sub(replace, content)
    return normalized, changed
