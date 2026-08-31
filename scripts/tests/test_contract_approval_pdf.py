#!/usr/bin/env python3
"""Tests for readable, exact-fingerprint Contract approval PDFs.

The tests exercise recursive change highlighting, removal visibility, output
naming, and response-media publication without launching Chromium or contacting
Docker, Vault, or S3. The renderer remains a deterministic tooling surface.
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

from PIL import Image
import pytest

from scripts import contract_approval_pdf as approval_pdf
from scripts import contracts


def bundle(tmp_path: Path) -> contracts.ContractBundle:
    return contracts.ContractBundle(
        path=tmp_path,
        contract_id="feature.example",
        version=1,
        status="draft",
        contract={
            "id": "feature.example",
            "title": "Example",
            "summary": "Updated summary",
            "examples": {"file": "examples.yml"},
            "assertions": [
                {"id": "example.existing", "must": "Existing truth"},
                {"id": "example.new", "must": "New truth"},
            ],
        },
        examples={"contract": "feature.example@1", "cases": [{"id": "new-case", "expect": "visible"}]},
        fingerprint="a" * 64,
    )


# contract-test: tooling
def test_html_highlights_changes_and_keeps_removals_visible(tmp_path: Path) -> None:
    current = bundle(tmp_path)
    current.contract["summary"] = "Updated\u2011summary"
    document = approval_pdf.build_html(
        current,
        baseline_contract={
            "id": "feature.example",
            "title": "Example",
            "summary": "Old summary",
            "legacy_rule": "Must remain visible as removed",
            "assertions": [{"id": "example.existing", "must": "Existing truth"}],
        },
        baseline_examples={"contract": "feature.example@1", "cases": []},
        baseline_ref="HEAD",
    )

    assert "Updated-summary" in document
    assert "\u2011" not in document
    assert 'class="field changed"' in document
    assert "New truth" in document
    assert "Must remain visible as removed" in document
    assert "Removed" in document
    assert current.fingerprint in document
    assert "Yellow marks content added or modified" in document


# contract-test: tooling
def test_scalar_list_deletion_retains_the_removed_value() -> None:
    document = approval_pdf.render_node("Values", ["A", "C"], ["A", "B", "C"])

    assert "Removed item" in document
    assert "<pre>B\n...</pre>" in document
    assert "Removed" in document
    assert document.count(">C<") == 1


# contract-test: tooling
def test_scalar_list_matching_consumes_duplicate_occurrences() -> None:
    matches, removed = approval_pdf._match_list_items(["B", "B"], ["A", "B"])

    assert matches[0] == "B"
    assert matches[1] is approval_pdf.MISSING
    assert removed == ["A"]


# contract-test: tooling
def test_uses_the_contract_selected_examples_filename(tmp_path: Path) -> None:
    current = bundle(tmp_path)
    current.contract["examples"] = {"file": "contract-examples.yml"}

    assert approval_pdf._examples_path(current) == tmp_path / "contract-examples.yml"


# contract-test: tooling
def test_examples_rename_resolves_the_baseline_filename(tmp_path: Path) -> None:
    current = bundle(tmp_path)
    current.contract["examples"] = {"file": "renamed-examples.yml"}
    baseline_contract = {"examples": {"file": "examples.yml"}}

    assert approval_pdf._examples_path(current, baseline_contract) == tmp_path / "examples.yml"


# contract-test: tooling
def test_dry_run_upload_writes_an_ineligible_review_artifact(tmp_path: Path, monkeypatch) -> None:
    current = bundle(tmp_path)
    output = tmp_path / "approval.pdf"

    monkeypatch.setattr(approval_pdf.contracts, "validate_bundle", lambda _path: current)
    monkeypatch.setattr(approval_pdf.contracts, "_resolve", lambda path: Path(path))
    monkeypatch.setattr(approval_pdf, "_baseline_commit", lambda *_args: "b" * 40)
    monkeypatch.setattr(approval_pdf, "_git_yaml", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(approval_pdf, "render_pdf", lambda _document, path: path.write_bytes(b"%PDF"))

    def upload(path: Path, **_kwargs):
        digest = approval_pdf.hashlib.sha256(path.read_bytes()).hexdigest()
        return {"bucket": "private-bucket", "key": "contract.pdf", "sha256": f"sha256:{digest}", "snippets": {"markdown": "", "html": ""}}

    monkeypatch.setattr(approval_pdf.opencode_response_media, "upload_file", upload)

    assert approval_pdf.main([str(tmp_path), "--output", str(output), "--dry-run-upload"]) == 0
    artifact = approval_pdf.json.loads(output.with_suffix(".approval.json").read_text(encoding="utf-8"))
    assert artifact["approval_eligible"] is False


# contract-test: tooling
def test_main_renders_and_publishes_exact_fingerprint(tmp_path: Path, monkeypatch, capsys) -> None:
    current = bundle(tmp_path)
    output = tmp_path / "approval.pdf"
    rendered: list[str] = []
    published: list[Path] = []

    monkeypatch.setattr(approval_pdf.contracts, "validate_bundle", lambda _path: current)
    monkeypatch.setattr(approval_pdf.contracts, "_resolve", lambda path: Path(path))
    monkeypatch.setattr(approval_pdf, "_baseline_commit", lambda *_args: "b" * 40)
    monkeypatch.setattr(approval_pdf, "_git_yaml", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(approval_pdf, "render_pdf", lambda document, path: (rendered.append(document), path.write_bytes(b"%PDF")))

    def upload(path: Path, **_kwargs):
        published.append(path)
        digest = approval_pdf.hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "bucket": "private-bucket",
            "key": "contract.pdf",
            "sha256": f"sha256:{digest}",
            "snippets": {"markdown": "[Read PDF](https://example.invalid/contract.pdf)", "html": "<a>Read PDF</a>"},
        }

    monkeypatch.setattr(approval_pdf.opencode_response_media, "upload_file", upload)

    code = approval_pdf.main([str(tmp_path), "--output", str(output)])

    assert code == 0
    assert rendered and current.fingerprint in rendered[0]
    assert published == [output]
    artifact = approval_pdf.json.loads(output.with_suffix(".approval.json").read_text(encoding="utf-8"))
    assert artifact["approval_eligible"] is True
    stdout = capsys.readouterr().out
    assert current.versioned_id in stdout
    assert current.fingerprint in stdout
    assert "[Read PDF]" in stdout
    assert "Review artifact:" in stdout
    assert output.with_suffix(".approval.json").is_file()


# contract-test: tooling
def test_documented_cli_entry_point_loads_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/contract_approval_pdf.py", "--help"],
        cwd=approval_pdf.REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "highlighted Contract approval PDF" in result.stdout


# contract-test: tooling
def test_invalid_baseline_ref_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not resolve"):
        approval_pdf._baseline_commit(tmp_path, "missing-ref")


# contract-test: tooling
def test_real_chromium_render_contains_yellow_changes(tmp_path: Path) -> None:
    current = bundle(tmp_path)
    document = approval_pdf.build_html(
        current,
        baseline_contract={"id": "feature.example", "title": "Example", "summary": "Old"},
        baseline_examples={"contract": "feature.example@1"},
        baseline_ref="HEAD",
    )
    screenshot = tmp_path / "approval.png"
    pdf = tmp_path / "approval.pdf"
    try:
        playwright, browser = approval_pdf.launch_browser()
    except RuntimeError as exc:
        if os.environ.get("CONTRACT_PDF_RENDER_REQUIRED") == "1":
            raise
        pytest.skip(str(exc))
    try:
        page = browser.new_page()
        page.set_content(document, wait_until="load")
        page.screenshot(path=str(screenshot), full_page=True)
    finally:
        browser.close()
        playwright.stop()
    approval_pdf.render_pdf(document, pdf)

    image = Image.open(screenshot).convert("RGB")
    yellow_pixels = sum(1 for pixel in image.get_flattened_data() if pixel == (255, 242, 168))
    assert yellow_pixels > 1000
    assert pdf.read_bytes().startswith(b"%PDF")
    assert pdf.stat().st_size > 1000
