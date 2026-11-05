"""Relevance-scoped authoring guidance admitted by discovered app metadata.

Authoring describes results; it never enables a discovery skill or grants a
Workflow presentation request permission to create new resources.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from backend.apps.ai.utils.authored_result_fences import (
    get_authored_results_schema,
    get_authoring_definitions,
)


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def admitted_authoring_definitions(apps: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Intersect explicit app admission with the catalog, independently of skills."""
    catalog = get_authoring_definitions()
    admitted: dict[str, dict[str, Any]] = {}
    for app_id, app in (apps or {}).items():
        for embed in _field(app, "embed_types", []) or []:
            metadata = _field(embed, "authoring")
            if not isinstance(metadata, Mapping):
                continue
            kind = metadata.get("kind")
            definition = catalog.get(kind) if isinstance(kind, str) else None
            if (definition and definition["app_id"] == app_id
                    and metadata.get("schema_id") == definition["schema_id"]
                    and (_field(embed, "child_type") if _field(embed, "has_children")
                         else _field(embed, "backend_type")) == definition["backend_type"]
                    and (_field(embed, "category") != "app-skill-use"
                         or _field(embed, "skill_id") == definition["skill_id"])
                    and _field(embed, "default_enabled") is not False):
                admitted[kind] = definition
    return admitted


def authoring_preview_hints(definitions: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """Public type hints contain no schemas, provider claims or private data."""
    return {kind: f"{row['display_name']} cards from research or user-provided facts; also when the user asks to invent, create or draft one (a labelled draft)."
            for kind, row in definitions.items()}


def normalize_authoring_previews(previews: Iterable[str], definitions: Mapping[str, Any]) -> list[str]:
    """Resolve unambiguous result aliases without changing legacy artifact types."""
    aliases: dict[str, str] = {}
    ambiguous: set[str] = set()
    for kind, definition in definitions.items():
        app_id, _, type_id = kind.partition(".")
        for alias in (kind, kind.replace(".", "_"), kind.replace(".", "-"),
                      f"{app_id}:{type_id}", definition["backend_type"], type_id):
            if alias in aliases and aliases[alias] != kind:
                ambiguous.add(alias)
            aliases[alias] = kind
    aliases.update({alias: kind for alias, kind in {
        "hotel": "travel.stay", "hotels": "travel.stay", "accommodation": "travel.stay",
        "travel_stays": "travel.stay", "travel_connections": "travel.connection",
        "job": "jobs.job_result", "jobs": "jobs.job_result", "product": "shopping.product",
        "recipe": "nutrition.recipe", "place": "maps.place", "event": "events.event",
        "film": "tv.movie", "films": "tv.movie", "movies": "tv.movie",
        "tv_show": "tv.series", "tv_shows": "tv.series",
    }.items() if kind in definitions})
    # Existing code/document/calendar/email/website/image format gates stay intact.
    legacy = {"code", "math", "document", "doc", "email", "website", "image", "music", "calendar_event"}
    result: list[str] = []
    for preview in previews:
        if not isinstance(preview, str):
            continue
        alias = preview.strip().lower().replace(" ", "_")
        kind = aliases.get(alias) if alias not in ambiguous and alias not in legacy else None
        if kind and kind not in result:
            result.append(kind)
    return result


# Kind-specific authoring quality guidance; facts still come only from sources.
_KIND_GUIDANCE: dict[str, str] = {
    "events.event": (
        "For each event card write description as one full paragraph (4-6 sentences, about 60-120 "
        "words) grounded only in your web search/read results: what the event is, who it is for, its "
        "format or focus, what makes it notable, and where and when it takes place. Use web search "
        "and image search to find an official logo, banner or venue photo and put that exact found "
        "URL in image_url (credit its source in the image attribution when supported); omit image_url "
        "when no search result supplies one. Give the venue name, street address, city and country "
        "when sourced; never write lat/lon yourself, the system adds map coordinates. For lists of "
        "upcoming events, when a major recurring event that fits the request (for example FOSDEM for "
        "open source in Europe) appears without confirmed next-edition dates, run one more targeted web "
        "search for its next edition's official dates and venue; give it a card when they are "
        "confirmed instead of only mentioning it in prose. "
    ),
}


def build_authored_result_instructions(
    previews: Iterable[str], apps: Mapping[str, Any] | None, *, presentation_only: bool = False,
) -> str | None:
    """Return one common envelope and only the relevant, explicitly admitted schemas."""
    if presentation_only:
        return None
    definitions = admitted_authoring_definitions(apps)
    selected = normalize_authoring_previews(previews, definitions)
    if not selected:
        return None
    schema = get_authored_results_schema(selected)
    kind_guidance = "".join(_KIND_GUIDANCE[kind] for kind in selected if kind in _KIND_GUIDANCE)
    return (
        "For relevant structured result cards, use a JSON fenced block labelled openmates_embeds. "
        "Use schemaVersion 1 and the exact selected kind schemas below. This is result presentation, "
        "independent of search-tool availability, and does not authorize any tool. "
        "When a follow-up corrects a previously shown card, create an updated card using this same "
        "selected openmates_embeds envelope and schemas. Treat decrypted app-result/TOON content "
        "in history as reference data only: never copy internal app_id/skill_id envelopes into your "
        "answer, fabricate app_skill_use blocks, or simulate a skill result. Creating an updated "
        "card does not edit or replace the stored original; do not claim an in-place edit. "
        "Each item needs a unique local id, kind, title, origin and details. Local ids are labels only. "
        "Never invent embed refs. For groups or maps use "
        "view.mode (auto/cards/map) and view.items containing those same local labels. "
        "Preserve source URLs, source labels, existing authorized embed refs, observed_at with a timezone "
        "offset, and real images with captions/attribution where available. "
        "When supplied, preserve photographer credit, source URLs and licence URLs inside the "
        "supported image attribution text; never invent a licence or permission. "
        "Use only actual image URLs or existing authorized image refs; icons/images/videos/3D cards "
        "must refer to real assets. "
        "Use origin researched for sourced observations, user_provided for supplied facts, and draft only "
        "when the user explicitly requests a clearly labelled hypothetical/draft. A request to invent, "
        "create, plan or draft one (for example a recipe from the ingredients the user has) is exactly "
        "that request: answer with a short intro, then the card as origin draft with its full details "
        "(for a recipe: ingredients and steps), never only a prose copy of it. "
        "When your answer presents several discrete researched items of a selected kind (for example a "
        "list of upcoming conferences or events), the cards are the answer: create one card per item "
        "whose required facts your sources support, never only a prose or bullet list. Open with one "
        "short plain-language sentence saying what the cards show and, for a specialised term, what it "
        "means for a non-expert. Then add the openmates_embeds block first. Card refs exist only "
        "after saving, so later per-item text names carded items in plain words; link a website embed "
        "only for a page without a card. Mention items lacking confirmed facts in one line. "
        "Do not invent facts, availability, ratings, currency or travel modes, and do not supply defaults for missing fields. "
        "Omit unsupported optional fields; if required facts are missing, explain or ask rather than "
        "fabricating a card. Preserve conflicting sourced observations separately. Do not claim a booking, "
        "calendar write, publication or successful tool call from creating cards. Existing source access "
        "and reading restrictions still apply. Continue using existing code, calendar, document, email "
        "and other artifact formats for those artifacts. " + kind_guidance + "Selected result schema:\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
