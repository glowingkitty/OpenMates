"""Tests for session-level CLI and Playwright proof-video orchestration.

Purpose: verify exact capture delegates to the demonstration pipeline safely.
Security: webhook fixtures are synthetic and must never be printed.
Architecture: scripts/sessions.py wraps scripts/spec_demo.py for session evidence.
Tests: python3 -m pytest scripts/tests/test_sessions_proof_video.py.
"""

# contract-test-file: tooling

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
    monkeypatch.setattr(sessions, "_save_sessions", lambda _data: None)
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
        audio_path=tmp_path / "narration-audio.mp3",
        audio_provider="elevenlabs",
        audio_model="eleven_flash_v2_5",
        audio_voice="warm_neutral",
        audio_reused_from="",
        device_profile=None,
        playback_rate=1.0,
        hold_last_frame_seconds=0.0,
        demo_audio_path=None,
    )

    sessions.cmd_proof_video(args)

    assert observed["argv"] == ["openmates", "plans", "create"]
    assert observed["anonymize_sensitive"] is True
    assert observed["narration_audio_model"] == "eleven_flash_v2_5"


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
    monkeypatch.setattr(sessions, "_save_sessions", lambda _data: None)
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
        audio_path=tmp_path / "narration-audio.mp3",
        audio_provider="elevenlabs",
        audio_model="eleven_flash_v2_5",
        audio_voice="warm_neutral",
        audio_reused_from="",
        device_profile="web-phone",
        playback_rate=0.75,
        hold_last_frame_seconds=2.0,
        demo_audio_path=tmp_path / "product-audio.mp3",
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
    assert observed["device_profile_name"] == "web-phone"
    assert observed["playback_rate"] == 0.75
    assert observed["hold_last_frame_seconds"] == 2.0
    assert observed["demo_audio_path"] == tmp_path / "product-audio.mp3"


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
    monkeypatch.setattr(sessions, "_save_sessions", lambda _data: None)
    monkeypatch.setattr(sessions, "ENV_FILE", env_file)
    monkeypatch.delenv("DISCORD_WEBHOOK_DEV_SMOKE", raising=False)

    sessions.cmd_proof_video(
        argparse.Namespace(session="abcd", proof_action="publish", run_dir=run_dir),
    )

    assert observed["webhook_url"] == secret
    assert secret not in capsys.readouterr().out


def write_passed_manifest(tmp_path: Path, *, subject_commit: str = "abc1234") -> Path:
    run_dir = tmp_path / "proof"
    run_dir.mkdir()
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "spec_id": "session-proof",
                "subject_commit": subject_commit,
                "privacy": {"status": "passed"},
                "narration_audio": {
                    "status": "passed",
                    "provider": "elevenlabs",
                    "model": "eleven_flash_v2_5",
                    "voice": "warm_neutral",
                    "path": str(run_dir / "narration-audio.mp3"),
                    "sha256": "sha256:" + "a" * 64,
                    "mime_type": "audio/mpeg",
                    "duration_seconds": 1.0,
                    "reused_from": "",
                },
                "video_metadata": {"has_audio": True},
                "captions": [{"id": "CAP-1", "text": "Visible."}],
                "review": {"status": "passed", "run_id": "review-1", "attempt_count": 1},
                "publication": {"status": "delivered"},
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_proof_video_gate_blocks_feature_runtime_changes_without_video(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sessions, "_current_head", lambda: "abc1234")
    monkeypatch.setattr(sessions, "_proof_video_delivery_required", lambda: False)

    with pytest.raises(SystemExit):
        sessions._enforce_proof_video_end_gate(
            "abcd",
            {"mode": "feature"},
            ["frontend/packages/ui/src/components/NewFeature.svelte"],
        )

    assert "PROOF VIDEO REQUIRED" in capsys.readouterr().err


def test_proof_video_gate_ignores_docs_and_scripts_only_feature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "_current_head", lambda: "abc1234")

    sessions._enforce_proof_video_end_gate(
        "abcd",
        {"mode": "feature"},
        ["scripts/spec_demo.py", "docs/specs/example/spec.yml"],
    )


def test_proof_video_gate_accepts_current_delivered_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = write_passed_manifest(tmp_path)
    monkeypatch.setattr(sessions, "_current_head", lambda: "abc1234")
    monkeypatch.setattr(sessions, "_proof_video_delivery_required", lambda: True)
    session = {
        "mode": "feature",
        "proof_videos": [
            {
                "status": "passed",
                "subject_commit": "abc1234",
                "manifest_path": str(manifest_path),
            }
        ],
    }

    sessions._enforce_proof_video_end_gate(
        "abcd",
        session,
        ["frontend/packages/ui/src/components/NewFeature.svelte"],
    )


def test_proof_video_manifest_requires_exact_device_profile_dimensions(tmp_path: Path) -> None:
    manifest_path = write_passed_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["video_metadata"] = {
        "has_audio": True,
        "device_profile": "web-phone",
        "width": 800,
        "height": 450,
        "target_width": 390,
        "target_height": 844,
        "black_bar_scan_status": {"status": "passed"},
    }

    problems = sessions._proof_video_manifest_problems(manifest, delivery_required=True)

    assert "web-phone proof video must be 390x844" in problems
