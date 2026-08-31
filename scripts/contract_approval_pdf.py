#!/usr/bin/env python3
"""Render and privately publish an exact-fingerprint Contract approval PDF.

The document contains the full contract and examples in a readable hierarchy.
Values changed from the selected Git baseline are highlighted in yellow, while
removed values remain visible as highlighted removal blocks. The resulting PDF
is uploaded through the existing 48-hour OpenCode response-media path by default.
"""

from __future__ import annotations

import argparse
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

from scripts import contracts  # noqa: E402
from scripts import opencode_response_media  # noqa: E402
from scripts.playwright_visual_smoke import launch_browser  # noqa: E402


DEFAULT_BASELINE_REF = "HEAD"
DEFAULT_OUTPUT_ROOT = Path("/tmp/opencode/contract-approvals")
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
        section_class = _classes("node", "mapping", "changed" if new_value else "")
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
        section_class = _classes("node", "sequence", "changed" if changed else "")
        empty = '<div class="value empty">None</div>' if not items else ""
        return f'<section class="{section_class}"><h{heading_level}>{title}</h{heading_level}>{empty}<ol>{"".join(items)}</ol></section>'

    field_class = _classes("field", "changed" if changed else "", "new" if new_value else "")
    return f'<div class="{field_class}"><div class="field-label">{title}</div>{_scalar(current)}</div>'


def render_removed(key: str, value: Any, *, level: int) -> str:
    heading_level = min(level, 6)
    title = html.escape(_label(key))
    rendered = html.escape(_display_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).strip()))
    return (
        f'<section class="node removed changed"><h{heading_level}>{title} <span class="removed-label">Removed</span></h{heading_level}>'
        f'<pre>{rendered}</pre></section>'
    )


def build_html(
    bundle: contracts.ContractBundle,
    *,
    baseline_contract: dict[str, Any] | None,
    baseline_examples: dict[str, Any] | None,
    baseline_ref: str,
) -> str:
    baseline_contract = baseline_contract or {}
    baseline_examples = baseline_examples or {}
    title = html.escape(str(bundle.contract.get("title") or bundle.contract_id))
    fingerprint = html.escape(bundle.fingerprint)
    versioned_id = html.escape(bundle.versioned_id)
    baseline = html.escape(baseline_ref)
    contract_body = render_node("Contract", bundle.contract, baseline_contract, level=2)
    examples_body = render_node("Examples", bundle.examples, baseline_examples, level=2)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} Contract approval</title>
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
.changed {{ background: #fff2a8; border-color: #e2c94f; border-radius: 2mm; padding: 2.5mm 3mm; }}
.mapping.changed, .sequence.changed {{ border: 1px solid #e2c94f; }}
.value {{ overflow-wrap: anywhere; white-space: normal; }}
.value.badge {{ background: #dbeafe; border-radius: 99px; display: inline-block; font-weight: 700; padding: 0 2mm; }}
.value.empty {{ color: #71808f; font-style: italic; }}
.removed {{ border: 1px dashed #aa6b00; }}
.removed-label {{ color: #8a4b00; font-size: 8pt; text-transform: uppercase; }}
ol {{ margin: 1mm 0 2mm 5mm; padding-left: 5mm; }}
li {{ margin: 1mm 0; padding-left: 1mm; }}
pre {{ font: 8pt/1.35 "Courier New", monospace; margin: 1mm 0; overflow-wrap: anywhere; white-space: pre-wrap; }}
.footer-note {{ color: #52616f; font-size: 8.5pt; margin-top: 10mm; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">
  <div class="meta-row"><div class="meta-label">Contract</div><div>{versioned_id}</div></div>
  <div class="meta-row"><div class="meta-label">Status</div><div>{html.escape(bundle.status)}</div></div>
  <div class="meta-row"><div class="meta-label">Fingerprint</div><div class="fingerprint">{fingerprint}</div></div>
  <div class="meta-row"><div class="meta-label">Compared with</div><div>{baseline}</div></div>
</div>
<div class="legend"><span class="swatch"></span><span>Yellow marks content added or modified since {baseline}. Removed content remains visible in highlighted removal blocks.</span></div>
{contract_body}
{examples_body}
<p class="footer-note">Approval must match the exact fingerprint printed above. Any later Contract or example edit requires a new PDF and approval.</p>
</body>
</html>"""


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
        raise ValueError(f"Baseline file is missing at {ref}:{relative.as_posix()}; use --new-contract only for a new bundle")
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
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "contract"


def _examples_path(bundle: contracts.ContractBundle, contract: dict[str, Any] | None = None) -> Path:
    examples = (contract or bundle.contract).get("examples")
    filename = examples.get("file") if isinstance(examples, dict) else None
    if not isinstance(filename, str) or not filename:
        raise ValueError("Contract examples.file must identify the examples document")
    return bundle.path / filename


def write_review_artifact(
    path: Path,
    *,
    bundle: contracts.ContractBundle,
    pdf: Path,
    baseline_ref: str,
    baseline_commit: str,
    publication: dict[str, Any] | None,
    approval_eligible: bool,
) -> dict[str, Any]:
    pdf_sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    artifact = {
        "schema_version": 1,
        "contract": bundle.versioned_id,
        "fingerprint": bundle.fingerprint,
        "baseline_ref": baseline_ref,
        "baseline_commit": baseline_commit,
        "pdf": str(pdf.resolve()),
        "pdf_sha256": pdf_sha256,
        "highlight_policy": {
            "additions_and_modifications": "yellow_background",
            "removals": "yellow_removal_block",
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
    parser = argparse.ArgumentParser(description="Render and privately upload a highlighted Contract approval PDF")
    parser.add_argument("bundle", help="Contract bundle directory or contract.yml path")
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF, help="Git ref used to highlight changes")
    parser.add_argument("--output", type=Path, help="PDF output path; defaults under /tmp/opencode/contract-approvals")
    parser.add_argument("--container", default=opencode_response_media.DEFAULT_CONTAINER, help="API container used for S3 upload")
    parser.add_argument("--new-contract", action="store_true", help="Allow contract files to be absent from the baseline commit")
    parser.add_argument("--no-upload", action="store_true", help="Generate the PDF without uploading it")
    parser.add_argument("--dry-run-upload", action="store_true", help="Generate a fake upload result without Docker or S3")
    parser.add_argument("--json", action="store_true", help="Print the complete result as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        bundle = contracts.validate_bundle(contracts._resolve(args.bundle))
        output = args.output or DEFAULT_OUTPUT_ROOT / f"{_safe_name(bundle.contract_id)}-{bundle.fingerprint[:16]}.pdf"
        baseline_commit = _baseline_commit(contracts.REPO_ROOT, args.baseline_ref)
        baseline_contract = _git_yaml(
            contracts.REPO_ROOT,
            args.baseline_ref,
            bundle.path / "contract.yml",
            allow_missing=args.new_contract,
        )
        baseline_examples = _git_yaml(
            contracts.REPO_ROOT,
            args.baseline_ref,
            _examples_path(bundle, baseline_contract if baseline_contract is not None else None),
            allow_missing=args.new_contract,
        )
        document = build_html(
            bundle,
            baseline_contract=baseline_contract,
            baseline_examples=baseline_examples,
            baseline_ref=args.baseline_ref,
        )
        render_pdf(document, output)
        result: dict[str, Any] = {
            "baseline_ref": args.baseline_ref,
            "baseline_commit": baseline_commit,
            "contract": bundle.versioned_id,
            "fingerprint": bundle.fingerprint,
            "pdf": str(output.resolve()),
        }
        publication = None
        if not args.no_upload:
            publication = opencode_response_media.upload_file(
                output,
                alt=f"Read {bundle.versioned_id} Contract approval PDF",
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
        print(f"contract_approval_pdf: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Contract: {result['contract']}")
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
