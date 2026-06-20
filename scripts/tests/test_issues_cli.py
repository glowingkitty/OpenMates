#!/usr/bin/env python3
"""
Regression tests for the reported-issue workflow CLI.

These tests cover pure parsing, clustering, and local findings-note behavior.
They never call Docker, Directus, or the privileged debug.py issue backend.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ISSUES_CLI_PATH = PROJECT_ROOT / "scripts" / "issues.py"


def load_issues_cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("openmates_issues_cli", ISSUES_CLI_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "FINDINGS_ROOT", tmp_path / "docs" / "findings" / "issues")
    return module


def sample_issue() -> dict:
    return {
        "id": "a3d966e2-3d50-4f3a-b208-31ee218afe12",
        "short_issue_id": "K7M2Q",
        "title": "Audio upload failed",
        "created_at": "2026-06-19T09:10:11Z",
        "processed": False,
        "linear_issue_identifier": "OPE-512",
        "decrypted": {
            "chat_or_embed_url": "https://app.openmates.org/share/chat/11111111-2222-3333-4444-555555555555#key=secret-value",
        },
    }


def test_extract_json_object_from_noisy_debug_output(tmp_path, monkeypatch):
    issues_cli = load_issues_cli(tmp_path, monkeypatch)

    output = "INFO starting issue lookup\n{\"issues\": [{\"id\": \"123\"}]}\nWARNING done"

    assert issues_cli.extract_json_object(output) == {"issues": [{"id": "123"}]}


def test_env_normalization_and_redaction(tmp_path, monkeypatch):
    issues_cli = load_issues_cli(tmp_path, monkeypatch)

    assert issues_cli.normalize_env("production") == "prod"
    assert issues_cli.normalize_env(" DEV ") == "dev"
    assert issues_cli.redact_url("https://example.test/share/chat/abc#key=top-secret") == (
        "https://example.test/share/chat/abc#key=<redacted>"
    )


def test_normalize_issue_detail_matches_debug_detail_shape(tmp_path, monkeypatch):
    issues_cli = load_issues_cli(tmp_path, monkeypatch)

    normalized = issues_cli.normalize_issue_detail(
        {
            "issue_id": "issue-123",
            "short_issue_id": "Q8R7T",
            "issue_metadata": {"title": "Broken upload", "created_at": "2026-06-19T09:10:11Z"},
            "decrypted_fields": {"description": "The upload failed"},
        },
        "production",
    )

    assert normalized["id"] == "issue-123"
    assert normalized["short_issue_id"] == "Q8R7T"
    assert normalized["title"] == "Broken upload"
    assert normalized["decrypted"] == {"description": "The upload failed"}
    assert normalized["_env"] == "prod"


def test_cluster_key_prefers_share_url(tmp_path, monkeypatch):
    issues_cli = load_issues_cli(tmp_path, monkeypatch)

    assert issues_cli.cluster_key(sample_issue()) == "chat:11111111-2222-3333-4444-555555555555"


def test_findings_note_creation_redacts_url_and_uses_year_path(tmp_path, monkeypatch):
    issues_cli = load_issues_cli(tmp_path, monkeypatch)

    path = issues_cli.ensure_findings_note(sample_issue(), "prod")

    assert path == (
        tmp_path
        / "docs/findings/issues/prod/2026/a3d966e2-3d50-4f3a-b208-31ee218afe12-audio-upload-failed.md"
    )
    note = path.read_text(encoding="utf-8")
    assert "issue_id: a3d966e2-3d50-4f3a-b208-31ee218afe12" in note
    assert "short_issue_id: K7M2Q" in note
    assert "status: open" in note
    assert "#key=<redacted>" in note
    assert "secret-value" not in note
    assert "linear: [OPE-512]" in note


def test_mark_and_link_update_findings_frontmatter(tmp_path, monkeypatch, capsys):
    issues_cli = load_issues_cli(tmp_path, monkeypatch)
    issue = sample_issue()

    monkeypatch.setattr(issues_cli, "fetch_issue_detail", lambda env, issue_id, include_logs=False: issue)

    assert issues_cli.main(["findings", issue["id"], "--env", "prod"]) == 0
    assert issues_cli.main(["mark", issue["id"], "--env", "prod", "--status", "verified"]) == 0
    assert issues_cli.main(["link", issue["id"], "--env", "prod", "--github", "#123", "--linear", "OPE-999"]) == 0
    capsys.readouterr()

    path = issues_cli.findings_path(issue, "prod")
    note = path.read_text(encoding="utf-8")
    assert "status: verified" in note
    assert "github: [#123]" in note
    assert "linear: [OPE-512, OPE-999]" in note


def test_issue_table_and_show_prefer_short_issue_id(tmp_path, monkeypatch, capsys):
    issues_cli = load_issues_cli(tmp_path, monkeypatch)
    issue = sample_issue()

    issues_cli.print_issue_table([issue])
    table_output = capsys.readouterr().out
    assert "K7M2Q" in table_output
    assert "a3d966e2" not in table_output

    monkeypatch.setattr(issues_cli, "fetch_issue_detail", lambda env, issue_id, include_logs=False: issue)
    assert issues_cli.main(["show", "K7M2Q", "--env", "prod"]) == 0
    show_output = capsys.readouterr().out
    assert "Issue: K7M2Q" in show_output
    assert "UUID: a3d966e2-3d50-4f3a-b208-31ee218afe12" in show_output
