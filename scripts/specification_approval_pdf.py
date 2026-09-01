#!/usr/bin/env python3
"""Render and privately publish an exact-fingerprint Specification approval PDF.

The document contains the full Specification and examples in a readable hierarchy.
Only changed text is colored: green plus-marked insertions and red minus-marked
deletions. The resulting PDF is uploaded through the existing private 48-hour
OpenCode response-media path by default.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import specifications  # noqa: E402
from scripts import specification_readable_pdf as readable_pdf  # noqa: E402
from scripts import opencode_response_media  # noqa: E402
from scripts.playwright_visual_smoke import launch_browser  # noqa: E402


DEFAULT_BASELINE_REF = "HEAD"
DEFAULT_OUTPUT_ROOT = Path("/tmp/opencode/specification-approvals")
MISSING = object()
IDENTITY_FIELDS = ("id", "name", "key")


def _label(value: object) -> str:
    text = str(value).replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:]


def _classes(*values: str) -> str:
    return " ".join(value for value in values if value)


def _display_text(value: object) -> str:
    return str(value).translate(str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-"}))


def _scalar(value: Any) -> str:
    if value is None:
        return '<span class="value empty">Not set</span>'
    if isinstance(value, bool):
        return f'<span class="value badge">{"Yes" if value else "No"}</span>'
    if isinstance(value, (int, float)):
        return f'<span class="value number">{html.escape(str(value))}</span>'
    displayed = _display_text(value)
    escaped = html.escape(displayed)
    if "\n" in displayed:
        return f'<div class="value multiline">{escaped.replace(chr(10), "<br>")}</div>'
    return f'<span class="value">{escaped}</span>'


def _text_diff(baseline: Any, current: Any) -> str:
    current_text = _display_text(current)
    if baseline is MISSING:
        rendered = html.escape(current_text).replace("\n", "<br>")
        return f'<span class="diff-insert"><b>+</b>{rendered}</span>'
    baseline_text = _display_text(baseline)
    if baseline_text == current_text:
        return html.escape(current_text)
    baseline_tokens = re.findall(r"\s+|[^\s]+", baseline_text)
    current_tokens = re.findall(r"\s+|[^\s]+", current_text)
    pieces = []
    for operation, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(None, baseline_tokens, current_tokens).get_opcodes():
        old_text = "".join(baseline_tokens[old_start:old_end])
        new_text = "".join(current_tokens[new_start:new_end])
        if operation == "equal":
            pieces.append(html.escape(new_text))
        elif operation == "delete":
            pieces.append(f'<span class="diff-delete"><b>-</b>{html.escape(old_text)}</span>')
        elif operation == "insert":
            pieces.append(f'<span class="diff-insert"><b>+</b>{html.escape(new_text)}</span>')
        else:
            pieces.append(f'<span class="diff-delete"><b>-</b>{html.escape(old_text)}</span>')
            pieces.append(f'<span class="diff-insert"><b>+</b>{html.escape(new_text)}</span>')
    return "".join(pieces).replace("\n", "<br>")


def _scalar_diff(current: Any, baseline: Any) -> str:
    if current == baseline:
        return _scalar(current)
    if isinstance(current, str) and (baseline is MISSING or isinstance(baseline, str)):
        return f'<span class="value diff-text">{_text_diff(baseline, current)}</span>'
    if baseline is MISSING:
        return f'<span class="diff-insert"><b>+</b>{_scalar(current)}</span>'
    return f'<span class="diff-delete"><b>-</b>{_scalar(baseline)}</span><span class="diff-insert"><b>+</b>{_scalar(current)}</span>'


def _identity(item: Any) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    for field in IDENTITY_FIELDS:
        value = item.get(field)
        if isinstance(value, (str, int, float)):
            return field, str(value)
    return None


def _match_list_items(current: list[Any], baseline: list[Any]) -> tuple[list[Any], list[Any]]:
    used_baseline_indexes: set[int] = set()
    matches: list[Any] = []
    for item in current:
        identity = _identity(item)
        match = MISSING
        for index, candidate in enumerate(baseline):
            if index in used_baseline_indexes:
                continue
            candidate_matches = _identity(candidate) == identity if identity is not None else candidate == item
            if candidate_matches:
                used_baseline_indexes.add(index)
                match = candidate
                break
        matches.append(match)
    removed = [item for index, item in enumerate(baseline) if index not in used_baseline_indexes]
    return matches, removed


def render_node(key: str, current: Any, baseline: Any = MISSING, *, level: int = 2) -> str:
    changed = baseline is MISSING or current != baseline
    new_value = baseline is MISSING
    heading_level = min(level, 6)
    title = html.escape(_label(key))

    if isinstance(current, dict):
        baseline_map = baseline if isinstance(baseline, dict) else {}
        body = [
            render_node(str(child_key), value, baseline_map.get(child_key, MISSING), level=level + 1)
            for child_key, value in current.items()
        ]
        for removed_key, removed_value in baseline_map.items():
            if removed_key not in current:
                body.append(render_removed(str(removed_key), removed_value, level=level + 1))
        section_class = _classes("node", "mapping", "diff-added" if new_value else "")
        return f'<section class="{section_class}"><h{heading_level}>{title}</h{heading_level}>{"".join(body)}</section>'

    if isinstance(current, list):
        baseline_list = baseline if isinstance(baseline, list) else []
        matched_baselines, removed_items = _match_list_items(current, baseline_list)
        items = []
        for index, value in enumerate(current):
            item_baseline = matched_baselines[index]
            identity = _identity(value)
            item_key = str(identity[1]) if identity is not None else f"Item {index + 1}"
            items.append(f"<li>{render_node(item_key, value, item_baseline, level=level + 1)}</li>")
        for removed in removed_items:
            items.append(f"<li>{render_removed('Removed item', removed, level=level + 1)}</li>")
        section_class = _classes("node", "sequence", "diff-added" if new_value else "")
        empty = '<div class="value empty">None</div>' if not items else ""
        return f'<section class="{section_class}"><h{heading_level}>{title}</h{heading_level}>{empty}<ol>{"".join(items)}</ol></section>'

    field_class = _classes("field", "diff-field" if changed else "", "new" if new_value else "")
    return f'<div class="{field_class}"><div class="field-label">{title}</div>{_scalar_diff(current, baseline)}</div>'


def render_removed(key: str, value: Any, *, level: int) -> str:
    heading_level = min(level, 6)
    title = html.escape(_label(key))
    rendered = html.escape(_display_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).strip()))
    return (
        f'<section class="node removed"><h{heading_level}>{title} <span class="removed-label">Removed</span></h{heading_level}>'
        f'<pre>{rendered}</pre></section>'
    )


def build_legacy_html(
    bundle: specifications.SpecificationBundle,
    *,
    baseline_contract: dict[str, Any] | None,
    baseline_examples: dict[str, Any] | None,
    baseline_ref: str,
) -> str:
    baseline_contract = baseline_contract or {}
    baseline_examples = baseline_examples or {}
    title = html.escape(str(bundle.specification.get("title") or bundle.specification_id))
    fingerprint = html.escape(bundle.fingerprint)
    versioned_id = html.escape(bundle.versioned_id)
    baseline = html.escape(baseline_ref)
    contract_body = render_node("Specification", bundle.specification, baseline_contract, level=2)
    examples_body = render_node("Examples", bundle.examples, baseline_examples, level=2)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} Specification approval</title>
<style>
@page {{ size: A4; margin: 16mm 14mm 18mm; }}
* {{ box-sizing: border-box; }}
body {{ color: #17212b; font: 10.5pt/1.45 Arial, sans-serif; margin: 0; }}
h1 {{ font-size: 24pt; line-height: 1.12; margin: 0 0 4mm; }}
h2 {{ border-bottom: 1px solid #cbd5df; font-size: 17pt; margin: 9mm 0 3mm; padding-bottom: 2mm; }}
h2, h3, h4, h5, h6 {{ break-after: avoid; }}
h3 {{ font-size: 13pt; margin: 5mm 0 2mm; }}
h4, h5, h6 {{ font-size: 11pt; margin: 3mm 0 1.5mm; }}
.meta {{ background: #edf3f8; border-radius: 3mm; margin: 5mm 0; padding: 4mm; }}
.meta-row {{ display: grid; grid-template-columns: 34mm 1fr; gap: 3mm; margin: 1mm 0; }}
.meta-label, .field-label {{ color: #52616f; font-size: 8.5pt; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; }}
.fingerprint {{ font-family: "Courier New", monospace; font-size: 8pt; overflow-wrap: anywhere; }}
.legend {{ align-items: center; display: flex; gap: 3mm; margin: 4mm 0 8mm; }}
.swatch {{ background: #fff2a8; border: 1px solid #e2c94f; display: inline-block; height: 5mm; width: 9mm; }}
.node {{ margin: 2mm 0; }}
.node.mapping > .node, .node.sequence > ol {{ margin-left: 3mm; }}
.field {{ border-left: 2px solid #d9e1e8; break-inside: avoid; margin: 1.5mm 0; padding: 2mm 3mm; }}
.diff-added {{ border-left: 3px solid #239b56; padding-left: 2mm; }}
.diff-insert {{ background: #e6f7ec; color: #176b3b; text-decoration: none; }}
.diff-delete {{ background: #fdebec; color: #a52a32; text-decoration: line-through; }}
.diff-insert, .diff-delete {{ border-radius: 1mm; display: inline; margin: 0 .4mm; padding: .2mm .7mm; }}
.diff-insert b, .diff-delete b {{ margin-right: .6mm; text-decoration: none; }}
.value {{ overflow-wrap: anywhere; white-space: normal; }}
.value.badge {{ background: #dbeafe; border-radius: 99px; display: inline-block; font-weight: 700; padding: 0 2mm; }}
.value.empty {{ color: #71808f; font-style: italic; }}
.removed {{ background: #fdebec; border: 1px dashed #c84951; }}
.removed-label {{ color: #a52a32; font-size: 8pt; text-transform: uppercase; }}
ol {{ margin: 1mm 0 2mm 5mm; padding-left: 5mm; }}
li {{ margin: 1mm 0; padding-left: 1mm; }}
pre {{ font: 8pt/1.35 "Courier New", monospace; margin: 1mm 0; overflow-wrap: anywhere; white-space: pre-wrap; }}
.footer-note {{ color: #52616f; font-size: 8.5pt; margin-top: 10mm; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">
  <div class="meta-row"><div class="meta-label">Specification</div><div>{versioned_id}</div></div>
  <div class="meta-row"><div class="meta-label">Status</div><div>{html.escape(bundle.status)}</div></div>
  <div class="meta-row"><div class="meta-label">Fingerprint</div><div class="fingerprint">{fingerprint}</div></div>
  <div class="meta-row"><div class="meta-label">Compared with</div><div>{baseline}</div></div>
</div>
<div class="legend"><span class="diff-insert"><b>+</b> added</span><span class="diff-delete"><b>-</b> removed</span><span>Only changed text is colored; unchanged text remains neutral.</span></div>
{contract_body}
{examples_body}
<p class="footer-note">Approval must match the exact fingerprint printed above. Any later Specification or example edit requires a new PDF and approval.</p>
</body>
</html>"""


def _item_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item["id"]): item
        for item in value
        if isinstance(item, dict) and isinstance(item.get("id"), (str, int, float))
    }


def _changed_item_ids(current: Any, baseline: Any) -> list[str]:
    current_items = _item_map(current)
    baseline_items = _item_map(baseline)
    return [item_id for item_id, item in current_items.items() if item != baseline_items.get(item_id, MISSING)]


def _removed_items(current: Any, baseline: Any) -> list[dict[str, Any]]:
    current_items = _item_map(current)
    baseline_items = _item_map(baseline)
    return [item for item_id, item in baseline_items.items() if item_id not in current_items]


def _mark_diff_status(document: str, *, css_class: str, anchor: str, added: bool) -> str:
    marker = f'<section class="{css_class}" id="{anchor}">'
    status = "diff-added" if added else "diff-modified"
    replacement = f'<section class="{css_class} {status}" id="{anchor}">'
    return document.replace(marker, replacement, 1)


def _replace_after_anchor(document: str, anchor: str, current_html: str, replacement_html: str) -> str:
    anchor_index = document.find(f'id="{anchor}"')
    if anchor_index < 0:
        return document
    value_index = document.find(current_html, anchor_index)
    if value_index < 0:
        return document
    return document[:value_index] + replacement_html + document[value_index + len(current_html):]


def _change_summary(
    bundle: specifications.SpecificationBundle,
    baseline_contract: dict[str, Any],
    baseline_examples: dict[str, Any],
    baseline_ref: str,
) -> str:
    specification = bundle.specification
    groups = [
        ("Chapters", "chapter", "chapters", readable_pdf._anchor("chapter", bundle.specification.get("presentation", {}).get("chapter_order", ["chapter"])[0])),
        ("Requirements", "requirement", "assertions", "index-requirements"),
        ("Flows and edge cases", "user_flow", "flows", "index-user-flows"),
        ("Checks", "check", "check_obligations", "index-checks"),
    ]
    cards = []
    for label, icon, field, target in groups:
        changed = _changed_item_ids(specification.get(field), baseline_contract.get(field))
        removed = _removed_items(specification.get(field), baseline_contract.get(field))
        cards.append(
            f'<a class="change-count" href="#{target}">{readable_pdf._icon(icon)}'
            f'<span><strong>{len(changed)}</strong>{html.escape(label)} changed'
            f'{f"; {len(removed)} removed" if removed else ""}</span></a>'
        )
    changed_example_groups = sum(
        1 for key, value in bundle.examples.items()
        if key not in {"schema_version", "specification"} and value != baseline_examples.get(key, MISSING)
    )
    cards.append(
        f'<a class="change-count" href="#approval-examples">{readable_pdf._icon("examples")}'
        f'<span><strong>{changed_example_groups}</strong>Example groups changed</span></a>'
    )
    return (
        '<section class="change-summary" id="change-summary">'
        f'{readable_pdf._heading(2, "history", "Changes Since " + baseline_ref)}'
        '<p>Green <strong>+</strong> text was added; red <strong>-</strong> text was removed. Unchanged text remains neutral.</p>'
        f'<div class="change-grid">{"".join(cards)}</div></section>'
    )


def _compact_value(value: Any) -> str:
    if value is None:
        return '<span class="value empty">Not set</span>'
    if isinstance(value, bool):
        return f'<span class="value badge">{"Yes" if value else "No"}</span>'
    if isinstance(value, str) and len(value) <= 120 and "\n" not in value:
        return f'<span class="value">{html.escape(_display_text(value))}</span>'
    rendered = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(", ", ": "))
    return f'<code class="compact-json">{html.escape(rendered)}</code>'


def _compact_diff_value(current: Any, baseline: Any) -> str:
    if current == baseline:
        return _compact_value(current)
    if isinstance(current, str) and (baseline is MISSING or isinstance(baseline, str)):
        return f'<span class="diff-text">{_text_diff(baseline, current)}</span>'
    if baseline is MISSING:
        return f'<span class="diff-insert"><b>+</b>{_compact_value(current)}</span>'
    return f'<div class="structured-diff"><span class="diff-delete"><b>-</b>{_compact_value(baseline)}</span><span class="diff-insert"><b>+</b>{_compact_value(current)}</span></div>'


def _render_examples_appendix(
    examples: dict[str, Any],
    baseline_examples: dict[str, Any],
) -> str:
    groups = []
    for group_name, cases in examples.items():
        if group_name in {"schema_version", "specification"}:
            continue
        baseline_cases = baseline_examples.get(group_name, [])
        baseline_by_id = _item_map(baseline_cases)
        case_cards = []
        for index, case in enumerate(cases if isinstance(cases, list) else [], start=1):
            case_id = _identity(case)
            case_key = str(case_id[1]) if case_id else f"case-{index}"
            changed = case != baseline_by_id.get(case_key, MISSING)
            baseline_case = baseline_by_id.get(case_key, MISSING)
            fields = "".join(
                f'<div class="example-field"><div class="field-label">{html.escape(_label(key))}</div>'
                f'{_compact_diff_value(value, baseline_case.get(key, MISSING) if isinstance(baseline_case, dict) else MISSING)}</div>'
                for key, value in case.items()
                if key != "id"
            ) if isinstance(case, dict) else _compact_value(case)
            case_cards.append(
                f'<article class="example-case {"diff-added" if baseline_case is MISSING else "diff-modified" if changed else ""}" id="example-{readable_pdf._anchor("case", case_key)}">'
                f'<h4>{html.escape(case_key)}</h4>{fields}</article>'
            )
        removed = _removed_items(cases, baseline_cases)
        removed_cards = "".join(render_removed("Removed example", item, level=4) for item in removed)
        groups.append(
            f'<section class="example-group" id="example-group-{readable_pdf._anchor("group", group_name)}">'
            f'<h3>{html.escape(_label(group_name))}</h3>{"".join(case_cards)}{removed_cards}</section>'
        )
    return (
        f'<section class="approval-appendix" id="approval-examples">'
        f'{readable_pdf._heading(2, "examples", "Complete Examples")}'
        '<p class="appendix-intro">Every example remains present for exact-fingerprint review; groups and cases are compact and independently labeled.</p>'
        f'{"".join(groups)}</section>'
    )


def _render_technical_appendix(contract: dict[str, Any], baseline_contract: dict[str, Any]) -> str:
    requirements = [
        {"id": item.get("id"), "depends_on": item.get("depends_on", [])}
        for item in contract.get("assertions", [])
        if isinstance(item, dict)
    ]
    flows = [
        {"id": item.get("id"), "embed_references": item.get("embed_references", [])}
        for item in contract.get("flows", [])
        if isinstance(item, dict)
    ]
    technical = {
        "schema_version": contract.get("schema_version"),
        "presentation": contract.get("presentation"),
        "model_placements": contract.get("model_placements", []),
        "requirement_dependencies": requirements,
        "flow_embed_references": flows,
        "applies_to": contract.get("applies_to"),
        "examples_declaration": contract.get("examples"),
    }
    baseline_requirements = [
        {"id": item.get("id"), "depends_on": item.get("depends_on", [])}
        for item in baseline_contract.get("assertions", [])
        if isinstance(item, dict)
    ]
    baseline_flows = [
        {"id": item.get("id"), "embed_references": item.get("embed_references", [])}
        for item in baseline_contract.get("flows", [])
        if isinstance(item, dict)
    ]
    baseline = {
        "schema_version": baseline_contract.get("schema_version", MISSING),
        "presentation": baseline_contract.get("presentation", MISSING),
        "model_placements": baseline_contract.get("model_placements", MISSING),
        "requirement_dependencies": baseline_requirements,
        "flow_embed_references": baseline_flows,
        "applies_to": baseline_contract.get("applies_to", MISSING),
        "examples_declaration": baseline_contract.get("examples", MISSING),
    }
    return (
        f'<section class="approval-appendix technical" id="approval-technical">'
        f'{readable_pdf._heading(2, "model", "Technical And Traceability Fields")}'
        '<p class="appendix-intro">These exact fields complete the human presentation without making raw YAML the default reading surface.</p>'
        f'{render_node("Technical fields", technical, baseline, level=3)}</section>'
    )


def _render_removal_appendix(contract: dict[str, Any], baseline_contract: dict[str, Any]) -> str:
    removed_blocks = []
    for field in ("chapters", "flows", "check_obligations", "assertions"):
        removed_blocks.extend(render_removed(f"Removed from {field}", item, level=3) for item in _removed_items(contract.get(field), baseline_contract.get(field)))
    current_models = contract.get("models") if isinstance(contract.get("models"), dict) else {}
    baseline_models = baseline_contract.get("models") if isinstance(baseline_contract.get("models"), dict) else {}
    for model_id, model in baseline_models.items():
        if model_id not in current_models:
            removed_blocks.append(render_removed(f"Removed model {model_id}", model, level=3))
    known_fields = set(contract)
    for field, value in baseline_contract.items():
        if field not in known_fields:
            removed_blocks.append(render_removed(f"Removed field {field}", value, level=3))
    if not removed_blocks:
        return ""
    return (
        f'<section class="approval-appendix removals" id="approval-removals">'
        f'{readable_pdf._heading(2, "edge_case", "Removed Content")}{"".join(removed_blocks)}</section>'
    )


def _annotate_readable_changes(
    document: str,
    contract: dict[str, Any],
    baseline_contract: dict[str, Any],
) -> str:
    mappings = (
        ("chapters", "chapter", "chapter"),
        ("assertions", "card requirement", "requirement"),
        ("flows", "card flow", "flow"),
        ("check_obligations", "card check", "check"),
    )
    for field, css_class, anchor_prefix in mappings:
        current_items = _item_map(contract.get(field))
        baseline_items = _item_map(baseline_contract.get(field))
        for item_id in _changed_item_ids(contract.get(field), baseline_contract.get(field)):
            document = _mark_diff_status(
                document,
                css_class=css_class,
                anchor=readable_pdf._anchor(anchor_prefix, item_id),
                added=item_id not in baseline_items,
            )
            current_item = current_items[item_id]
            baseline_item = baseline_items.get(item_id, MISSING)
            anchor = readable_pdf._anchor(anchor_prefix, item_id)
            title = current_item.get("title")
            if isinstance(title, str):
                old_title = baseline_item.get("title", MISSING) if isinstance(baseline_item, dict) else MISSING
                if field == "chapters":
                    document = _replace_after_anchor(document, anchor, f'<span>{html.escape(_display_text(title))}</span>', f'<span>{_text_diff(old_title, title)}</span>')
                else:
                    document = _replace_after_anchor(document, anchor, f'<h4>{html.escape(_display_text(title))}</h4>', f'<h4>{_text_diff(old_title, title)}</h4>')
            if field == "chapters" and isinstance(current_item.get("summary"), str):
                summary = current_item["summary"]
                old_summary = baseline_item.get("summary", MISSING) if isinstance(baseline_item, dict) else MISSING
                document = _replace_after_anchor(document, anchor, f'<p class="chapter-summary">{html.escape(_display_text(summary))}</p>', f'<p class="chapter-summary diff-text">{_text_diff(old_summary, summary)}</p>')
            elif field == "assertions" and isinstance(current_item.get("must"), str):
                must = current_item["must"]
                old_must = baseline_item.get("must", MISSING) if isinstance(baseline_item, dict) else MISSING
                document = _replace_after_anchor(document, anchor, f'<p>{html.escape(_display_text(must))}</p>', f'<p class="diff-text">{_text_diff(old_must, must)}</p>')
            elif field == "flows" and isinstance(current_item.get("content"), str):
                content = current_item["content"]
                old_content = baseline_item.get("content", MISSING) if isinstance(baseline_item, dict) else MISSING
                current_block = readable_pdf._render_content_block(content)
                document = _replace_after_anchor(document, anchor, f'<div class="flow-narrative">{current_block}</div>', f'<div class="flow-narrative diff-text">{_text_diff(old_content, content)}</div>')
    current_models = contract.get("models") if isinstance(contract.get("models"), dict) else {}
    baseline_models = baseline_contract.get("models") if isinstance(baseline_contract.get("models"), dict) else {}
    for model_id, model in current_models.items():
        if model != baseline_models.get(model_id, MISSING):
            document = _mark_diff_status(document, css_class="card model", anchor=readable_pdf._anchor("model", model_id), added=model_id not in baseline_models)
    for key, css_class, anchor in (("scope", "scope", "scope-and-boundaries"), ("project_surface_catalog", "catalog", "project-surfaces")):
        if contract.get(key) != baseline_contract.get(key, MISSING):
            document = _mark_diff_status(document, css_class=css_class, anchor=anchor, added=key not in baseline_contract)
    for field_name, css_class in (("outcome", "lead"), ("summary", "")):
        current_text = contract.get(field_name)
        if not isinstance(current_text, str):
            continue
        old_text = baseline_contract.get(field_name, MISSING)
        current_class = f' class="{css_class}"' if css_class else ""
        replacement_class = f' class="{css_class} diff-text"' if css_class else ' class="diff-text"'
        current_html = f'<p{current_class}>{html.escape(_display_text(current_text))}</p>'
        replacement = f'<p{replacement_class}>{_text_diff(old_text, current_text)}</p>'
        document = _replace_after_anchor(document, "contract-outcome", current_html, replacement)
    current_versioned_id = f'{contract.get("id")}@{contract.get("version")}'
    baseline_versioned_id = (
        f'{baseline_contract.get("id")}@{baseline_contract.get("version")}'
        if baseline_contract.get("id") and baseline_contract.get("version")
        else MISSING
    )
    document = document.replace(
        f'<span class="pill">{html.escape(current_versioned_id)}</span>',
        f'<span class="pill diff-text">{_text_diff(baseline_versioned_id, current_versioned_id)}</span>',
        1,
    )
    current_status = contract.get("status")
    if isinstance(current_status, str):
        baseline_status = baseline_contract.get("status", MISSING)
        old_status = readable_pdf._label(baseline_status) if baseline_status is not MISSING else MISSING
        current_label = readable_pdf._label(current_status)
        document = document.replace(
            f'<span class="pill">{html.escape(current_label)}</span>',
            f'<span class="pill diff-text">{_text_diff(old_status, current_label)}</span>',
            1,
        )
    return document


def build_html(
    bundle: specifications.SpecificationBundle,
    *,
    baseline_contract: dict[str, Any] | None,
    baseline_examples: dict[str, Any] | None,
    baseline_ref: str,
) -> str:
    baseline_contract = baseline_contract or {}
    baseline_examples = baseline_examples or {}
    if not isinstance(bundle.specification.get("presentation"), dict):
        return build_legacy_html(
            bundle,
            baseline_contract=baseline_contract,
            baseline_examples=baseline_examples,
            baseline_ref=baseline_ref,
        )

    document = readable_pdf.build_html(bundle)
    document = _annotate_readable_changes(document, bundle.specification, baseline_contract)
    change_summary = _change_summary(bundle, baseline_contract, baseline_examples, baseline_ref)
    document = document.replace('<section class="legend" id="legend">', change_summary + '<section class="legend" id="legend">', 1)
    appendices = (
        _render_examples_appendix(bundle.examples, baseline_examples)
        + _render_technical_appendix(bundle.specification, baseline_contract)
        + _render_removal_appendix(bundle.specification, baseline_contract)
    )
    document = document.replace(
        '<p class="footer-note">This is a readable Specification presentation, not an approval receipt. Exact approval must use the highlighted approval PDF and matching review artifact.</p>',
        appendices
        + '<p class="footer-note">Approval must match the exact fingerprint printed on page one. Any later Specification or example edit requires a new PDF and approval.</p>',
        1,
    )
    navigation_additions = (
        f'<a class="utility-link" href="#change-summary">{readable_pdf._icon("history")}<span>Change summary</span></a>'
        f'<a class="utility-link" href="#approval-examples">{readable_pdf._icon("examples")}<span>Complete examples</span></a>'
        f'<a class="utility-link" href="#approval-technical">{readable_pdf._icon("model")}<span>Technical fields</span></a>'
    )
    document = document.replace('<div class="utility-links">', f'<div class="utility-links">{navigation_additions}', 1)
    approval_css = """
.diff-added { border-color: #239b56 !important; }
.diff-modified { border-left-color: #4b7bec !important; }
.diff-insert { background: #e6f7ec; color: #176b3b; text-decoration: none; }
.diff-delete { background: #fdebec; color: #a52a32; text-decoration: line-through; }
.diff-insert, .diff-delete { border-radius: 1mm; display: inline; margin: 0 .35mm; padding: .2mm .65mm; }
.diff-insert b, .diff-delete b { margin-right: .6mm; text-decoration: none; }
.diff-text { white-space: normal; }
.change-summary { margin-top: 2mm; }
.change-summary > p { font-size: 7.6pt; margin: .8mm 0 1.4mm; }
.change-grid { display: grid; gap: 1mm; grid-template-columns: repeat(5, 1fr); }
.change-count { align-items: center; background: #f4f7fa; border: 1px solid #d3dee8; border-radius: 2mm; display: flex; font-size: 7pt; gap: 1mm; padding: 1mm; }
.change-count strong { display: block; font-size: 11pt; line-height: 1; }
.approval-appendix { break-before: page; }
.appendix-intro { color: #52616f; }
.example-group { border-top: 1px solid #cbd5df; margin-top: 4mm; padding-top: 2mm; }
.example-case { border: 1px solid #d8e1ea; border-radius: 2mm; break-inside: avoid; margin: 1.5mm 0; padding: 2mm; }
.example-field { display: grid; gap: 2mm; grid-template-columns: 30mm 1fr; margin: .8mm 0; }
.compact-json { display: block; overflow-wrap: anywhere; white-space: normal; }
.node { margin: 2mm 0; }
.node.mapping > .node, .node.sequence > ol { margin-left: 3mm; }
.field { border-left: 2px solid #d9e1e8; break-inside: avoid; margin: 1mm 0; padding: 1.5mm 2mm; }
.structured-diff { display: grid; gap: 1mm; }
.removed { background: #fdebec; border: 1px dashed #c84951; border-radius: 2mm; padding: 2mm; }
.removed-label { color: #a52a32; font-size: 8pt; text-transform: uppercase; }
pre { font: 8pt/1.35 "Courier New", monospace; margin: 1mm 0; overflow-wrap: anywhere; white-space: pre-wrap; }
"""
    return document.replace("</style>", approval_css + "</style>", 1)


def _baseline_commit(repo_root: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError(f"Baseline ref does not resolve to a commit: {ref}")
    return result.stdout.strip()


def _git_yaml(repo_root: Path, ref: str, path: Path, *, allow_missing: bool) -> dict[str, Any] | None:
    relative = path.resolve().relative_to(repo_root.resolve())
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative.as_posix()}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        if allow_missing:
            return None
        raise ValueError(f"Baseline file is missing at {ref}:{relative.as_posix()}; use --new-specification only for a new bundle")
    value = yaml.safe_load(result.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"Baseline file must contain a mapping: {ref}:{relative.as_posix()}")
    return value


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


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "specification"


def _examples_path(bundle: specifications.SpecificationBundle, specification: dict[str, Any] | None = None) -> Path:
    examples = (specification or bundle.specification).get("examples")
    filename = examples.get("file") if isinstance(examples, dict) else None
    if not isinstance(filename, str) or not filename:
        raise ValueError("Specification examples.file must identify the examples document")
    return bundle.path / filename


def write_review_artifact(
    path: Path,
    *,
    bundle: specifications.SpecificationBundle,
    pdf: Path,
    baseline_ref: str,
    baseline_commit: str,
    publication: dict[str, Any] | None,
    approval_eligible: bool,
) -> dict[str, Any]:
    pdf_sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    artifact = {
        "schema_version": 1,
        "specification": bundle.versioned_id,
        "fingerprint": bundle.fingerprint,
        "baseline_ref": baseline_ref,
        "baseline_commit": baseline_commit,
        "pdf": str(pdf.resolve()),
        "pdf_sha256": pdf_sha256,
        "highlight_policy": {
            "additions": "inline_green_plus",
            "removals": "inline_red_minus",
            "unchanged": "neutral",
            "granularity": "changed_text_only",
        },
        "approval_eligible": approval_eligible,
    }
    if publication is not None:
        artifact["publication"] = {
            "bucket": publication.get("bucket"),
            "key": publication.get("key"),
            "sha256": publication.get("sha256"),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render and privately upload an inline-diff Specification approval PDF")
    parser.add_argument("bundle", help="Specification bundle directory or specification.yml path")
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF, help="Git ref used to highlight changes")
    parser.add_argument("--output", type=Path, help="PDF output path; defaults under /tmp/opencode/specification-approvals")
    parser.add_argument("--preview-output", type=Path, help="Optional first-page PNG used for deterministic visual inspection")
    parser.add_argument("--preview-anchor", default="", help="Render one element id instead of page one when --preview-output is set")
    parser.add_argument("--container", default=opencode_response_media.DEFAULT_CONTAINER, help="API container used for S3 upload")
    parser.add_argument("--new-specification", action="store_true", help="Allow Specification files to be absent from the baseline commit")
    parser.add_argument("--no-upload", action="store_true", help="Generate the PDF without uploading it")
    parser.add_argument("--dry-run-upload", action="store_true", help="Generate a fake upload result without Docker or S3")
    parser.add_argument("--json", action="store_true", help="Print the complete result as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        bundle = specifications.validate_bundle(specifications._resolve_specification_path(args.bundle))
        output = args.output or DEFAULT_OUTPUT_ROOT / f"{_safe_name(bundle.specification_id)}-{bundle.fingerprint[:16]}.pdf"
        baseline_commit = _baseline_commit(specifications.REPO_ROOT, args.baseline_ref)
        baseline_contract = _git_yaml(
            specifications.REPO_ROOT,
            args.baseline_ref,
            bundle.path / "specification.yml",
            allow_missing=args.new_specification,
        )
        baseline_examples = _git_yaml(
            specifications.REPO_ROOT,
            args.baseline_ref,
            _examples_path(bundle, baseline_contract if baseline_contract is not None else None),
            allow_missing=args.new_specification,
        )
        document = build_html(
            bundle,
            baseline_contract=baseline_contract,
            baseline_examples=baseline_examples,
            baseline_ref=args.baseline_ref,
        )
        render_pdf(document, output)
        if args.preview_output:
            readable_pdf.render_preview(document, args.preview_output, anchor=args.preview_anchor)
        result: dict[str, Any] = {
            "baseline_ref": args.baseline_ref,
            "baseline_commit": baseline_commit,
            "specification": bundle.versioned_id,
            "fingerprint": bundle.fingerprint,
            "pdf": str(output.resolve()),
            **({"preview": str(args.preview_output.resolve())} if args.preview_output else {}),
        }
        publication = None
        if not args.no_upload:
            publication = opencode_response_media.upload_file(
                output,
                alt=f"Read {bundle.versioned_id} Specification approval PDF",
                container=args.container,
                dry_run=args.dry_run_upload,
            )
            result["publication"] = publication
        review_artifact_path = output.with_suffix(".approval.json")
        write_review_artifact(
            review_artifact_path,
            bundle=bundle,
            pdf=output,
            baseline_ref=args.baseline_ref,
            baseline_commit=baseline_commit,
            publication=publication,
            approval_eligible=publication is not None and not args.dry_run_upload,
        )
        result["review_artifact"] = str(review_artifact_path.resolve())
    except Exception as exc:
        print(f"specification_approval_pdf: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Specification: {result['specification']}")
        print(f"Fingerprint: {result['fingerprint']}")
        print(f"PDF: {result['pdf']}")
        print(f"Review artifact: {result['review_artifact']}")
        publication = result.get("publication")
        if isinstance(publication, dict):
            print("\nMarkdown:")
            print(publication["snippets"]["markdown"])
            print("\nHTML:")
            print(publication["snippets"]["html"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
