"""Overlay installed app package providers onto raw built-in app.yml data.

Every metadata reader (skill registry build for the API and Celery workers,
the feature availability manifest reader and the filesystem workflow metadata
reader) calls ``apply_app_package_overlay`` on the raw app.yml dict before
parsing it. The overlay is computed from the server's installation registry
only; removing a package (or disabling app packages) and restarting yields the
unmodified metadata again.

Skills paused without any provider that receive a ``skill.requests@1`` provider
are also switched to a generic delegate class (``class_path``):
``InstalledProviderSkill`` for a ``requests`` array schema,
``InstalledProviderFlatSkill`` for a flat schema, keeping the original class path in ``delegated_class_path`` so
the delegate can reuse the skill's request and response models. Every execution
path resolves the class from this metadata, so no call site changes.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional

from backend.shared.app_packages.generic_contract import (
    PROVIDER_SELECTOR_FIELDS,
    SKILL_REQUESTS_V1,
    accepts_generic_contract,
    delegate_class_path,
    has_requests_array,
)
from backend.shared.app_packages.loader import InstalledProvider, get_installed_packages


def _extend_enum(schema: Any, values: List[str]) -> None:
    if isinstance(schema, dict) and isinstance(schema.get("enum"), list):
        schema["enum"].extend(value for value in values if value not in schema["enum"])


def extend_provider_enums(schema: Any, values: List[str]) -> None:
    """Add provider values to every ``provider`` / ``providers`` enum in a JSON schema."""
    if isinstance(schema, list):
        for item in schema:
            extend_provider_enums(item, values)
        return
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if isinstance(properties, dict):
        _extend_enum(properties.get("provider"), values)
        providers = properties.get("providers")
        if isinstance(providers, dict):
            _extend_enum(providers.get("items"), values)
    for value in schema.values():
        if isinstance(value, (dict, list)):
            extend_provider_enums(value, values)


def installed_provider_entry(provider: InstalledProvider) -> Dict[str, Any]:
    """Provider entry appended to the target skill's ``providers`` list."""
    return {
        "name": provider.provider_id,
        "id": provider.provider_id,
        "display_name": provider.name,
        # Providers without declared secrets need no key; declared secrets are
        # checked per call and by the availability helpers.
        "no_api_key": not provider.secrets,
        "installed": True,
    }


# Routing sentence for skills that also answer from public web pages (see web_source.py).
# It leads the hint: provider hints describe city-bound platforms, and the router
# otherwise sends region-wide or worldwide discovery questions to general web search.
WEB_SOURCE_HINTS: Dict[tuple, str] = {
    ("events", "search"): "Prefer this over web search for any question about upcoming events or conferences, "
                          "anywhere: in a city, a country, a region such as Europe, or worldwide. Results also "
                          "come from public web pages; without a city give only a topic query.",
    ("shopping", "search_products"): "Prefer this over web search for products to buy: results come from the "
                                     "listed shops and from public shop pages.",
}


def _add_web_source_hint(app_id: str, skill: Dict[str, Any]) -> None:
    extra = WEB_SOURCE_HINTS.get((app_id, str(skill.get("id"))))
    hint = skill.get("preprocessor_hint")
    if extra and isinstance(hint, str) and hint.strip():
        skill["preprocessor_hint"] = f"{extra} {hint.strip()}"


def _overlay_skill(skill: Dict[str, Any], providers: List[InstalledProvider]) -> None:
    skill["providers"] = list(skill.get("providers") or []) + [installed_provider_entry(p) for p in providers]
    skill.pop("default_enabled", None)
    hints = list(dict.fromkeys(p.skill_hint for p in providers if p.skill_hint))
    if hints:
        skill["preprocessor_hint"] = " ".join(hints)
    ids = [p.provider_id for p in providers]
    if isinstance(skill.get("tool_schema"), dict):
        extend_provider_enums(skill["tool_schema"], ids)
    workflow = skill.get("workflow")
    if isinstance(workflow, dict) and isinstance(workflow.get("output_schema"), dict):
        extend_provider_enums(workflow["output_schema"], ids + [p.name for p in providers])


PROVIDER_SELECTOR_DESCRIPTION = (
    "Optional provider ids to limit this request to. Omit to use every available provider."
)


def _selector_description(provider_ids: List[str], names: Optional[Mapping[str, str]]) -> str:
    """The filter description; ids whose display name differs are listed with it."""
    named = [f"{pid} ({names[pid]})" for pid in provider_ids
             if names and names.get(pid) and names[pid].strip().casefold() != pid]
    return f"{PROVIDER_SELECTOR_DESCRIPTION} Ids: {', '.join(named)}." if named else PROVIDER_SELECTOR_DESCRIPTION


def ensure_provider_selector(skill: Dict[str, Any], provider_ids: List[str],
                             names: Optional[Mapping[str, str]] = None) -> None:
    """Declare a ``providers`` filter in the public request schema when it has no selector.

    ``names`` maps ids to display names so a caller can tell which id is which provider.

    Callers reach the generic delegate through request models built from this
    schema, which drop undeclared fields; without a declared selector a named
    provider would be ignored and every installed provider would answer.
    """
    schema = skill.get("tool_schema")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return
    if has_requests_array(skill):
        items = properties["requests"].get("items")
        properties = items.setdefault("properties", {}) if isinstance(items, dict) else None
        if not isinstance(properties, dict):
            return
    if any(field in properties for field in PROVIDER_SELECTOR_FIELDS):
        return
    properties["providers"] = {
        "type": "array",
        "items": {"type": "string", "enum": list(provider_ids)},
        "description": _selector_description(list(provider_ids), names),
    }


def _overlay_delegated_skill(skill: Dict[str, Any], providers: List[InstalledProvider]) -> None:
    """Serve a paused, provider-less skill through the generic delegate class."""
    _overlay_skill(skill, providers)
    ensure_provider_selector(skill, list(dict.fromkeys(p.provider_id for p in providers)),
                             {p.provider_id: p.name for p in providers})
    if not any(p.skill_hint for p in providers):
        # The built-in hint of a paused skill describes it as unavailable.
        skill.pop("preprocessor_hint", None)
    skill["delegated_class_path"] = str(skill["class_path"]).strip()
    skill["class_path"] = delegate_class_path(skill)


def apply_app_package_overlay(app_id: str, raw_config: Any) -> Any:
    """Return ``raw_config`` with active installed providers merged in.

    The input is never mutated; when no contribution targets this app the same
    object is returned unchanged.
    """
    if not isinstance(raw_config, dict):
        return raw_config
    contributions = get_installed_packages().for_app(app_id)
    if not contributions:
        return raw_config
    overlaid = copy.deepcopy(raw_config)
    applied = False
    for skill in overlaid.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        if skill.get("provider_contract"):
            matching = [
                p for p in contributions
                if p.skill_id == str(skill.get("id")) and p.contract == skill["provider_contract"]
            ]
            if matching:
                _overlay_skill(skill, matching)
                if any(p.skill_hint for p in matching):
                    _add_web_source_hint(app_id, skill)
                applied = True
        elif accepts_generic_contract(skill):
            matching = [
                p for p in contributions
                if p.skill_id == str(skill.get("id")) and p.contract == SKILL_REQUESTS_V1
            ]
            if matching:
                _overlay_delegated_skill(skill, matching)
                _add_web_source_hint(app_id, skill)
                applied = True
    if applied:
        overlaid.pop("default_enabled", None)
        return overlaid
    return raw_config
