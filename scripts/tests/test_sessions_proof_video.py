"""Tests for session-level CLI and Playwright proof-video orchestration.

Purpose: verify exact capture delegates to the demonstration pipeline safely.
Security: webhook fixtures are synthetic and must never be printed.
Architecture: scripts/sessions.py wraps scripts/spec_demo.py for session evidence.
Tests: python3 -m pytest scripts/tests/test_sessions_proof_video.py.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from scripts import sessions


class SyntheticDemonstrationError(RuntimeError):
    pass


def fake_spec_demo(**functions: object) -> ModuleType:
    module = ModuleType("spec_demo")
    module.DemonstrationError = SyntheticDemonstrationError
    module.produce_cli_demonstration = functions.get("produce", lambda **_kwargs: {})
    module.produce_playwright_demonstration = functions.get("produce_playwright", lambda **_kwargs: {})
    module.record_review = functions.get("review", lambda *_args: {})
    module.publish_reviewed_video = functions.get("publish", lambda *_args, **_kwargs: {})
    return module


def test_proof_video_produce_always_enables_typed_anonymization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def produce(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"privacy": {"status": "passed"}}

    monkeypatch.setitem(sys.modules, "spec_demo", fake_spec_demo(produce=produce))
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})
    args = argparse.Namespace(
        session="abcd",
        proof_action="produce",
        argv=["--", "openmates", "plans", "create"],
        run_dir=tmp_path / "proof",
        subject_commit="abc1234",
        proof_id="plan-proof",
        run_id="run-1",
        target_environment="dev",
        test_account_provenance="stored session",
        narration_id="NARR-1",
        caption="Create a plan.",
        expected_proof="The plan is created.",
        acceptance_criterion=["AC-1"],
    )

    sessions.cmd_proof_video(args)

    assert observed["argv"] == ["openmates", "plans", "create"]
    assert observed["anonymize_sensitive"] is True


def test_proof_video_playwright_requires_and_forwards_passing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def produce_playwright(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"privacy": {"status": "passed"}}

    video = tmp_path / "video.webm"
    video.write_bytes(b"video")
    monkeypatch.setitem(
        sys.modules,
        "spec_demo",
        fake_spec_demo(produce_playwright=produce_playwright),
    )
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})
    args = argparse.Namespace(
        session="abcd",
        proof_action="produce-playwright",
        run_dir=tmp_path / "proof",
        source_video=video,
        proof_id="signup-proof",
        subject_commit="abc1234",
        run_id="gha-123-case-1",
        target_environment="https://app.dev.openmates.org",
        test_account_provenance="reserved test account with synthetic signup identity",
        narration_id="NARR-1",
        caption="The signup tutorial explains the action and visible result.",
        expected_proof="The passing signup flow is visible.",
        acceptance_criterion=["AC-1"],
        spec_name="signup-flow-passkey.spec.ts",
        deployment_reference="dpl-example",
        source_status="passed",
    )

    sessions.cmd_proof_video(args)

    assert observed["source_video"] == video
    assert observed["source"] == {
        "status": "passed",
        "command_or_spec": "signup-flow-passkey.spec.ts",
        "target": "https://app.dev.openmates.org",
        "deployment_reference": "dpl-example",
        "run_id": "gha-123-case-1",
        "subject_commit": "abc1234",
        "artifact_path": str(video),
        "test_account_provenance": "reserved test account with synthetic signup identity",
    }


def test_proof_video_publish_loads_dev_smoke_webhook_without_printing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "https://discord.invalid/api/webhooks/synthetic/dev-smoke"
    env_file = tmp_path / ".env"
    env_file.write_text(f"DISCORD_WEBHOOK_DEV_SMOKE={secret}\n", encoding="utf-8")
    run_dir = tmp_path / "proof"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"review": {"status": "passed"}}), encoding="utf-8")
    observed: dict[str, object] = {}

    def publish(*_args: object, **kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"publication": {"status": "delivered"}}

    monkeypatch.setitem(sys.modules, "spec_demo", fake_spec_demo(publish=publish))
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})
    monkeypatch.setattr(sessions, "ENV_FILE", env_file)
    monkeypatch.delenv("DISCORD_WEBHOOK_DEV_SMOKE", raising=False)

    sessions.cmd_proof_video(
        argparse.Namespace(session="abcd", proof_action="publish", run_dir=run_dir),
    )

    assert observed["webhook_url"] == secret
    assert secret not in capsys.readouterr().out
