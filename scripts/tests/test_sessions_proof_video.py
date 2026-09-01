"""Tests for session-level CLI and Playwright proof-video orchestration.

Purpose: verify exact capture delegates to the demonstration pipeline safely.
Security: response-media URLs are synthetic in tests and secrets are never printed.
Architecture: scripts/sessions.py wraps scripts/spec_demo.py for session evidence.
Tests: python3 -m pytest scripts/tests/test_sessions_proof_video.py.
"""

# contract-test-file: tooling

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from scripts import sessions
from scripts import proof_video_workflow
from scripts import spec_demo


class SyntheticDemonstrationError(RuntimeError):
    pass


def fake_spec_demo(**functions: object) -> ModuleType:
    module = ModuleType("spec_demo")
    module.DemonstrationError = SyntheticDemonstrationError
    module.produce_cli_demonstration = functions.get("produce", lambda **_kwargs: {})
    module.produce_playwright_demonstration = functions.get("produce_playwright", lambda **_kwargs: {})
    module.require_review_receipt_integrity = functions.get("require_receipt", lambda *_args: None)
    module.resolve_run_artifact_path = functions.get("resolve_path", lambda run_dir, value: Path(run_dir) / value)
    module.publish_reviewed_video = functions.get("publish", lambda *_args, **_kwargs: {})
    return module


def fake_proof_workflow(**functions: object) -> ModuleType:
    module = ModuleType("proof_video_workflow")
    module.WorkflowError = SyntheticDemonstrationError
    module.approved_render_claims = functions.get(
        "approved_render_claims",
        lambda _contract, **_kwargs: {
            "caption_text": "Approved caption.",
            "expected_proof": "Approved proof.",
            "acceptance_criteria": ["approved"],
            "assertions": [{"id": "approved", "description": "Approved proof."}],
            "contract_hash": "sha256:" + "a" * 64,
        },
    )
    module.record_contract_authorization = functions.get("record_contract_authorization", lambda **_kwargs: {})
    module.require_clean_worktree = functions.get("require_clean_worktree", lambda *_args: None)
    module.require_recorded_approval = functions.get("require_recorded_approval", lambda **_kwargs: {})
    module.resolve_deployed_run = functions.get("resolve_deployed_run", lambda **_kwargs: {})
    return module


def allow_control_plane_deploy_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "_fetch_origin_dev_commit", lambda: "origin-dev")
    monkeypatch.setattr(sessions, "_enforce_control_plane_deploy_protocol_compatible", lambda _origin_ref: None)


def test_proof_video_produce_does_not_enable_typed_anonymization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def produce(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"privacy": {"status": "not_applicable", "scan": "disabled"}}

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
        audio_path=None,
        audio_provider="elevenlabs",
        audio_model="eleven_flash_v2_5",
        audio_voice="warm_neutral",
        audio_reused_from="",
        timeout_seconds=240.0,
        device_profile=None,
        playback_rate=1.0,
        hold_last_frame_seconds=0.0,
        demo_audio_path=None,
    )

    sessions.cmd_proof_video(args)

    assert observed["argv"] == ["openmates", "plans", "create"]
    assert "anonymize_sensitive" not in observed
    assert observed["timeout_seconds"] == 240.0
    assert observed["narration_audio_path"] is None


def test_proof_video_produce_rejects_generic_smoke_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "spec_demo", fake_spec_demo())
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})
    monkeypatch.setattr(sessions, "_save_sessions", lambda _data: None)

    args = argparse.Namespace(
        session="abcd",
        proof_action="produce",
        argv=["--", "python3", "scripts/smoke_cli_encrypted_slugs.py"],
        run_dir=tmp_path / "proof",
        subject_commit="abc1234",
        proof_id="cli-proof",
        run_id="run-1",
        target_environment="dev",
        test_account_provenance="stored session",
        narration_id="NARR-1",
        caption="Run a smoke script.",
        expected_proof="The smoke output is visible.",
        acceptance_criterion=["AC-1"],
        audio_path=None,
        audio_provider="elevenlabs",
        audio_model="eleven_flash_v2_5",
        audio_voice="warm_neutral",
        audio_reused_from="",
        device_profile=None,
        playback_rate=1.0,
        hold_last_frame_seconds=0.0,
        demo_audio_path=None,
    )

    with pytest.raises(SyntheticDemonstrationError, match="OpenMates CLI"):
        sessions.cmd_proof_video(args)


def test_proof_video_playwright_requires_and_forwards_passing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    commit = "a" * 40

    def produce_playwright(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"privacy": {"status": "passed"}}

    video = tmp_path / "video.webm"
    video.write_bytes(b"video")
    contract_path = tmp_path / "contract.json"
    proof_video_workflow.write_contract(
        contract_path,
        {
            "title": "Signup proof",
            "transcript": ["The signup screen shows the expected result."],
            "assertions": [{"id": "signup", "description": "The signup result is visible."}],
            "devices": ["web-phone"],
        },
    )
    results_dir = tmp_path / "test-results"
    results_dir.mkdir()
    proof_sources = results_dir / "proof-video-sources"
    proof_sources.mkdir()
    (proof_sources / "source.json").write_text(
        json.dumps(
            {
                "run_id": "gha-123-case-1",
                "git_sha": commit,
                "source": "scripts_tests",
                "deployment_verified": True,
                "deployment_reference": commit,
                "target": "https://app.dev.openmates.org",
                "spec": "signup-flow-passkey.spec.ts",
                "status": "passed",
                "artifact_path": str(video),
                "artifact_sha256": proof_video_workflow._file_sha256(video),
                "action_timestamps": [1.25],
                "state_change_timestamps": [2.5],
                "state_change_timestamps_by_id": {"signup.visible": 2.5},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(proof_video_workflow, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(proof_video_workflow, "APPROVALS_DIR", results_dir / "proof-video-approvals")
    monkeypatch.setattr(proof_video_workflow, "PROOF_SOURCE_DIR", proof_sources)
    monkeypatch.setattr(proof_video_workflow, "_tracked_worktree_changes", lambda: [])
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
        subject_commit=commit,
        run_id="gha-123-case-1",
        target_environment="https://app.dev.openmates.org",
        test_account_provenance="reserved test account with synthetic signup identity",
        narration_id="NARR-1",
        caption="The signup tutorial explains the action and visible result.",
        expected_proof="The passing signup flow is visible.",
        acceptance_criterion=["AC-1"],
        audio_path=None,
        audio_provider="elevenlabs",
        audio_model="eleven_flash_v2_5",
        audio_voice="warm_neutral",
        audio_reused_from="",
        device_profile="web-phone",
        playback_rate=0.75,
        hold_last_frame_seconds=2.0,
        ready_timestamp_seconds=4.2,
        source_end_timestamp_seconds=8.4,
        demo_audio_path=tmp_path / "product-audio.mp3",
        spec_name="signup-flow-passkey.spec.ts",
        contract_path=contract_path,
    )

    sessions.cmd_proof_video(args)

    assert observed["source_video"] == video
    assert observed["source"] == {
        "source": "scripts_tests",
        "status": "passed",
        "command_or_spec": "signup-flow-passkey.spec.ts",
        "target": "https://app.dev.openmates.org",
        "deployment_reference": commit,
        "run_id": "gha-123-case-1",
        "subject_commit": commit,
        "artifact_path": str(video),
        "artifact_sha256": proof_video_workflow._file_sha256(video),
        "test_account_provenance": "reserved test account with synthetic signup identity",
        "action_timestamps": [1.25],
        "state_change_timestamps": [2.5],
        "state_change_timestamps_by_id": {"signup.visible": 2.5},
        "source_end_timestamp_seconds": 8.4,
    }
    assert observed["device_profile_name"] == "web-phone"
    assert observed["narration_audio_path"] is None
    assert observed["caption_text"] == "The signup screen shows the expected result."
    assert observed["expected_proof"] == "The signup result is visible."
    assert observed["acceptance_criteria"] == ["signup"]
    assert observed["proof_assertions"] == [{"id": "signup", "description": "The signup result is visible."}]
    assert str(observed["proof_contract_hash"]).startswith("sha256:")
    assert str(observed["proof_group_id"]).startswith("sha256:")
    assert observed["proof_group_id"] == "sha256:" + hashlib.sha256(
        f"{args.spec_name}\0{observed['proof_contract_hash']}".encode("utf-8")
    ).hexdigest()
    assert observed["playback_rate"] == 0.75
    assert observed["hold_last_frame_seconds"] == 2.0
    assert observed["ready_timestamp_seconds"] == 4.2
    assert observed["demo_audio_path"] == tmp_path / "product-audio.mp3"
    authorization = json.loads(
        proof_video_workflow.approval_record_path("abcd", "signup-flow-passkey.spec.ts").read_text(encoding="utf-8")
    )
    assert authorization["authorized_by"] == "tooling"
    assert authorization["contract_hash"] == observed["proof_contract_hash"]


def test_proof_video_playwright_uses_passed_run_when_session_worktree_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    subject_commit = "a" * 40
    stale_session_commit = "b" * 40

    def produce_playwright(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"privacy": {"status": "passed"}}

    def reject_clean_worktree(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("passed Playwright run binding must not require local worktree provenance")

    video = tmp_path / "video.webm"
    video.write_bytes(b"video")
    contract_path = tmp_path / "contract.json"
    proof_video_workflow.write_contract(
        contract_path,
        {
            "schema_version": 2,
            "title": "Team context isolation",
            "transcript": [{"text": "The Team workspace shows isolated chat state.", "devices": ["web-laptop"]}],
            "assertions": [
                {
                    "id": "team-context-isolated",
                    "description": "Personal chats are absent from the Team context.",
                    "devices": ["web-laptop"],
                }
            ],
            "devices": ["web-laptop"],
        },
    )
    results_dir = tmp_path / "test-results"
    proof_sources = results_dir / "proof-video-sources"
    proof_sources.mkdir(parents=True)
    (proof_sources / "source.json").write_text(
        json.dumps(
            {
                "run_id": "gha-123-case-1",
                "git_sha": subject_commit,
                "source": "scripts_tests",
                "deployment_verified": True,
                "deployment_reference": subject_commit,
                "target": "https://app.dev.openmates.org",
                "spec": "teams-settings-context.spec.ts",
                "status": "passed",
                "artifact_path": str(video),
                "artifact_sha256": proof_video_workflow._file_sha256(video),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(proof_video_workflow, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(proof_video_workflow, "APPROVALS_DIR", results_dir / "proof-video-approvals")
    monkeypatch.setattr(proof_video_workflow, "PROOF_SOURCE_DIR", proof_sources)
    monkeypatch.setattr(proof_video_workflow, "require_clean_worktree", reject_clean_worktree)
    proof_video_workflow.record_contract_approval(
        session_id="abcd",
        spec_name="teams-settings-context.spec.ts",
        contract_path=contract_path,
    )
    monkeypatch.setitem(sys.modules, "spec_demo", fake_spec_demo(produce_playwright=produce_playwright))
    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {
            "sessions": {
                "abcd": {
                    "modified_files": ["frontend/packages/ui/src/components/ActiveChat.svelte"],
                    "worktree": {"merged_commit": stale_session_commit},
                }
            }
        },
    )
    monkeypatch.setattr(sessions, "_save_sessions", lambda _data: None)
    args = argparse.Namespace(
        session="abcd",
        proof_action="produce-playwright",
        run_dir=tmp_path / "proof",
        source_video=video,
        proof_id="teams-proof",
        subject_commit=subject_commit,
        run_id="gha-123-case-1",
        target_environment="https://app.dev.openmates.org",
        test_account_provenance="reserved test account 2",
        narration_id="NARR-1",
        caption="The Team workspace shows isolated chat state.",
        expected_proof="Personal chats are absent from the Team context.",
        acceptance_criterion=["team-context-isolated"],
        audio_path=None,
        audio_provider="elevenlabs",
        audio_model="eleven_flash_v2_5",
        audio_voice="warm_neutral",
        audio_reused_from="",
        device_profile="web-laptop",
        playback_rate=1.0,
        hold_last_frame_seconds=0.0,
        ready_timestamp_seconds=None,
        demo_audio_path=None,
        spec_name="teams-settings-context.spec.ts",
        contract_path=contract_path,
    )

    sessions.cmd_proof_video(args)

    assert observed["source_video"] == video
    assert observed["source"]["subject_commit"] == subject_commit
    assert observed["device_profile_name"] == "web-laptop"


def test_proof_video_playwright_rejects_unverified_source_before_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "video.webm"
    video.write_bytes(b"video")
    rendered = False

    def produce_playwright(**_kwargs: object) -> dict[str, object]:
        nonlocal rendered
        rendered = True
        return {}

    def reject_run(**_kwargs: object) -> dict[str, object]:
        raise SyntheticDemonstrationError("expected one deployed passing run")

    monkeypatch.setitem(sys.modules, "spec_demo", fake_spec_demo(produce_playwright=produce_playwright))
    monkeypatch.setitem(sys.modules, "proof_video_workflow", fake_proof_workflow(resolve_deployed_run=reject_run))
    monkeypatch.setitem(sys.modules, "scripts.proof_video_workflow", sys.modules["proof_video_workflow"])
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})
    args = argparse.Namespace(
        session="abcd",
        proof_action="produce-playwright",
        run_dir=tmp_path / "proof",
        source_video=video,
        proof_id="proof",
        subject_commit="abc1234",
        run_id="local-run",
        target_environment="https://app.dev.openmates.org",
        test_account_provenance="synthetic account",
        narration_id="NARR-1",
        caption="The screen shows the action and its visible result.",
        expected_proof="The result is visible.",
        acceptance_criterion=["AC-1"],
        audio_path=None,
        audio_provider="elevenlabs",
        audio_model="eleven_flash_v2_5",
        audio_voice="warm_neutral",
        audio_reused_from="",
        device_profile="web-phone",
        playback_rate=1.0,
        hold_last_frame_seconds=0.0,
        demo_audio_path=None,
        spec_name="example.spec.ts",
        contract_path=tmp_path / "contract.json",
    )

    with pytest.raises(SyntheticDemonstrationError, match="deployed passing run"):
        sessions.cmd_proof_video(args)

    assert rendered is False


def test_proof_video_playwright_rejects_post_resolution_artifact_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "video.webm"
    video.write_bytes(b"original")
    rendered = False

    def produce_playwright(**kwargs: object) -> dict[str, object]:
        nonlocal rendered
        rendered = True
        from scripts import spec_demo

        spec_demo.select_playwright_source([kwargs["source"]], run_id="run-one", subject_commit="a" * 40)
        return {}

    def resolve_run(**_kwargs: object) -> dict[str, object]:
        record = {
            "artifact_path": str(video),
            "artifact_sha256": proof_video_workflow._file_sha256(video),
            "target": "https://app.dev.openmates.org",
            "deployment_reference": "a" * 40,
        }
        video.write_bytes(b"replacement")
        return record

    monkeypatch.setitem(sys.modules, "spec_demo", fake_spec_demo(produce_playwright=produce_playwright))
    monkeypatch.setitem(sys.modules, "proof_video_workflow", fake_proof_workflow(resolve_deployed_run=resolve_run))
    monkeypatch.setitem(sys.modules, "scripts.proof_video_workflow", sys.modules["proof_video_workflow"])
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})
    args = argparse.Namespace(
        session="abcd", proof_action="produce-playwright", run_dir=tmp_path / "proof",
        source_video=video, proof_id="proof", subject_commit="a" * 40, run_id="run-one",
        target_environment="https://app.dev.openmates.org", test_account_provenance="synthetic account",
        narration_id="NARR-1", caption="The screen shows the action and visible result.",
        expected_proof="The result is visible.", acceptance_criterion=["AC-1"], audio_path=None,
        audio_provider="elevenlabs", audio_model="eleven_flash_v2_5", audio_voice="warm_neutral",
        audio_reused_from="", device_profile="web-phone", playback_rate=1.0,
        hold_last_frame_seconds=0.0, demo_audio_path=None, spec_name="example.spec.ts",
        contract_path=tmp_path / "contract.json",
    )

    with pytest.raises(Exception, match="hash no longer matches"):
        sessions.cmd_proof_video(args)

    assert rendered is True


def test_proof_video_publish_uploads_response_media_without_discord(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "https://discord.invalid/api/webhooks/synthetic/dev-smoke"
    env_file = tmp_path / ".env"
    env_file.write_text(f"DISCORD_WEBHOOK_DEV_SMOKE={secret}\n", encoding="utf-8")
    run_dir = tmp_path / "proof"
    run_dir.mkdir()
    video = run_dir / "proof.mp4"
    video.write_bytes(b"video")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spec_id": "session-proof",
                "privacy": {"status": "passed"},
                "review": {"status": "passed"},
                "narration_audio": {"status": "not_required"},
                "video_path": "proof.mp4",
                "video_metadata": {"sha256": "sha256:" + hashlib.sha256(b"video").hexdigest()},
            }
        ),
        encoding="utf-8",
    )
    observed_command: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> object:
        observed_command.extend(command)

        class Result:
            returncode = 0
            stderr = ""
            stdout = json.dumps(
                {
                    "expires_in": 172800,
                    "key": "opencode-responses/proof.mp4",
                    "sha256": "sha256:" + hashlib.sha256(b"video").hexdigest(),
                    "snippets": {
                        "html": "<video controls><source src=\"https://example.invalid/proof.mp4\"></video>",
                        "markdown": "[Proof](https://example.invalid/proof.mp4)",
                    },
                    "url": "https://example.invalid/proof.mp4",
                }
            )

        return Result()

    monkeypatch.setitem(sys.modules, "spec_demo", fake_spec_demo())
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})
    monkeypatch.setattr(sessions, "_save_sessions", lambda _data: None)
    monkeypatch.setattr(sessions, "ENV_FILE", env_file)
    monkeypatch.setattr(sessions.subprocess, "run", fake_run)
    monkeypatch.delenv("DISCORD_WEBHOOK_DEV_SMOKE", raising=False)

    sessions.cmd_proof_video(
        argparse.Namespace(session="abcd", proof_action="publish", run_dir=run_dir),
    )

    output = capsys.readouterr().out
    publication = json.loads((run_dir / "publication.json").read_text(encoding="utf-8"))

    assert "opencode_response_media.py" in " ".join(observed_command)
    assert publication["delivery_kind"] == "opencode_response_media"
    assert publication["snippet_html"].startswith("<video")
    assert "snippet_html" in output
    assert secret not in output


def write_passed_manifest(tmp_path: Path, *, subject_commit: str = "abc1234") -> Path:
    run_dir = tmp_path / "proof"
    run_dir.mkdir()
    proof_contract_hash = "sha256:" + "c" * 64
    video_hash = "sha256:" + "d" * 64
    frame_path = run_dir / "frames" / "frame.png"
    frame_path.parent.mkdir()
    frame_path.write_bytes(b"frame")
    request = spec_demo.build_review_request(
        spec_id="session-proof",
        subject_commit=subject_commit,
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["visible"]}],
        expected_proof=[{"claim_id": "visible", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": "frames/frame.png", "sha256": spec_demo.sha256_file(frame_path)}],
        video_metadata={"duration_seconds": 1.0, "sha256": video_hash, "width": 320, "height": 240},
        narration_audio={"status": "not_required", "provider": "", "model": "", "voice": "", "path": "", "sha256": "", "mime_type": "", "duration_seconds": 0.0, "reused_from": ""},
        proof_contract_hash=proof_contract_hash,
    )
    frame_index_hash = str(request["frame_index_hash"])
    proof_group_id = str(request["proof_group_id"])
    receipt = {
        "status": "passed",
        "reviewer_session_id": "ses_reviewer",
        "frame_index_hash": frame_index_hash,
        "proof_contract_hash": proof_contract_hash,
        "proof_group_id": proof_group_id,
        "source_artifact_hash": video_hash,
        "review_request_hash": spec_demo.review_request_hash(request),
        "subject_commit": subject_commit,
        "correction_round": 0,
        "correction_kind": "none",
        "reviewed_frames": ["frames/frame.png"],
        "frame_reviews": [
            {
                "frame": "frames/frame.png",
                "checks": {
                    "layout": "pass",
                    "readability": "pass",
                    "geometry": "pass",
                    "controls": "pass",
                    "visual_assets": "pass",
                    "application_state": "pass",
                    "consistency": "pass",
                    "proof_alignment": "pass",
                },
                "observation": "Completed the independent critical UI scan.",
            }
        ],
        "assertions": [
            {
                "id": "visible",
                "verdict": "supported",
                "frames": ["frames/frame.png"],
                "observation": "The expected state is visible.",
            }
        ],
        "incidental_findings": [],
        "workflow": {"requires_user_input": False},
    }
    receipt_path = run_dir / "review-receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "review-request.json").write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
    receipt_hash = f"sha256:{hashlib.sha256(receipt_path.read_bytes()).hexdigest()}"
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "spec_id": "session-proof",
                "subject_commit": subject_commit,
                "proof_contract_hash": proof_contract_hash,
                "proof_group_id": proof_group_id,
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
                "video_metadata": {"has_audio": True, "sha256": video_hash},
                "captions": [{"id": "CAP-1", "text": "Visible."}],
                "review": {
                    "status": "passed",
                    "run_id": "review-1",
                    "attempt_count": 1,
                    "frame_index_hash": frame_index_hash,
                    "receipt_sha256": receipt_hash,
                },
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


def test_proof_video_deploy_records_pending_without_failing_plain_deploy(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    saved: dict[str, object] = {}

    def mutate(callback: object) -> None:
        data = {"sessions": {"abcd": {"mode": "feature"}}}
        callback(data)
        saved.update(data)

    monkeypatch.setattr(sessions, "_current_head", lambda: "abc1234")
    monkeypatch.setattr(sessions, "_proof_video_delivery_required", lambda: False)
    monkeypatch.setattr(sessions, "_mutate_sessions", mutate)

    sessions._record_proof_video_deploy_pending(
        "abcd",
        {"mode": "feature"},
        ["frontend/packages/ui/src/components/NewFeature.svelte"],
    )

    error_output = capsys.readouterr().err
    assert "DEPLOYED BUT PROOF VIDEO REQUIRED" in error_output
    assert "proof_video_workflow.py start --current" in error_output
    pending = saved["sessions"]["abcd"]["proof_video_pending"]
    assert pending[0]["status"] == "pending"
    assert pending[0]["subject_commit"] == "abc1234"


def test_proof_video_deploy_skips_pending_for_not_required_account_health_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec_path = tmp_path / "frontend/apps/web_app/tests/test-account-preflight.spec.ts"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(
        "// proof-video: not_required reason=account_health\ntest('account preflight', async () => {});\n",
        encoding="utf-8",
    )
    saved: dict[str, object] = {}

    def mutate(callback: object) -> None:
        data = {"sessions": {"abcd": {"mode": "testing"}}}
        callback(data)
        saved.update(data)

    monkeypatch.setattr(sessions, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sessions, "_current_head", lambda: "abc1234")
    monkeypatch.setattr(sessions, "_mutate_sessions", mutate)

    sessions._record_proof_video_deploy_pending(
        "abcd",
        {"mode": "testing"},
        ["frontend/apps/web_app/tests/test-account-preflight.spec.ts"],
    )

    assert saved == {}
    assert "DEPLOYED BUT PROOF VIDEO REQUIRED" not in capsys.readouterr().err


def test_cmd_deploy_records_proof_pending_without_failing_plain_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_file = "frontend/packages/ui/src/components/NewFeature.svelte"
    commit = "a" * 40
    commands: list[list[str]] = []
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "locks": {},
                "sessions": {
                    "abcd": {
                        "mode": "feature",
                        "task": "proof pending deploy",
                        "modified_files": [runtime_file],
                        "proof_video_pending": [
                            {
                                "status": "pending",
                                "subject_commit": "c" * 40,
                                "next_action": "python3 scripts/proof_video_workflow.py start --current --spec <name>.spec.ts",
                            }
                        ],
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_run_cmd(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
        commands.append(command)
        if command[:2] == ["git", "commit"]:
            return 0, "[dev abc123] proof pending", ""
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, commit, ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda **_kwargs: [runtime_file])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda: {runtime_file})
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_get_lint_flags", lambda _files: [])
    monkeypatch.setattr(sessions, "_run_translation_build", lambda: (0, "", ""))
    monkeypatch.setattr(sessions, "_run_translation_validation", lambda: (0, "", ""))
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_sdk_cleartext_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_validate_staged_deploy_files", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_save_last_deploy_sha", lambda _sha: None)
    monkeypatch.setattr(sessions, "_proof_video_delivery_required", lambda: False)
    allow_control_plane_deploy_protocol(monkeypatch)

    sessions.cmd_deploy(
        argparse.Namespace(
            session="abcd",
            exclude=None,
            title="test: proof pending deploy",
            message=None,
            end_session=False,
            no_verify=False,
            use_staged=True,
            skip_tests_reason="unit test",
            skip_visual_smoke_reason=None,
            require_parity=False,
            expected_patch_id="",
            expected_checkpoint_commit="",
            lock_timeout=0,
            lock_poll=1,
        )
    )

    assert ["git", "push", "origin", "dev"] in commands
    error_output = capsys.readouterr().err
    assert "DEPLOYED BUT PROOF VIDEO REQUIRED" in error_output
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    pending = data["sessions"]["abcd"]["proof_video_pending"]
    assert [record["subject_commit"] for record in pending] == ["c" * 40, commit]
    assert pending[1]["next_action"].startswith("python3 scripts/proof_video_workflow.py start --current")


def test_cmd_deploy_end_hard_blocks_without_proof_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_file = "frontend/packages/ui/src/components/NewFeature.svelte"
    commit = "b" * 40
    commands: list[list[str]] = []
    finalized = False
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "locks": {},
                "sessions": {
                    "abcd": {
                        "mode": "feature",
                        "task": "proof blocked deploy end",
                        "modified_files": [runtime_file],
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_run_cmd(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
        commands.append(command)
        if command[:2] == ["git", "commit"]:
            return 0, "[dev abc123] proof blocked", ""
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, commit, ""
        return 0, "", ""

    def fake_finalize(*_args: object, **_kwargs: object) -> None:
        nonlocal finalized
        finalized = True

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda **_kwargs: [runtime_file])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda: {runtime_file})
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_get_lint_flags", lambda _files: [])
    monkeypatch.setattr(sessions, "_run_translation_build", lambda: (0, "", ""))
    monkeypatch.setattr(sessions, "_run_translation_validation", lambda: (0, "", ""))
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_sdk_cleartext_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_validate_staged_deploy_files", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_save_last_deploy_sha", lambda _sha: None)
    monkeypatch.setattr(sessions, "_proof_video_delivery_required", lambda: False)
    monkeypatch.setattr(sessions, "_enforce_visual_smoke_end_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "finalize_session_worktree", fake_finalize)
    allow_control_plane_deploy_protocol(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        sessions.cmd_deploy(
            argparse.Namespace(
                session="abcd",
                exclude=None,
                title="test: proof blocked deploy end",
                message=None,
                end_session=True,
                no_verify=False,
                use_staged=True,
                skip_tests_reason="unit test",
                skip_visual_smoke_reason=None,
                require_parity=False,
                expected_patch_id="",
                expected_checkpoint_commit="",
                lock_timeout=0,
                lock_poll=1,
            )
        )

    assert exc.value.code == 1
    assert ["git", "push", "origin", "dev"] in commands
    assert finalized is False
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


def test_proof_video_gate_accepts_prior_video_when_later_pending_cleanup_is_dev_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof_commit = "a" * 40
    cleanup_commit = "b" * 40
    manifest_path = write_passed_manifest(tmp_path, subject_commit=proof_commit)
    monkeypatch.setattr(sessions, "_current_head", lambda: cleanup_commit)
    monkeypatch.setattr(sessions, "_proof_video_delivery_required", lambda: False)
    session = {
        "mode": "feature",
        "proof_videos": [
            {
                "status": "passed",
                "subject_commit": proof_commit,
                "manifest_path": str(manifest_path),
            }
        ],
        "proof_video_pending": [
            {
                "status": "pending",
                "subject_commit": cleanup_commit,
                "files": [
                    "backend/core/api/app/routes/test_recordings.py",
                    "backend/core/api/main.py",
                    "deployment/dev_server/Caddyfile",
                    "frontend/apps/web_app/src/routes/tests/+page.svelte",
                ],
            }
        ],
    }

    sessions._enforce_proof_video_end_gate(
        "abcd",
        session,
        ["frontend/packages/openmates-cli/src/client.ts"],
        commit_sha=cleanup_commit,
    )


def test_proof_video_gate_blocks_prior_video_when_later_pending_product_change_requires_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proof_commit = "a" * 40
    product_commit = "b" * 40
    manifest_path = write_passed_manifest(tmp_path, subject_commit=proof_commit)
    monkeypatch.setattr(sessions, "_current_head", lambda: product_commit)
    monkeypatch.setattr(sessions, "_proof_video_delivery_required", lambda: False)
    session = {
        "mode": "feature",
        "proof_videos": [
            {
                "status": "passed",
                "subject_commit": proof_commit,
                "manifest_path": str(manifest_path),
            }
        ],
        "proof_video_pending": [
            {
                "status": "pending",
                "subject_commit": product_commit,
                "files": ["frontend/packages/ui/src/components/NewFeature.svelte"],
            }
        ],
    }

    with pytest.raises(SystemExit):
        sessions._enforce_proof_video_end_gate(
            "abcd",
            session,
            ["frontend/packages/ui/src/components/NewFeature.svelte"],
            commit_sha=product_commit,
        )

    assert "PROOF VIDEO REQUIRED" in capsys.readouterr().err


def test_proof_video_gate_rejects_forged_passed_manifest_without_receipt(tmp_path: Path) -> None:
    manifest_path = write_passed_manifest(tmp_path)
    (manifest_path.parent / "review-receipt.json").unlink()
    record = {
        "status": "passed",
        "subject_commit": "abc1234",
        "manifest_path": str(manifest_path),
    }

    problems = sessions._proof_video_record_problems(record, "abc1234")

    assert any("invalid frame-review receipt" in problem for problem in problems)


def test_upsert_proof_video_record_clears_matching_pending_entry(tmp_path: Path) -> None:
    manifest_path = write_passed_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    session = {
        "proof_video_pending": [
            {"status": "pending", "subject_commit": "abc1234"},
            {"status": "pending", "subject_commit": "other"},
        ]
    }

    sessions._upsert_proof_video_record(session, tmp_path, manifest)

    assert session["proof_video_pending"] == [{"status": "pending", "subject_commit": "other"}]


def test_proof_video_record_requires_blocker_image_for_failed_review(tmp_path: Path) -> None:
    manifest_path = write_passed_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["review"]["status"] = "render_defect"
    manifest["video_path"] = str(tmp_path / "demo.mp4")
    (tmp_path / "demo.mp4").write_bytes(b"video")

    record = sessions._proof_video_manifest_record(tmp_path, manifest)

    blocker_media = record["blocker_media"]
    assert blocker_media["media_status"] == "missing"
    assert blocker_media["video_path"] == str(tmp_path / "demo.mp4")
    assert blocker_media["upload_command"].startswith("python3 scripts/opencode_response_media.py ")
    assert "image_upload_command" not in blocker_media


def test_proof_video_blocker_media_resolves_repository_relative_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "test-results" / "proof-videos" / "session" / "proof"
    run_dir.mkdir(parents=True)
    video = run_dir / "demo.mp4"
    captions = run_dir / "captions.vtt"
    video.write_bytes(b"video")
    captions.write_text("WEBVTT\n", encoding="utf-8")
    monkeypatch.setattr(spec_demo, "__file__", str(tmp_path / "scripts" / "spec_demo.py"))
    manifest = {
        "spec_id": "proof",
        "review": {"status": "product_defect"},
        "video_path": "test-results/proof-videos/session/proof/demo.mp4",
        "caption_artifact": {
            "path": "test-results/proof-videos/session/proof/captions.vtt",
            "language": "en",
            "label": "Captions",
        },
    }

    blocker_media = sessions._proof_video_blocker_media_record(run_dir, manifest)

    assert blocker_media["media_status"] == "missing"
    assert blocker_media["video_path"] == str(video)
    assert blocker_media["captions_path"] == str(captions)


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


def test_playwright_proof_instructions_require_clean_player_caption_tracks() -> None:
    source = (Path(__file__).resolve().parents[2] / ".claude" / "skills" / "create-demo-video" / "SKILL.md").read_text(encoding="utf-8")

    assert "WebVTT" in source
    assert "burned-in" not in source
