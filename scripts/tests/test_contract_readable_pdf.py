#!/usr/bin/env python3
"""Tests for readable Contract presentation PDFs.

These tests keep the human-facing Contract renderer deterministic without
launching Chromium or contacting Docker, Vault, or S3. The approval path remains
covered by test_contract_approval_pdf.py; this suite verifies only the separate
chaptered presentation used to show a Contract as a Project document.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from scripts import contract_readable_pdf as readable_pdf
from scripts import contracts


def bundle(tmp_path: Path) -> contracts.ContractBundle:
    contract = {
        "schema_version": 1,
        "id": "feature.example",
        "version": 2,
        "status": "draft",
        "title": "Example",
        "summary": "Example summary.",
        "outcome": "Example outcome for readers.",
        "presentation": {
            "document_kind": "capability_contract",
            "chapter_order": ["first", "second"],
            "generated_indexes": ["requirements", "user_flows", "edge_cases", "models", "checks", "examples", "history"],
            "legend": {"requirement": "Durable truth.", "check": "Reusable proof."},
        },
        "project_surface_catalog": {
            "home_project_id": "openmates",
            "revision_id": "surfaces-v1",
            "surfaces": [
                {"id": "rest_api", "label": "REST API", "kind": "api", "status": "active"},
                {"id": "web", "label": "Web", "kind": "web", "status": "active"},
                {"id": "apple", "label": "Apple", "kind": "native", "status": "deferred"},
            ],
        },
        "scope": {"includes": ["Included behavior"], "excludes": ["Excluded behavior"]},
        "chapters": [
            {
                "id": "second",
                "title": "Second Chapter",
                "summary": "Rendered after First Chapter.",
                "requirement_ids": [],
                "user_flow_ids": [],
                "edge_case_ids": [],
                "model_ids": [],
            },
            {
                "id": "first",
                "title": "First Chapter",
                "summary": "Primary capability chapter.",
                "requirement_ids": ["example.requirement"],
                "user_flow_ids": ["create-example"],
                "edge_case_ids": ["example-edge"],
                "model_ids": ["ExampleModel"],
            },
        ],
        "flows": [
            {
                "id": "create-example",
                "kind": "user_flow",
                "title": "Create example",
                "chapter_id": "first",
                "requirement_ids": ["example.requirement"],
                "surface_ids": ["rest_api", "web"],
                "content": "1. Start.\n2. Finish.",
                "embed_references": [],
                "check_obligation_ids": ["check.example"],
            },
            {
                "id": "example-edge",
                "kind": "edge_case",
                "parent_flow_id": "create-example",
                "title": "Example edge case",
                "chapter_id": "first",
                "requirement_ids": ["example.requirement"],
                "surface_ids": ["rest_api"],
                "content": "Fail visibly and preserve state.",
                "embed_references": [],
                "check_obligation_ids": ["check.example"],
            },
        ],
        "model_placements": [{"model_id": "ExampleModel", "chapter_ids": ["first"]}],
        "check_obligations": [
            {
                "id": "check.example",
                "title": "Example check",
                "materialization": "pending",
                "covers": ["example.requirement", "create-example"],
                "sources": [{"kind": "integration", "role": "required", "surface": "rest_api", "path": "tests/test_example.py"}],
            }
        ],
        "models": {
            "ExampleModel": {
                "example_id": {"type": "stable_id", "required": True},
                "optional_note": {"type": "string", "nullable": True, "constraints": {"plaintext_private_content": "forbidden"}},
            }
        },
        "assertions": [
            {
                "id": "example.requirement",
                "title": "Example requirement",
                "chapter_id": "first",
                "type": "behavior",
                "importance": "required",
                "project_surface_ids": ["rest_api", "web", "apple"],
                "check_obligation_ids": ["check.example"],
                "must": "Do required behavior.",
                "depends_on": ["models.ExampleModel", "examples.example_group"],
            }
        ],
        "surfaces": {
            "rest_api": {"required": True},
            "cli": {"required": False},
            "sdks": {"required": False, "implementations": {"npm": {"required": False}, "pip": {"required": False}}},
            "gui": {"required": True, "implementations": {"web": {"required": True}, "apple": {"required": False}}, "exceptions": []},
        },
        "examples": {"file": "examples.yml", "required_groups": ["example_group", "contract_structure"]},
    }
    examples = {
        "schema_version": 1,
        "contract": "feature.example@2",
        "example_group": [{"id": "case-one", "expect": {"visible": True}}],
        "contract_structure": [{"id": "chaptered-contract", "expect": {"raw_yaml_default": False}}],
    }
    return contracts.ContractBundle(
        path=tmp_path,
        contract_id="feature.example",
        version=2,
        status="draft",
        contract=contract,
        examples=examples,
        fingerprint="b" * 64,
    )


# contract-test: tooling
def test_html_renders_chaptered_contract_presentation(tmp_path: Path) -> None:
    document = readable_pdf.build_html(bundle(tmp_path))

    assert "Example outcome for readers." in document
    assert "Scope And Boundaries" in document
    assert document.index("First Chapter") < document.index("Second Chapter")
    assert "Example requirement" in document
    assert "Do required behavior." in document
    assert "Create example" in document
    assert "<ol><li>Start.</li><li>Finish.</li></ol>" in document
    assert "Example edge case" in document
    assert "Parent flow" in document
    assert "ExampleModel" in document
    assert "Example check" in document
    assert "Apple (deferred)" in document
    assert "Generated Indexes" in document
    assert "case-one" in document
    assert "schema_version:" not in document
    assert 'class="front-page"' in document
    assert document.index('id="legend"') < document.index('id="project-surfaces"')
    assert 'href="#chapter-first"' in document
    assert 'href="#index-requirements"' in document
    assert "Open index" in document
    assert '<svg class="icon"' in document
    assert '<svg class="card-icon"' in document
    assert document.count('class="flow-wireframe"') == 2
    assert ".flow-wireframe { margin: 0; width: 58mm; }" in document
    assert "height: 39mm" in document
    assert "User flow wireframe" in document
    assert "Edge case wireframe" in document


# contract-test: tooling
def test_missing_presentation_metadata_fails_closed(tmp_path: Path) -> None:
    current = bundle(tmp_path)
    current.contract.pop("presentation")

    try:
        readable_pdf.build_html(current)
    except readable_pdf.ReadableContractError as exc:
        assert "presentation" in str(exc)
    else:
        raise AssertionError("missing presentation metadata should fail")


# contract-test: tooling
def test_main_renders_and_publishes_readable_pdf(tmp_path: Path, monkeypatch, capsys) -> None:
    current = bundle(tmp_path)
    output = tmp_path / "readable.pdf"
    rendered: list[str] = []
    published: list[Path] = []

    monkeypatch.setattr(readable_pdf.contracts, "validate_bundle", lambda _path: current)
    monkeypatch.setattr(readable_pdf.contracts, "_resolve", lambda path: Path(path))
    monkeypatch.setattr(readable_pdf, "render_pdf", lambda document, path: (rendered.append(document), path.write_bytes(b"%PDF")))

    def upload(path: Path, **_kwargs):
        published.append(path)
        return {"bucket": "private-bucket", "key": "readable.pdf", "sha256": "sha256:" + "c" * 64, "snippets": {"markdown": "[Read PDF](https://example.invalid/readable.pdf)", "html": "<a>Read PDF</a>"}}

    monkeypatch.setattr(readable_pdf.opencode_response_media, "upload_file", upload)

    code = readable_pdf.main([str(tmp_path), "--output", str(output)])

    assert code == 0
    assert rendered and "First Chapter" in rendered[0]
    assert published == [output]
    stdout = capsys.readouterr().out
    assert current.versioned_id in stdout
    assert current.fingerprint in stdout
    assert "[Read PDF]" in stdout


# contract-test: tooling
def test_documented_cli_entry_point_loads_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/contract_readable_pdf.py", "--help"],
        cwd=readable_pdf.contracts.REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "readable Contract presentation PDF" in result.stdout
