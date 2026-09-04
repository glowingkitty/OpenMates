"""Tests for incremental Playwright proof-video metadata auditing.

The audit is designed for hooks: it checks only files passed by the caller and
allows explicit not-required classifications so legacy specs can be backfilled
gradually without blocking unrelated work.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_audit_module():
    path = ROOT / "scripts" / "audit_playwright_proof_metadata.py"
    spec = importlib.util.spec_from_file_location("audit_playwright_proof_metadata", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_spec(tmp_path: Path, relative: str, content: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_proof_metadata_is_reported(tmp_path: Path, monkeypatch) -> None:
    audit = load_audit_module()
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    path = write_spec(tmp_path, "frontend/apps/web_app/tests/chat-flow.spec.ts", "test('chat', async () => {});\n")

    problems = audit.audit_path(path)

    assert len(problems) == 1
    assert "missing defineVideoProof" in problems[0]
    assert "proof-video: not_required" in problems[0]


def test_explicit_not_required_classification_passes(tmp_path: Path, monkeypatch) -> None:
    audit = load_audit_module()
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    path = write_spec(
        tmp_path,
        "frontend/apps/web_app/tests/setup.spec.ts",
        "// proof-video: not_required reason=non_visual_setup\ntest('setup', async () => {});\n",
    )

    assert audit.audit_path(path) == []


def test_account_health_not_required_classification_passes(tmp_path: Path, monkeypatch) -> None:
    audit = load_audit_module()
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    path = write_spec(
        tmp_path,
        "frontend/apps/web_app/tests/test-account-preflight.spec.ts",
        "// proof-video: not_required reason=account_health\ntest('account preflight', async () => {});\n",
    )

    assert audit.audit_path(path) == []


def test_invalid_classification_reason_is_reported(tmp_path: Path, monkeypatch) -> None:
    audit = load_audit_module()
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    path = write_spec(
        tmp_path,
        "frontend/apps/web_app/tests/setup.spec.ts",
        "// proof-video: not_required reason=whatever\ntest('setup', async () => {});\n",
    )

    problems = audit.audit_path(path)

    assert len(problems) == 1
    assert "invalid proof-video not_required reason=whatever" in problems[0]


def test_define_video_proof_with_required_fields_passes(tmp_path: Path, monkeypatch) -> None:
    audit = load_audit_module()
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    path = write_spec(
        tmp_path,
        "frontend/apps/web_app/tests/proof.spec.ts",
        """
const {createVideoProofRuntime, defineVideoProof} = require('./helpers/video-proof');
const proof = defineVideoProof({
  id: 'proof',
  title: 'Proof',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [{id: 'ready', text: 'Ready.', checkpoint: 'ready', devices: ['web-laptop']}],
  assertions: [{id: 'ready.visible', checkpoint: 'ready', visual: 'Ready state is visible.', devices: ['web-laptop']}],
  tutorial: {readingWordsPerSecond: 2.2, minimumHoldMs: 1000, maximumHoldMs: 5000}
});
createVideoProofRuntime(proof, options);
""",
    )

    assert audit.audit_path(path) == []


def test_non_playwright_spec_path_is_ignored(tmp_path: Path, monkeypatch) -> None:
    audit = load_audit_module()
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    path = write_spec(tmp_path, "frontend/packages/ui/src/example.spec.ts", "test('unit', () => {});\n")

    assert audit.audit_path(path) == []
