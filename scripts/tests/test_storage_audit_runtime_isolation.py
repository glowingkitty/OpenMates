#!/usr/bin/env python3
# contract-test-file: tooling
"""Regression coverage for nightly storage-audit runtime isolation.

Nightly tests may derive review candidates from browser evidence, but they must
not rewrite tracked files in the managed Docker checkout. Incomplete evidence
also retains prior observations instead of silently pruning the inventory.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import yaml

from scripts import merge_storage_audits
from scripts import run_tests
from scripts import sessions


def test_candidate_merge_retains_prior_entries_and_preserves_tracked_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshots = tmp_path / "test-results" / "storage-audits"
    snapshots.mkdir(parents=True)
    cookies_source = tmp_path / "docs" / "cookies.yml"
    storage_source = tmp_path / "docs" / "browser-storage.yml"
    cookies_source.parent.mkdir(parents=True)
    cookies_source.write_text(
        yaml.safe_dump({"cookies": [{"name": "prior", "domain": "", "path": "/"}]}),
        encoding="utf-8",
    )
    storage_source.write_text(
        yaml.safe_dump(
            {
                "local_storage": [{"key": "prior-key"}],
                "session_storage": [],
                "indexed_db": [],
            }
        ),
        encoding="utf-8",
    )
    (snapshots / "fresh.json").write_text(
        json.dumps(
            {
                "spec": "fresh.spec.ts",
                "cookies": [],
                "local_storage_keys": ["fresh-key"],
                "session_storage_keys": [],
                "indexed_db": [],
            }
        ),
        encoding="utf-8",
    )
    original_cookies = cookies_source.read_bytes()
    original_storage = storage_source.read_bytes()
    monkeypatch.setattr(merge_storage_audits, "SNAPSHOT_DIR", snapshots)
    monkeypatch.setattr(merge_storage_audits, "COOKIES_YAML", cookies_source)
    monkeypatch.setattr(merge_storage_audits, "BROWSER_STORAGE_YAML", storage_source)

    cookies, storage = merge_storage_audits.merge(retain_unobserved=True)
    candidate_dir = tmp_path / "test-results" / "storage-audit-candidate"
    merge_storage_audits.write(cookies, storage, output_dir=candidate_dir)

    assert cookies_source.read_bytes() == original_cookies
    assert storage_source.read_bytes() == original_storage
    candidate = yaml.safe_load((candidate_dir / "browser-storage.yml").read_text(encoding="utf-8"))
    assert {entry["key"] for entry in candidate["local_storage"]} == {"prior-key", "fresh-key"}


def test_nightly_orchestrator_requests_candidate_output(monkeypatch, tmp_path: Path) -> None:
    merger = tmp_path / "scripts" / "merge_storage_audits.py"
    merger.parent.mkdir(parents=True)
    merger.write_text("# test merger\n", encoding="utf-8")
    candidate_dir = tmp_path / "test-results" / "storage-audit-candidate"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(run_tests, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_tests, "STORAGE_AUDIT_CANDIDATE_DIR", candidate_dir)
    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)

    run_tests.TestOrchestrator._merge_cookie_audits()

    assert calls == [[
        run_tests.sys.executable,
        str(merger),
        "--output-dir",
        str(candidate_dir),
        "--retain-unobserved",
    ]]


def test_product_runtime_diagnostics_classifies_only_known_generated_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".git").mkdir()
    generated = sorted(sessions.PRODUCT_RUNTIME_GENERATED_PATHS)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root: generated)

    diagnostics = sessions._product_runtime_diagnostics(tmp_path)

    assert diagnostics == {
        "exists": True,
        "dirty_files": generated,
        "generated_only": True,
    }
