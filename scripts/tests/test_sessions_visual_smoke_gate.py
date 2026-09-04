# contract-test-file: tooling
"""Tests for deployed UI visual-smoke session gating.

Purpose: prevent larger UI sessions from ending without a deployed visual review.
Architecture: import sessions.py directly and exercise pure helpers plus the
session evidence command against a temporary sessions.json file.
Security: tests use synthetic URLs and no network, credentials, or product data.
Run: python3 -m pytest scripts/tests/test_sessions_visual_smoke_gate.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_visual_smoke", SESSIONS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_visual_smoke_required_for_spec_backed_ui_work():
    sessions = load_sessions_module()

    assert sessions._requires_visual_smoke(
        [
            "docs/plans/example-ui/plan.yml",
            "frontend/packages/ui/src/components/settings/SettingsExample.svelte",
        ]
    )


def test_visual_smoke_not_required_for_tiny_nonvisual_frontend_helper():
    sessions = load_sessions_module()

    assert not sessions._requires_visual_smoke(
        ["frontend/packages/ui/src/utils/formatCredits.ts"]
    )


def test_visual_smoke_record_requires_screenshot_review_terms():
    sessions = load_sessions_module()
    session = {
        "visual_smoke": [
            {
                "status": "passed",
                "subject_commit": "abcdef123456",
                "urls": ["https://app.dev.openmates.org/"],
                "viewports": ["laptop", "mobile"],
                "run_id": "playwright-summary.json",
                "summary": "Checked laptop and mobile rendering.",
            }
        ]
    }

    assert sessions._latest_visual_smoke_record(session, "abcdef1") is None


def test_visual_smoke_record_satisfies_current_commit_prefix():
    sessions = load_sessions_module()
    session = {
        "visual_smoke": [
            {
                "status": "passed",
                "subject_commit": "abcdef123456",
                "urls": ["https://app.dev.openmates.org/"],
                "viewports": ["laptop", "mobile"],
                "run_id": "playwright-summary.json",
                "summary": "Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none.",
            }
        ]
    }

    assert sessions._latest_visual_smoke_record(session, "abcdef1") is not None
    assert sessions._latest_visual_smoke_record(session, "fedcba9") is None


def test_visual_smoke_rejects_failed_local_playwright_artifact(tmp_path, monkeypatch):
    sessions = load_sessions_module()
    original_root = sessions.PROJECT_ROOT
    monkeypatch.setattr(sessions, "PROJECT_ROOT", tmp_path)
    summary_path = tmp_path / "test-results/visual-smoke/run/summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": "passed",
                "viewports": ["laptop", "mobile"],
                "records": [
                    {
                        "viewport": "mobile",
                        "problems": [],
                        "consoleErrors": ["Failed to load resource: 429"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        problems = sessions._visual_smoke_pass_record_problems(
            {
                "status": "passed",
                "urls": ["https://app.dev.openmates.org/"],
                "viewports": ["laptop", "mobile"],
                "run_id": "test-results/visual-smoke/run/summary.json",
                "summary": "Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none.",
            }
        )
    finally:
        monkeypatch.setattr(sessions, "PROJECT_ROOT", original_root)

    assert any("console errors" in problem for problem in problems)


def test_visual_smoke_command_records_evidence(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "locks": {},
                "sessions": {
                    "abcd": {
                        "task": "UI work",
                        "modified_files": [
                            "frontend/packages/ui/src/components/ActiveChat.svelte"
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_current_head", lambda: "abcdef123456")

    sessions.cmd_visual_smoke(
        argparse.Namespace(
            session="abcd",
            url=["https://app.dev.openmates.org/"],
            viewport=["laptop", "mobile"],
            result="passed",
            method="playwright",
            run_id="playwright-summary.json",
            screenshot=["screenshot-123.png"],
            summary="Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none.",
            reason=None,
            commit=None,
        )
    )

    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    record = data["sessions"]["abcd"]["visual_smoke"][0]
    assert record["status"] == "passed"
    assert record["method"] == "playwright"
    assert record["run_id"] == "playwright-summary.json"
    assert record["viewports"] == ["laptop", "mobile"]
    assert record["subject_commit"] == "abcdef123456"


def test_visual_smoke_command_rejects_passed_without_artifact(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps({"locks": {}, "sessions": {"abcd": {"task": "UI work"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)

    with pytest.raises(SystemExit):
        sessions.cmd_visual_smoke(
            argparse.Namespace(
                session="abcd",
                url=["https://app.dev.openmates.org/"],
                viewport=["laptop", "mobile"],
                result="passed",
                method="playwright",
                run_id=None,
                screenshot=None,
                summary="Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none.",
                reason=None,
                commit="abcdef123456",
            )
        )


def test_visual_smoke_command_rejects_passed_without_both_viewports(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps({"locks": {}, "sessions": {"abcd": {"task": "UI work"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)

    with pytest.raises(SystemExit):
        sessions.cmd_visual_smoke(
            argparse.Namespace(
                session="abcd",
                url=["https://app.dev.openmates.org/"],
                viewport=["laptop"],
                result="passed",
                method="playwright",
                run_id="playwright-summary.json",
                screenshot=None,
                summary="Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none.",
                reason=None,
                commit="abcdef123456",
            )
        )
