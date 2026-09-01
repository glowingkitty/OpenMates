#!/usr/bin/env python3
"""Render a readable Specification presentation PDF.

Specifications are stored as deterministic YAML, but the default human surface is a
chaptered Project document: outcome, scope, capability chapters, Requirements,
flows, contextual models, Checks, and generated indexes. This renderer turns one
validated bundle into that presentation without using it as an approval receipt.
Approval still uses scripts/specification_approval_pdf.py and scripts/specifications.py.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import html
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import specifications  # noqa: E402
from scripts import opencode_response_media  # noqa: E402
from scripts.playwright_visual_smoke import launch_browser  # noqa: E402


DEFAULT_OUTPUT_ROOT = Path("/tmp/opencode/specification-presentations")
IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
NUMBERED_LINE_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
IDENTITY_FIELDS = ("id", "name", "key")
SKIPPED_EXAMPLE_FIELDS = {"schema_version", "specification"}
ICON_PATHS = {
    "outcome": "M4 12h16M12 4v16M7 7l10 10M17 7 7 17",
    "legend": "M5 5h14v14H5zM8 9h8M8 13h5",
    "navigation": "M4 6h16M4 12h16M4 18h16",
    "scope": "M12 3 4 7v10l8 4 8-4V7zM12 3v18",
    "surface": "M4 5h16v11H4zM8 20h8M12 16v4",
    "chapter": "M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM8 4v16",
    "requirement": "M6 3h9l3 3v15H6zM9 11h6M9 15h6M15 3v4h4",
    "user_flow": "M5 5h6v5H5zM13 14h6v5h-6zM11 8h4v6",
    "edge_case": "M12 3 2 21h20zM12 9v5M12 18v.01",
    "model": "M4 6 12 3l8 3-8 3zM4 6v6l8 3 8-3V6M4 12v6l8 3 8-3v-6",
    "check": "M4 12 9 17 20 6",
    "examples": "M5 4h14v16H5zM8 8h8M8 12h8M8 16h5",
    "history": "M12 7v5l4 2M21 12a9 9 0 1 1-3-6.7",
    "indexes": "M6 4h12v16H6zM9 8h6M9 12h6M9 16h6",
}


class ReadableSpecificationError(ValueError):
    """Raised when a bundle lacks the presentation fields needed here."""


def _default_surface_catalog(contract: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Build presentation-only surface metadata from the canonical surface matrix."""
    matrix = contract.get("surfaces") if isinstance(contract.get("surfaces"), dict) else {}
    sdks = matrix.get("sdks") if isinstance(matrix.get("sdks"), dict) else {}
    sdk_implementations = sdks.get("implementations") if isinstance(sdks.get("implementations"), dict) else {}
    gui = matrix.get("gui") if isinstance(matrix.get("gui"), dict) else {}
    gui_implementations = gui.get("implementations") if isinstance(gui.get("implementations"), dict) else {}
    definitions = (
        ("rest_api", "REST API", "api", matrix.get("rest_api")),
        ("cli", "CLI", "cli", matrix.get("cli")),
        ("npm", "npm SDK", "sdk", sdk_implementations.get("npm")),
        ("pip", "pip SDK", "sdk", sdk_implementations.get("pip")),
        ("web", "Web", "web", gui_implementations.get("web")),
        ("apple", "Apple", "native", gui_implementations.get("apple")),
    )
    surfaces = []
    required_ids = []
    for surface_id, label, kind, config in definitions:
        if not isinstance(config, dict) or config.get("required") is not True:
            continue
        surfaces.append({"id": surface_id, "label": label, "kind": kind, "status": "active"})
        required_ids.append(surface_id)
    return {
        "home_project_id": "openmates",
        "revision_id": "derived-for-pdf",
        "surfaces": surfaces,
    }, required_ids


def with_default_presentation(bundle: specifications.SpecificationBundle) -> specifications.SpecificationBundle:
    """Add a modern presentation view without changing fingerprinted source data."""
    if isinstance(bundle.specification.get("presentation"), dict):
        return bundle

    contract = copy.deepcopy(bundle.specification)
    catalog, required_surface_ids = _default_surface_catalog(contract)
    assertions = contract.get("assertions") if isinstance(contract.get("assertions"), list) else []
    flows = contract.get("flows") if isinstance(contract.get("flows"), list) else []
    models = contract.get("models") if isinstance(contract.get("models"), dict) else {}
    checks = contract.get("check_obligations") if isinstance(contract.get("check_obligations"), list) else []

    for assertion in assertions:
        if isinstance(assertion, dict) and not isinstance(assertion.get("project_surface_ids"), list):
            assertion["project_surface_ids"] = required_surface_ids
    for flow in flows:
        if isinstance(flow, dict) and not isinstance(flow.get("surface_ids"), list):
            flow["surface_ids"] = required_surface_ids

    chapter_id = "overview"
    contract.update({
        "outcome": contract.get("outcome") or contract.get("summary") or "",
        "presentation": {
            "document_kind": "capability_specification",
            "chapter_order": [chapter_id],
            "generated_indexes": ["requirements", "user_flows", "edge_cases", "models", "checks", "examples", "history"],
            "legend": {
                "requirement": "Durable behavior the implementation must preserve.",
                "user_flow": "Goal-oriented path through the capability.",
                "edge_case": "Boundary or recovery behavior.",
                "model": "Canonical data shape.",
                "check": "Verification obligation.",
                "surface": "Client or API surface covered by this Specification.",
            },
        },
        "project_surface_catalog": catalog,
        "scope": contract.get("scope") if isinstance(contract.get("scope"), dict) else {"includes": [], "excludes": []},
        "chapters": [{
            "id": chapter_id,
            "title": "Requirements Overview",
            "summary": str(contract.get("summary") or "Review the Specification requirements and supporting material."),
            "requirement_ids": [str(item["id"]) for item in assertions if isinstance(item, dict) and item.get("id")],
            "user_flow_ids": [str(item["id"]) for item in flows if isinstance(item, dict) and item.get("id") and item.get("kind") != "edge_case"],
            "edge_case_ids": [str(item["id"]) for item in flows if isinstance(item, dict) and item.get("id") and item.get("kind") == "edge_case"],
            "model_ids": [str(model_id) for model_id in models],
        }],
        "assertions": assertions,
        "flows": flows,
        "models": models,
        "check_obligations": checks,
        "model_placements": contract.get("model_placements") if isinstance(contract.get("model_placements"), list) else [],
    })
    scope = contract["scope"]
    scope["includes"] = scope.get("includes") if isinstance(scope.get("includes"), list) else []
    scope["excludes"] = scope.get("excludes") if isinstance(scope.get("excludes"), list) else []
    return replace(bundle, specification=contract)


def _display_text(value: object) -> str:
    return str(value).translate(str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-"}))


def _escape(value: object) -> str:
    return html.escape(_display_text(value))


def _label(value: object) -> str:
    text = _display_text(value).replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else "Untitled"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "specification"


def _anchor(prefix: str, value: object) -> str:
    key = IDENTIFIER_RE.sub("-", _display_text(value)).strip("-_.:").lower()
    return f"{prefix}-{key or 'item'}"


def _icon(name: str, *, css_class: str = "icon") -> str:
    path = ICON_PATHS.get(name, ICON_PATHS["chapter"])
    return (
        f'<svg class="{css_class}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        f'<path d="{path}"/></svg>'
    )


def _heading(level: int, icon: str, title: str, *, anchor: str = "") -> str:
    anchor_attribute = f' id="{anchor}"' if anchor else ""
    return f'<h{level}{anchor_attribute} class="section-heading">{_icon(icon)}<span>{_escape(title)}</span></h{level}>'


def _as_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReadableSpecificationError(f"{field} must be a mapping")
    return value


def _as_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReadableSpecificationError(f"{field} must be a list")
    return value


def _string_ids(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _by_id(items: Any, field: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(_as_list(items, field), start=1):
        item = _as_mapping(item, f"{field}[{index}]")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ReadableSpecificationError(f"{field}[{index}].id must be a non-empty string")
        result[item_id] = item
    return result


def _identity(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        for field in IDENTITY_FIELDS:
            item = value.get(field)
            if isinstance(item, (str, int, float)):
                return str(item)
    return fallback


def _inline_json(value: Any) -> str:
    if value in (None, {}, []):
        return ""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(", ", ": "))


def _render_chips(values: list[str], *, css_class: str = "chip") -> str:
    if not values:
        return '<span class="muted">None</span>'
    return "".join(f'<span class="{css_class}">{_escape(value)}</span>' for value in values)


def _surface_lookup(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog = _as_mapping(contract.get("project_surface_catalog"), "project_surface_catalog")
    surfaces = _as_list(catalog.get("surfaces"), "project_surface_catalog.surfaces")
    lookup: dict[str, dict[str, Any]] = {}
    for index, surface in enumerate(surfaces, start=1):
        surface = _as_mapping(surface, f"project_surface_catalog.surfaces[{index}]")
        surface_id = surface.get("id")
        if not isinstance(surface_id, str) or not surface_id:
            raise ReadableSpecificationError(f"project_surface_catalog.surfaces[{index}].id must be a non-empty string")
        lookup[surface_id] = surface
    return lookup


def _render_surfaces(surface_ids: list[str], lookup: dict[str, dict[str, Any]]) -> str:
    if not surface_ids:
        return '<span class="muted">No surface declared</span>'
    chips = []
    for surface_id in surface_ids:
        surface = lookup.get(surface_id, {})
        label = str(surface.get("label") or surface_id)
        status = str(surface.get("status") or "active")
        status_class = " deferred" if status == "deferred" else ""
        suffix = f" ({status})" if status != "active" else ""
        chips.append(f'<span class="chip surface{status_class}">{_escape(label)}{_escape(suffix)}</span>')
    return "".join(chips)


def _render_content_block(content: Any) -> str:
    text = _display_text(content or "").strip()
    if not text:
        return '<p class="muted">No narrative content.</p>'
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    numbered = [NUMBERED_LINE_RE.match(line) for line in lines]
    if lines and all(numbered):
        items = "".join(f"<li>{_escape(match.group(1))}</li>" for match in numbered if match is not None)
        return f"<ol>{items}</ol>"
    paragraphs = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line:
            current.append(line)
            continue
        if current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "".join(f"<p>{_escape(paragraph)}</p>" for paragraph in paragraphs)


def _render_wireframe(flow: dict[str, Any]) -> str:
    kind = str(flow.get("kind") or "user_flow")
    title = str(flow.get("title") or flow.get("id") or "Flow")
    state_label = "Boundary state" if kind == "edge_case" else "Primary flow"
    return f"""
<figure class="flow-wireframe" role="img" aria-label="Wireframe for {_escape(title)}">
  <div class="wireframe-window">
    <div class="wireframe-topbar"><span></span><span></span><span></span><strong>{_escape(state_label)}</strong></div>
    <div class="wireframe-body">
      <div class="wireframe-sidebar"><i></i><i></i><i></i><i></i></div>
      <div class="wireframe-canvas">
        <div class="wireframe-title">{_escape(title)}</div>
        <div class="wireframe-line wide"></div><div class="wireframe-line"></div>
        <div class="wireframe-panel"><b></b><span></span><span></span></div>
        <div class="wireframe-actions"><i></i><i></i></div>
      </div>
    </div>
  </div>
  <figcaption>{_icon('edge_case' if kind == 'edge_case' else 'user_flow', css_class='card-icon')}{_escape(_label(kind))} wireframe</figcaption>
</figure>"""


def _meta_row(label: str, value_html: str) -> str:
    return f'<div class="meta-row"><div class="meta-label">{_escape(label)}</div><div>{value_html}</div></div>'


def _render_requirement(assertion: dict[str, Any], surface_lookup: dict[str, dict[str, Any]]) -> str:
    assertion_id = str(assertion["id"])
    title = str(assertion.get("title") or assertion_id)
    surfaces = _string_ids(assertion.get("project_surface_ids"))
    checks = _string_ids(assertion.get("check_obligation_ids"))
    return f"""
<section class="card requirement" id="{_anchor('requirement', assertion_id)}">
  <div class="card-kind">{_icon('requirement', css_class='card-icon')}Requirement</div>
  <h4>{_escape(title)}</h4>
  <div class="item-id"><code>{_escape(assertion_id)}</code></div>
  <div class="card-meta">
    {_meta_row('Type', _escape(assertion.get('type', '')))}
    {_meta_row('Importance', _escape(assertion.get('importance', 'required')))}
    {_meta_row('Surfaces', _render_surfaces(surfaces, surface_lookup))}
    {_meta_row('Checks', _render_chips(checks, css_class='chip check-chip'))}
  </div>
  <p>{_escape(assertion.get('must', ''))}</p>
</section>"""


def _render_flow(flow: dict[str, Any], surface_lookup: dict[str, dict[str, Any]]) -> str:
    flow_id = str(flow["id"])
    kind = str(flow.get("kind") or "user_flow")
    parent = flow.get("parent_flow_id")
    parent_row = _meta_row("Parent flow", f'<code>{_escape(parent)}</code>') if isinstance(parent, str) and parent else ""
    return f"""
<section class="card flow" id="{_anchor('flow', flow_id)}">
  <div class="card-kind">{_icon('edge_case' if kind == 'edge_case' else 'user_flow', css_class='card-icon')}{_escape(_label(kind))}</div>
  <div class="flow-layout">
    {_render_wireframe(flow)}
    <div class="flow-copy">
      <h4>{_escape(flow.get('title') or flow_id)}</h4>
      <div class="item-id"><code>{_escape(flow_id)}</code></div>
      <div class="card-meta">
        {parent_row}
        {_meta_row('Requirements', _render_chips(_string_ids(flow.get('requirement_ids')), css_class='chip requirement-chip'))}
        {_meta_row('Surfaces', _render_surfaces(_string_ids(flow.get('surface_ids')), surface_lookup))}
        {_meta_row('Checks', _render_chips(_string_ids(flow.get('check_obligation_ids')), css_class='chip check-chip'))}
      </div>
      <div class="flow-narrative">{_render_content_block(flow.get('content'))}</div>
    </div>
  </div>
</section>"""


def _render_model(model_id: str, model: dict[str, Any]) -> str:
    rows = []
    for field_name, definition in model.items():
        if not isinstance(definition, dict):
            continue
        constraints = _inline_json(definition.get("constraints"))
        required = "Yes" if definition.get("required") is True else "No"
        rows.append(
            "<tr>"
            f"<td><code>{_escape(field_name)}</code></td>"
            f"<td><code>{_escape(definition.get('type', ''))}</code></td>"
            f"<td>{required}</td>"
            f"<td>{_escape(constraints) if constraints else '<span class=\"muted\">None</span>'}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="4" class="muted">No fields declared.</td></tr>'
    return f"""
<section class="card model" id="{_anchor('model', model_id)}">
  <div class="card-kind">{_icon('model', css_class='card-icon')}Model</div>
  <h4>{_escape(model_id)}</h4>
  <table><thead><tr><th>Field</th><th>Type</th><th>Required</th><th>Constraints</th></tr></thead><tbody>{body}</tbody></table>
</section>"""


def _render_check(check: dict[str, Any]) -> str:
    check_id = str(check["id"])
    source_rows = []
    for source in check.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_rows.append(
            "<tr>"
            f"<td>{_escape(source.get('kind', ''))}</td>"
            f"<td>{_escape(source.get('role', ''))}</td>"
            f"<td>{_escape(source.get('surface', ''))}</td>"
            f"<td><code>{_escape(source.get('path', ''))}</code></td>"
            "</tr>"
        )
    sources = "".join(source_rows) or '<tr><td colspan="4" class="muted">No source declared.</td></tr>'
    covers = _render_chips(_string_ids(check.get("covers")))
    return f"""
<section class="card check" id="{_anchor('check', check_id)}">
  <div class="card-kind">{_icon('check', css_class='card-icon')}Check</div>
  <h4>{_escape(check.get('title') or check_id)}</h4>
  <div class="item-id"><code>{_escape(check_id)}</code></div>
  <div class="card-meta">
    {_meta_row('Materialization', _escape(check.get('materialization', 'unknown')))}
    {_meta_row('Covers', covers)}
  </div>
  <table><thead><tr><th>Kind</th><th>Role</th><th>Surface</th><th>Source</th></tr></thead><tbody>{sources}</tbody></table>
</section>"""


def _ordered_chapters(contract: dict[str, Any]) -> list[dict[str, Any]]:
    presentation = _as_mapping(contract.get("presentation"), "presentation")
    order = _string_ids(presentation.get("chapter_order"))
    chapters = list(_by_id(contract.get("chapters"), "chapters").values())
    by_id = {str(chapter["id"]): chapter for chapter in chapters}
    ordered = [by_id[chapter_id] for chapter_id in order if chapter_id in by_id]
    ordered.extend(chapter for chapter in chapters if str(chapter["id"]) not in order)
    if not ordered:
        raise ReadableSpecificationError("chapters must contain at least one chapter")
    return ordered


def _chapter_items(chapter: dict[str, Any], contract: dict[str, Any]) -> dict[str, list[str]]:
    assertions = [item for item in _as_list(contract.get("assertions"), "assertions") if isinstance(item, dict)]
    flows = [item for item in _as_list(contract.get("flows"), "flows") if isinstance(item, dict)]
    requirement_ids = _string_ids(chapter.get("requirement_ids")) or [str(item.get("id")) for item in assertions if item.get("chapter_id") == chapter.get("id")]
    chapter_flow_ids = set(_string_ids(chapter.get("user_flow_ids")) + _string_ids(chapter.get("edge_case_ids")))
    if not chapter_flow_ids:
        chapter_flow_ids = {str(item.get("id")) for item in flows if item.get("chapter_id") == chapter.get("id")}
    model_ids = _string_ids(chapter.get("model_ids"))
    if not model_ids:
        model_ids = [str(item.get("model_id")) for item in contract.get("model_placements") or [] if isinstance(item, dict) and chapter.get("id") in _string_ids(item.get("chapter_ids"))]
    check_ids: list[str] = []
    for assertion in assertions:
        if assertion.get("id") in requirement_ids:
            check_ids.extend(_string_ids(assertion.get("check_obligation_ids")))
    for flow in flows:
        if flow.get("id") in chapter_flow_ids:
            check_ids.extend(_string_ids(flow.get("check_obligation_ids")))
    return {
        "requirements": _dedupe(requirement_ids),
        "user_flows": _dedupe(_string_ids(chapter.get("user_flow_ids")) or [str(item.get("id")) for item in flows if item.get("chapter_id") == chapter.get("id") and item.get("kind") == "user_flow"]),
        "edge_cases": _dedupe(_string_ids(chapter.get("edge_case_ids")) or [str(item.get("id")) for item in flows if item.get("chapter_id") == chapter.get("id") and item.get("kind") == "edge_case"]),
        "models": _dedupe(model_ids),
        "checks": _dedupe(check_ids),
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _render_section_cards(title: str, cards: list[str], *, icon: str, anchor: str = "") -> str:
    if not cards:
        return ""
    return f'<section class="chapter-block">{_heading(3, icon, title, anchor=anchor)}{"".join(cards)}</section>'


def _render_chapter(
    chapter: dict[str, Any],
    *,
    contract: dict[str, Any],
    assertions_by_id: dict[str, dict[str, Any]],
    flows_by_id: dict[str, dict[str, Any]],
    checks_by_id: dict[str, dict[str, Any]],
    surface_lookup: dict[str, dict[str, Any]],
) -> str:
    models = _as_mapping(contract.get("models"), "models")
    items = _chapter_items(chapter, contract)
    requirement_cards = [_render_requirement(assertions_by_id[item], surface_lookup) for item in items["requirements"] if item in assertions_by_id]
    user_flow_cards = [_render_flow(flows_by_id[item], surface_lookup) for item in items["user_flows"] if item in flows_by_id]
    edge_case_cards = [_render_flow(flows_by_id[item], surface_lookup) for item in items["edge_cases"] if item in flows_by_id]
    model_cards = [_render_model(item, models[item]) for item in items["models"] if item in models and isinstance(models[item], dict)]
    check_cards = [_render_check(checks_by_id[item]) for item in items["checks"] if item in checks_by_id]
    chapter_id = str(chapter["id"])
    return f"""
<section class="chapter" id="{_anchor('chapter', chapter_id)}">
  <div class="chapter-label">{_icon('chapter', css_class='card-icon')}Capability Chapter</div>
  {_heading(2, 'chapter', str(chapter.get('title') or chapter_id))}
  <p class="chapter-summary">{_escape(chapter.get('summary', ''))}</p>
  {_render_section_cards('Requirements', requirement_cards, icon='requirement', anchor=f'{_anchor("chapter", chapter_id)}-requirements')}
  {_render_section_cards('User Flows', user_flow_cards, icon='user_flow', anchor=f'{_anchor("chapter", chapter_id)}-user-flows')}
  {_render_section_cards('Edge Cases', edge_case_cards, icon='edge_case', anchor=f'{_anchor("chapter", chapter_id)}-edge-cases')}
  {_render_section_cards('Relevant Models', model_cards, icon='model', anchor=f'{_anchor("chapter", chapter_id)}-models')}
  {_render_section_cards('Linked Checks', check_cards, icon='check', anchor=f'{_anchor("chapter", chapter_id)}-checks')}
</section>"""


def _render_scope(contract: dict[str, Any]) -> str:
    scope = _as_mapping(contract.get("scope"), "scope")
    includes = "".join(f"<li>{_escape(item)}</li>" for item in _as_list(scope.get("includes"), "scope.includes"))
    excludes = "".join(f"<li>{_escape(item)}</li>" for item in _as_list(scope.get("excludes"), "scope.excludes"))
    return f"""
<section class="scope" id="scope-and-boundaries">
  {_heading(2, 'scope', 'Scope And Boundaries')}
  <div class="columns">
    <div><h3>Includes</h3><ul>{includes}</ul></div>
    <div><h3>Excludes</h3><ul>{excludes}</ul></div>
  </div>
</section>"""


def _render_legend(contract: dict[str, Any]) -> str:
    presentation = _as_mapping(contract.get("presentation"), "presentation")
    legend = _as_mapping(presentation.get("legend", {}), "presentation.legend")
    if not legend:
        return ""
    icon_names = {"requirement": "requirement", "user_flow": "user_flow", "edge_case": "edge_case", "check": "check", "model": "model", "surface": "surface"}
    targets = {"requirement": "index-requirements", "user_flow": "index-user-flows", "edge_case": "index-edge-cases", "check": "index-checks", "model": "index-models", "surface": "project-surfaces"}
    items = "".join(
        f'<a class="legend-item" href="#{targets.get(str(key), "generated-indexes")}">'
        f'{_icon(icon_names.get(str(key), "legend"))}<span><strong>{_escape(_label(key))}</strong>{_escape(value)}<small>Open index</small></span></a>'
        for key, value in legend.items()
    )
    return f'<section class="legend" id="legend">{_heading(2, "legend", "Legend")}<div class="legend-grid">{items}</div></section>'


def _render_navigation(chapters: list[dict[str, Any]]) -> str:
    chapter_links = "".join(
        f'<a class="toc-link" href="#{_anchor("chapter", chapter["id"])}">'
        f'{_icon("chapter")}<span><strong>{index}. {_escape(chapter.get("title") or chapter["id"])}</strong>'
        f'<small>{_escape(chapter.get("summary", ""))}</small></span></a>'
        for index, chapter in enumerate(chapters, start=1)
    )
    utility_links = "".join(
        f'<a class="utility-link" href="#{target}">{_icon(icon)}<span>{_escape(label)}</span></a>'
        for target, icon, label in (
            ("scope-and-boundaries", "scope", "Scope and boundaries"),
            ("project-surfaces", "surface", "Project surfaces"),
            ("generated-indexes", "indexes", "Generated indexes"),
        )
    )
    return (
        f'<nav class="navigation" id="navigation">{_heading(2, "navigation", "Chapters")}'
        f'<div class="toc-grid">{chapter_links}</div><div class="utility-links">{utility_links}</div></nav>'
    )


def _render_surface_catalog(contract: dict[str, Any], surface_lookup: dict[str, dict[str, Any]]) -> str:
    catalog = _as_mapping(contract.get("project_surface_catalog"), "project_surface_catalog")
    surfaces = []
    for surface_id, surface in surface_lookup.items():
        status = str(surface.get("status") or "active")
        kind = str(surface.get("kind") or "surface")
        surfaces.append(f'<span class="chip surface {"deferred" if status == "deferred" else ""}">{_escape(surface.get("label") or surface_id)} - {_escape(_label(kind))}{"; " + _escape(status) if status != "active" else ""}</span>')
    return f"""
<section class="catalog" id="project-surfaces">
  {_heading(2, 'surface', 'Project Surfaces')}
  <p>Home Project: <strong>{_escape(catalog.get('home_project_id', ''))}</strong>; catalog revision: <code>{_escape(catalog.get('revision_id', ''))}</code></p>
  <div class="chips">{"".join(surfaces)}</div>
</section>"""


def _render_index_table(headers: list[str], rows: list[list[str]]) -> str:
    header_html = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    row_html = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    if not rows:
        row_html = f'<tr><td colspan="{len(headers)}" class="muted">No entries.</td></tr>'
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{row_html}</tbody></table>"


def _render_generated_indexes(bundle: specifications.SpecificationBundle, surface_lookup: dict[str, dict[str, Any]]) -> str:
    contract = bundle.specification
    presentation = _as_mapping(contract.get("presentation"), "presentation")
    requested = _string_ids(presentation.get("generated_indexes"))
    assertions = [item for item in _as_list(contract.get("assertions"), "assertions") if isinstance(item, dict)]
    flows = [item for item in _as_list(contract.get("flows"), "flows") if isinstance(item, dict)]
    checks = [item for item in _as_list(contract.get("check_obligations"), "check_obligations") if isinstance(item, dict)]
    models = _as_mapping(contract.get("models"), "models")
    chapters = {str(chapter["id"]): str(chapter.get("title") or chapter["id"]) for chapter in _ordered_chapters(contract)}
    sections: list[str] = []
    if "requirements" in requested:
        sections.append(_heading(3, "requirement", "Requirements", anchor="index-requirements") + _render_index_table(
            ["ID", "Title", "Chapter", "Surfaces"],
            [[f'<code>{_escape(item.get("id", ""))}</code>', _escape(item.get("title") or item.get("id", "")), _escape(chapters.get(str(item.get("chapter_id")), item.get("chapter_id", ""))), _render_surfaces(_string_ids(item.get("project_surface_ids")), surface_lookup)] for item in assertions],
        ))
    if "user_flows" in requested:
        user_flows = [item for item in flows if item.get("kind") == "user_flow"]
        sections.append(_heading(3, "user_flow", "User Flows", anchor="index-user-flows") + _render_index_table(
            ["ID", "Title", "Chapter", "Surfaces"],
            [[f'<code>{_escape(item.get("id", ""))}</code>', _escape(item.get("title") or item.get("id", "")), _escape(chapters.get(str(item.get("chapter_id")), item.get("chapter_id", ""))), _render_surfaces(_string_ids(item.get("surface_ids")), surface_lookup)] for item in user_flows],
        ))
    if "edge_cases" in requested:
        edge_cases = [item for item in flows if item.get("kind") == "edge_case"]
        sections.append(_heading(3, "edge_case", "Edge Cases", anchor="index-edge-cases") + _render_index_table(
            ["ID", "Title", "Parent Flow", "Chapter"],
            [[f'<code>{_escape(item.get("id", ""))}</code>', _escape(item.get("title") or item.get("id", "")), f'<code>{_escape(item.get("parent_flow_id", ""))}</code>', _escape(chapters.get(str(item.get("chapter_id")), item.get("chapter_id", "")))] for item in edge_cases],
        ))
    if "models" in requested:
        placements: dict[str, list[str]] = {}
        for placement in contract.get("model_placements") or []:
            if isinstance(placement, dict) and isinstance(placement.get("model_id"), str):
                placements[placement["model_id"]] = _string_ids(placement.get("chapter_ids"))
        sections.append(_heading(3, "model", "Models", anchor="index-models") + _render_index_table(
            ["ID", "Fields", "Chapters"],
            [[f'<code>{_escape(model_id)}</code>', str(len(fields)) if isinstance(fields, dict) else "0", _escape(", ".join(chapters.get(chapter_id, chapter_id) for chapter_id in placements.get(model_id, [])))] for model_id, fields in models.items()],
        ))
    if "checks" in requested:
        sections.append(_heading(3, "check", "Checks", anchor="index-checks") + _render_index_table(
            ["ID", "Title", "Sources"],
            [[f'<code>{_escape(item.get("id", ""))}</code>', _escape(item.get("title") or item.get("id", "")), str(len(item.get("sources") or []))] for item in checks],
        ))
    if "examples" in requested:
        rows = []
        for group, cases in bundle.examples.items():
            if group in SKIPPED_EXAMPLE_FIELDS:
                continue
            case_list = cases if isinstance(cases, list) else []
            ids = ", ".join(_identity(case, f"case-{index}") for index, case in enumerate(case_list, start=1))
            rows.append([f'<code>{_escape(group)}</code>', str(len(case_list)), _escape(ids)])
        sections.append(_heading(3, "examples", "Examples", anchor="index-examples") + _render_index_table(["Group", "Count", "Example IDs"], rows))
    if "history" in requested:
        rows = [
            ["Specification", f'<code>{_escape(bundle.versioned_id)}</code>'],
            ["Status", _escape(bundle.status)],
            ["Fingerprint", f'<code>{_escape(bundle.fingerprint)}</code>'],
        ]
        sections.append(_heading(3, "history", "History", anchor="index-history") + _render_index_table(["Field", "Value"], rows))
    return f'<section class="indexes" id="generated-indexes">{_heading(2, "indexes", "Generated Indexes")}{"".join(sections)}</section>'


def build_html(bundle: specifications.SpecificationBundle) -> str:
    bundle = with_default_presentation(bundle)
    contract = bundle.specification
    _as_mapping(contract.get("presentation"), "presentation")
    surface_lookup = _surface_lookup(contract)
    assertions_by_id = _by_id(contract.get("assertions"), "assertions")
    flows_by_id = _by_id(contract.get("flows"), "flows")
    checks_by_id = _by_id(contract.get("check_obligations"), "check_obligations")
    chapters = _ordered_chapters(contract)
    rendered_chapters = "".join(
        _render_chapter(
            chapter,
            contract=contract,
            assertions_by_id=assertions_by_id,
            flows_by_id=flows_by_id,
            checks_by_id=checks_by_id,
            surface_lookup=surface_lookup,
        )
        for chapter in chapters
    )
    title = str(contract.get("title") or bundle.specification_id)
    status = str(contract.get("status") or "unknown")
    outcome = str(contract.get("outcome") or contract.get("summary") or "")
    summary = str(contract.get("summary") or "")
    summary_html = f'<p>{_escape(summary)}</p>' if summary and summary != outcome else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_escape(title)} readable Specification</title>
<style>
@page {{ size: A4; margin: 16mm 13mm 18mm; }}
@media screen {{ body {{ margin: 0 auto; padding: 16mm 13mm 18mm; width: 210mm; }} .front-page {{ height: 263mm; overflow: hidden; }} }}
.preview-mode .front-page ~ * {{ display: none; }}
* {{ box-sizing: border-box; }}
body {{ color: #14212e; font: 10.2pt/1.46 Arial, sans-serif; margin: 0; }}
h1 {{ font-size: 27pt; line-height: 1.05; margin: 0 0 3mm; }}
h2 {{ break-after: avoid; border-bottom: 1px solid #c9d5e1; font-size: 16pt; margin: 9mm 0 3mm; padding-bottom: 1.6mm; }}
h3 {{ break-after: avoid; color: #26394c; font-size: 12pt; margin: 5mm 0 2mm; }}
h4 {{ break-after: avoid; font-size: 10.8pt; margin: 0 0 1mm; }}
a {{ color: inherit; text-decoration: none; }}
p {{ margin: 1.5mm 0 2mm; }}
code {{ background: #eef3f7; border-radius: 1mm; font: 8.5pt/1.35 "Courier New", monospace; padding: .3mm .8mm; }}
table {{ border-collapse: collapse; margin: 2mm 0 4mm; width: 100%; }}
th, td {{ border-bottom: 1px solid #d8e1ea; padding: 1.4mm 1.2mm; text-align: left; vertical-align: top; }}
th {{ color: #52616f; font-size: 8pt; letter-spacing: .03em; text-transform: uppercase; }}
ul, ol {{ margin: 1mm 0 2mm 5mm; padding-left: 4mm; }}
li {{ margin: .8mm 0; }}
.front-page {{ break-after: page; }}
.hero {{ background: linear-gradient(135deg, #edf5ff, #f7f2ff); border: 1px solid #d9e4f0; border-radius: 5mm; margin-bottom: 3mm; padding: 4.5mm; }}
.status {{ display: flex; flex-wrap: wrap; gap: 1.5mm; margin: 3mm 0 1mm; }}
.pill {{ background: #17212b; border-radius: 999px; color: white; display: inline-block; font-size: 8.5pt; font-weight: 700; padding: 1mm 2.2mm; }}
.fingerprint {{ color: #52616f; font: 8pt/1.35 "Courier New", monospace; overflow-wrap: anywhere; }}
.lead {{ font-size: 11pt; margin-top: 2mm; }}
.muted {{ color: #6d7d8c; }}
.icon {{ fill: none; flex: 0 0 auto; height: 4.2mm; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; width: 4.2mm; }}
.card-icon {{ fill: none; height: 3.5mm; margin-right: 1mm; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; vertical-align: -0.8mm; width: 3.5mm; }}
.section-heading {{ align-items: center; display: flex; gap: 1.5mm; }}
.columns {{ display: grid; gap: 5mm; grid-template-columns: 1fr 1fr; }}
.front-page h2 {{ font-size: 12.5pt; margin: 3mm 0 1.5mm; }}
.legend-grid {{ display: grid; gap: 1.2mm; grid-template-columns: 1fr 1fr 1fr; }}
.legend-item {{ align-items: flex-start; background: #f6f9fc; border: 1px solid #dce5ed; border-radius: 2mm; display: flex; gap: 1.2mm; padding: 1.4mm; }}
.legend-item span {{ color: #344658; font-size: 7.5pt; line-height: 1.25; }}
.legend-item strong {{ display: block; font-size: 7.4pt; letter-spacing: .03em; margin-bottom: .4mm; text-transform: uppercase; }}
.legend-item small {{ color: #7256d9; display: block; font-size: 6.7pt; font-weight: 700; margin-top: .6mm; }}
.card-kind, .chapter-label, .meta-label {{ color: #52616f; font-size: 7.6pt; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }}
.toc-grid {{ display: grid; gap: 1.2mm; grid-template-columns: 1fr 1fr; }}
.toc-link {{ align-items: flex-start; border-left: 3px solid #7256d9; display: flex; gap: 1.4mm; padding: 1.2mm 1.7mm; }}
.toc-link strong {{ display: block; font-size: 8.3pt; }}
.toc-link small {{ color: #52616f; display: block; font-size: 7pt; line-height: 1.25; margin-top: .3mm; }}
.utility-links {{ display: flex; gap: 2mm; margin-top: 2mm; }}
.utility-link {{ align-items: center; background: #eef3f7; border-radius: 999px; display: flex; font-size: 7.8pt; gap: 1mm; padding: 1mm 1.8mm; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 1.2mm; }}
.chip {{ background: #eef3f7; border: 1px solid #d6e0ea; border-radius: 999px; display: inline-block; font-size: 8.1pt; margin: .4mm .7mm .4mm 0; padding: .6mm 1.5mm; }}
.surface {{ background: #e9f4ff; border-color: #bad7f7; }}
.surface.deferred {{ background: #fff4db; border-color: #ebcc81; }}
.requirement-chip {{ background: #f3edff; border-color: #d7c5ff; }}
.check-chip {{ background: #eaf9ef; border-color: #bee4c8; }}
.chapter {{ break-before: page; }}
.chapter-summary {{ color: #3a4b5b; font-size: 11pt; }}
.chapter-block {{ margin-top: 4mm; }}
.card {{ border: 1px solid #d8e1ea; border-radius: 3mm; break-inside: avoid; margin: 2mm 0 3mm; padding: 3mm; }}
.requirement {{ border-left: 4px solid #7256d9; }}
.flow {{ border-left: 4px solid #2c8ccf; }}
.flow-layout {{ align-items: start; display: grid; gap: 3mm; grid-template-columns: 58mm 1fr; }}
.flow-wireframe {{ margin: 0; width: 58mm; }}
.wireframe-window {{ background: #fff; border: 1px solid #aebdca; border-radius: 2mm; height: 39mm; overflow: hidden; }}
.wireframe-topbar {{ align-items: center; background: #edf2f6; border-bottom: 1px solid #c9d5df; display: flex; gap: 1mm; height: 6mm; padding: 0 1.5mm; }}
.wireframe-topbar > span {{ background: #aebdca; border-radius: 50%; height: 1.4mm; width: 1.4mm; }}
.wireframe-topbar strong {{ color: #52616f; font-size: 6.5pt; margin-left: auto; }}
.wireframe-body {{ display: grid; grid-template-columns: 10mm 1fr; height: 33mm; }}
.wireframe-sidebar {{ background: #f5f8fa; border-right: 1px solid #d8e1e8; padding: 3mm 2.5mm; }}
.wireframe-sidebar i {{ background: #c9d5df; border-radius: 1mm; display: block; height: 2mm; margin-bottom: 2.4mm; }}
.wireframe-canvas {{ padding: 3mm; }}
.wireframe-title {{ font-size: 7.2pt; font-weight: 700; height: 5mm; max-width: 40mm; overflow: hidden; white-space: nowrap; }}
.wireframe-line {{ background: #d8e1e8; border-radius: 1mm; height: 1.5mm; margin: 1.5mm 0; width: 68%; }}
.wireframe-line.wide {{ width: 92%; }}
.wireframe-panel {{ background: #eef4f8; border: 1px solid #d8e1e8; border-radius: 1.5mm; height: 10mm; margin-top: 2.5mm; padding: 2mm; }}
.wireframe-panel b, .wireframe-panel span {{ background: #b9c8d5; border-radius: 1mm; display: block; height: 1.4mm; margin-bottom: 1.2mm; width: 45%; }}
.wireframe-panel span {{ background: #d2dce5; width: 85%; }}
.wireframe-actions {{ display: flex; gap: 1.5mm; justify-content: flex-end; margin-top: 2mm; }}
.wireframe-actions i {{ background: #ccd8e2; border-radius: 1mm; height: 3mm; width: 9mm; }}
.wireframe-actions i:last-child {{ background: #7256d9; }}
.flow-wireframe figcaption {{ color: #52616f; font-size: 7pt; margin-top: 1mm; text-align: center; }}
.model {{ border-left: 4px solid #8c6b20; }}
.check {{ border-left: 4px solid #2f9d55; }}
.item-id {{ margin-bottom: 1.5mm; }}
.card-meta {{ background: #f7fafc; border-radius: 2mm; margin: 2mm 0; padding: 1.5mm 2mm; }}
.meta-row {{ display: grid; gap: 2mm; grid-template-columns: 28mm 1fr; margin: .8mm 0; }}
.indexes h3 {{ margin-top: 6mm; }}
.footer-note {{ color: #52616f; font-size: 8.5pt; margin-top: 10mm; }}
</style>
</head>
<body>
<section class="front-page">
<section class="hero" id="contract-outcome">
  <div class="chapter-label">{_icon('outcome', css_class='card-icon')}Capability Specification</div>
  <h1>{_escape(title)}</h1>
  <div class="status">
    <span class="pill">{_escape(bundle.versioned_id)}</span>
    <span class="pill">{_escape(_label(status))}</span>
  </div>
  <p class="fingerprint">Fingerprint: {bundle.fingerprint}</p>
  <p class="lead">{_escape(outcome)}</p>
  {summary_html}
</section>
{_render_legend(contract)}
{_render_navigation(chapters)}
</section>
{_render_surface_catalog(contract, surface_lookup)}
{_render_scope(contract)}
{rendered_chapters}
{_render_generated_indexes(bundle, surface_lookup)}
<p class="footer-note">This is a readable Specification presentation, not an approval receipt. Exact approval must use the highlighted approval PDF and matching review artifact.</p>
</body>
</html>"""


def render_pdf(document: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    playwright, browser = launch_browser()
    try:
        page = browser.new_page()
        page.set_content(document, wait_until="load")
        page.pdf(
            path=str(output),
            format="A4",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            prefer_css_page_size=True,
            display_header_footer=True,
            header_template="<span></span>",
            footer_template=(
                '<div style="font:8px Arial,sans-serif;color:#52616f;text-align:center;width:100%;">'
                '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
            ),
        )
    finally:
        browser.close()
        playwright.stop()


def render_preview(document: str, output: Path, *, anchor: str = "") -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    playwright, browser = launch_browser()
    try:
        page = browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=1)
        page.set_content(document, wait_until="load")
        if anchor:
            target = page.locator(f"#{anchor}")
            if target.count() != 1:
                raise ReadableSpecificationError(f"preview anchor must resolve exactly once: {anchor}")
            target.screenshot(path=str(output))
        else:
            page.evaluate("document.body.classList.add('preview-mode')")
            page.screenshot(path=str(output), clip={"x": 0, "y": 0, "width": 794, "height": 1123})
    finally:
        browser.close()
        playwright.stop()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render and optionally upload a readable Specification presentation PDF")
    parser.add_argument("bundle", help="Specification bundle directory or specification.yml path")
    parser.add_argument("--output", type=Path, help="PDF output path; defaults under /tmp/opencode/specification-presentations")
    parser.add_argument("--preview-output", type=Path, help="Optional first-page PNG used for deterministic visual inspection")
    parser.add_argument("--preview-anchor", default="", help="Render one element id instead of page one when --preview-output is set")
    parser.add_argument("--container", default=opencode_response_media.DEFAULT_CONTAINER, help="API container used for S3 upload")
    parser.add_argument("--no-upload", action="store_true", help="Generate the PDF without uploading it")
    parser.add_argument("--dry-run-upload", action="store_true", help="Generate a fake upload result without Docker or S3")
    parser.add_argument("--json", action="store_true", help="Print the complete result as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        bundle = specifications.validate_bundle(specifications._resolve_specification_path(args.bundle))
        output = args.output or DEFAULT_OUTPUT_ROOT / f"{_safe_name(bundle.specification_id)}-{bundle.fingerprint[:16]}-readable.pdf"
        document = build_html(bundle)
        render_pdf(document, output)
        if args.preview_output:
            render_preview(document, args.preview_output, anchor=args.preview_anchor)
        result: dict[str, Any] = {
            "specification": bundle.versioned_id,
            "fingerprint": bundle.fingerprint,
            "pdf": str(output.resolve()),
            **({"preview": str(args.preview_output.resolve())} if args.preview_output else {}),
        }
        if not args.no_upload:
            result["publication"] = opencode_response_media.upload_file(
                output,
                alt=f"Read {bundle.versioned_id} readable Specification PDF",
                container=args.container,
                dry_run=args.dry_run_upload,
            )
    except Exception as exc:
        print(f"specification_readable_pdf: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Specification: {result['specification']}")
        print(f"Fingerprint: {result['fingerprint']}")
        print(f"PDF: {result['pdf']}")
        publication = result.get("publication")
        if isinstance(publication, dict):
            snippets = publication.get("snippets")
            if isinstance(snippets, dict):
                print("\nMarkdown:")
                print(snippets["markdown"])
                print("\nHTML:")
                print(snippets["html"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
