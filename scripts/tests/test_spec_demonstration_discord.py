"""Tests for reviewed demonstration response-media publication and cleanup.

Purpose: confirm OpenCode response-media publication before deleting video and bound failed-publication storage.
Architecture: use the response-media helper plus manifest-owned cleanup functions.
Privacy: response-media snippets, media, and identifiers are synthetic.
Tests: python3 -m pytest scripts/tests/test_spec_demonstration_discord.py.
"""

# contract-test-file: tooling

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from scripts import spec_demo as canonical_spec_demo


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def demo_run(tmp_path: Path) -> tuple[Path, dict]:
    run_dir = tmp_path / "run-1"
    frames = run_dir / "frames"
    frames.mkdir(parents=True)
    video = run_dir / "demo.mp4"
    transcript = run_dir / "transcript.txt"
    caption = run_dir / "captions.vtt"
    audio = run_dir / "narration-audio.mp3"
    frame = frames / "frame-001.png"
    video.write_bytes(b"synthetic-video")
    transcript.write_text("captured transcript", encoding="utf-8")
    caption.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nSanitized captions.\n", encoding="utf-8")
    audio.write_bytes(b"synthetic-audio")
    frame.write_bytes(b"synthetic-frame")
    source_artifact_hash = f"sha256:{hashlib.sha256(video.read_bytes()).hexdigest()}"
    caption_artifact_hash = f"sha256:{hashlib.sha256(caption.read_bytes()).hexdigest()}"
    proof_contract_hash = "sha256:" + "c" * 64
    request = canonical_spec_demo.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Sanitized captions.", "start": 0.0, "end": 1.0, "claim_ids": ["visible"]}],
        expected_proof=[{"claim_id": "visible", "text": "The proof state is visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": "frames/frame-001.png", "sha256": canonical_spec_demo.sha256_file(frame)}],
        video_metadata={"duration_seconds": 1.0, "sha256": source_artifact_hash, "captions_sha256": caption_artifact_hash, "width": 320, "height": 240},
        narration_audio={
            "status": "passed",
            "provider": "elevenlabs",
            "model": "eleven_flash_v2_5",
            "voice": "warm_neutral",
            "path": str(audio),
            "sha256": f"sha256:{hashlib.sha256(audio.read_bytes()).hexdigest()}",
            "mime_type": "audio/mpeg",
            "duration_seconds": 1.0,
            "reused_from": "",
        },
        proof_contract_hash=proof_contract_hash,
    )
    (run_dir / "review-request.json").write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
    frame_index_hash = str(request["frame_index_hash"])
    proof_group_id = str(request["proof_group_id"])
    receipt = {
        "status": "passed",
        "reviewer_session_id": "ses_reviewer",
        "frame_index_hash": frame_index_hash,
        "proof_contract_hash": proof_contract_hash,
        "proof_group_id": proof_group_id,
        "source_artifact_hash": source_artifact_hash,
        "caption_artifact_hash": caption_artifact_hash,
        "review_request_hash": canonical_spec_demo.review_request_hash(request),
        "subject_commit": "abc1234",
        "correction_round": 0,
        "correction_kind": "none",
        "reviewed_frames": ["frames/frame-001.png"],
        "frame_reviews": [
            {
                "frame": "frames/frame-001.png",
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
        "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame-001.png"], "observation": "Visible."}],
        "incidental_findings": [],
        "workflow": {"requires_user_input": False},
    }
    receipt_path = run_dir / "review-receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    receipt_sha256 = f"sha256:{hashlib.sha256(receipt_path.read_bytes()).hexdigest()}"
    manifest = {
        "schema_version": 2,
        "spec_id": "example",
        "subject_commit": "abc1234",
        "video_path": str(video),
        "video_metadata": {"has_audio": True, "sha256": source_artifact_hash, "captions_sha256": caption_artifact_hash},
        "caption_artifact": {"path": str(caption), "sha256": caption_artifact_hash, "mime_type": "text/vtt", "language": "und", "label": "Captions"},
        "proof_contract_hash": proof_contract_hash,
        "proof_group_id": proof_group_id,
        "narration_audio": {
            "status": "passed",
            "provider": "elevenlabs",
            "model": "eleven_flash_v2_5",
            "voice": "warm_neutral",
            "path": str(audio),
            "sha256": f"sha256:{hashlib.sha256(audio.read_bytes()).hexdigest()}",
            "mime_type": "audio/mpeg",
            "duration_seconds": 1.0,
            "reused_from": "",
        },
        "retained_paths": [str(transcript), str(caption), str(audio)],
        "disposable_artifacts": [
            {"path": str(video), "kind": "derived_video", "sha256": f"sha256:{hashlib.sha256(video.read_bytes()).hexdigest()}"},
            {"path": str(frame), "kind": "review_frame", "sha256": f"sha256:{hashlib.sha256(frame.read_bytes()).hexdigest()}"},
        ],
        "privacy": {"status": "not_applicable", "scan": "disabled"},
        "review": {"status": "passed", "frame_index_hash": frame_index_hash, "receipt_sha256": receipt_sha256},
        "publication": {"status": "pending"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir, manifest


def response_media_result() -> dict[str, object]:
    caption_bytes = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nSanitized captions.\n"
    return {
        "expires_in": 172800,
        "key": "opencode-responses/2026/08/14/demo.mp4",
        "kind": "video",
        "sha256": "sha256:" + hashlib.sha256(b"synthetic-video").hexdigest(),
        "url": "https://media.invalid/demo.mp4",
        "snippets": {
            "markdown": "[Demo](https://media.invalid/demo.mp4)",
            "html": '<video controls><source src="https://media.invalid/demo.mp4" type="video/mp4"><track kind="captions" src="https://media.invalid/captions.vtt" default></video>',
        },
        "captions": {
            "content_type": "text/vtt",
            "expires_in": 172800,
            "key": "opencode-responses/2026/08/14/captions.vtt",
            "sha256": f"sha256:{hashlib.sha256(caption_bytes).hexdigest()}",
            "url": "https://media.invalid/captions.vtt",
        },
    }


def test_response_media_upload_helper_parses_json(monkeypatch, tmp_path: Path) -> None:
    module = load_module("spec_demo")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"synthetic-video")

    def fake_run(command, **kwargs):
        assert command[1].endswith("opencode_response_media.py")
        assert "--output" in command
        assert "--captions" in command
        assert kwargs == {"check": False, "capture_output": True, "text": True}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(response_media_result()), stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    captions = tmp_path / "captions.vtt"
    captions.write_text("WEBVTT\n", encoding="utf-8")
    result = module.upload_response_media(
        path=video,
        captions_path=captions,
        captions_language="und",
        captions_label="Captions",
        alt="Demo",
    )

    assert result["key"] == "opencode-responses/2026/08/14/demo.mp4"


def test_confirmed_response_media_publication_deletes_video_and_frames_but_retains_text(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        now=now,
        uploader=lambda **_kwargs: response_media_result(),
    )

    assert result["publication"]["status"] == "delivered"
    assert result["publication"]["delivery_kind"] == "opencode_response_media"
    assert result["publication"]["response_media_key"] == "opencode-responses/2026/08/14/demo.mp4"
    assert result["publication"]["response_media_html"].startswith("<video")
    assert result["publication"]["snippet_html"].startswith("<video")
    assert result["publication"]["snippet_markdown"].startswith("[Demo]")
    assert not Path(manifest["video_path"]).exists()
    assert not (run_dir / "frames" / "frame-001.png").exists()


def test_publication_rejects_legacy_pass_without_bound_receipt(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    (run_dir / "review-receipt.json").unlink()
    manifest["review"] = {"status": "passed"}

    try:
        module.publish_reviewed_video(
            run_dir,
            manifest,
            now=datetime(2026, 8, 6, tzinfo=timezone.utc),
            uploader=lambda **_kwargs: response_media_result(),
        )
    except module.DemonstrationError as exc:
        assert "hash-bound AI review receipt" in str(exc)
    else:
        raise AssertionError("legacy free-form review unexpectedly reached publication")


def test_publication_rejects_unfinished_privacy_state(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    manifest["privacy"] = {"status": "pending", "scan": "disabled"}

    try:
        module.publish_reviewed_video(
            run_dir,
            manifest,
            now=datetime(2026, 8, 6, tzinfo=timezone.utc),
            uploader=lambda **_kwargs: response_media_result(),
        )
    except module.DemonstrationError as exc:
        assert "finalized proof privacy state" in str(exc)
    else:
        raise AssertionError("unfinished proof privacy state unexpectedly reached publication")


def test_publication_rejects_video_changed_after_review(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    Path(manifest["video_path"]).write_bytes(b"changed-after-review")

    try:
        module.publish_reviewed_video(
            run_dir,
            manifest,
            now=datetime(2026, 8, 6, tzinfo=timezone.utc),
            uploader=lambda **_kwargs: response_media_result(),
        )
    except module.DemonstrationError as exc:
        assert "content hash changed" in str(exc)
    else:
        raise AssertionError("modified proof video unexpectedly reached publication")
    assert (run_dir / "transcript.txt").is_file()
    assert (run_dir / "captions.vtt").is_file()


def test_publication_rejects_captions_changed_after_review(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    Path(manifest["caption_artifact"]["path"]).write_text("WEBVTT\n\nchanged\n", encoding="utf-8")

    try:
        module.publish_reviewed_video(
            run_dir,
            manifest,
            now=datetime(2026, 8, 6, tzinfo=timezone.utc),
            uploader=lambda **_kwargs: response_media_result(),
        )
    except module.DemonstrationError as exc:
        assert "WebVTT captions" in str(exc)
    else:
        raise AssertionError("modified captions unexpectedly reached publication")


def test_publication_rejects_uploaded_caption_hash_mismatch(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    upload = response_media_result()
    upload["captions"] = {**upload["captions"], "sha256": "sha256:" + "0" * 64}

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        uploader=lambda **_kwargs: upload,
    )

    assert result["publication"]["status"] == "publication_pending"
    assert Path(manifest["video_path"]).is_file()


def test_publication_rejects_uploaded_video_hash_mismatch(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    upload = {**response_media_result(), "sha256": "sha256:" + "0" * 64}

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        uploader=lambda **_kwargs: upload,
    )

    assert result["publication"]["status"] == "publication_pending"
    assert Path(manifest["video_path"]).is_file()


def test_delivered_publication_is_idempotent_after_video_cleanup(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    manifest["publication"] = {
        "status": "delivered",
        "delivery_kind": "opencode_response_media",
        "response_media_key": "opencode-responses/2026/08/14/demo.mp4",
    }
    Path(manifest["video_path"]).unlink()

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        uploader=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not republish")),
    )

    assert result["publication"]["status"] == "delivered"
    assert result["publication"]["response_media_key"] == "opencode-responses/2026/08/14/demo.mp4"


def test_failed_response_media_publication_keeps_video_during_retry_window(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)

    def fail_upload(**_kwargs):
        raise RuntimeError("synthetic upload failure")

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        now=now,
        uploader=fail_upload,
    )

    assert result["publication"]["status"] == "publication_pending"
    assert result["publication"]["retry_until"] == "2026-08-07T00:00:00Z"
    assert "response-media upload did not complete" in result["publication"]["failure_reason"]
    assert Path(manifest["video_path"]).is_file()


def test_missing_response_media_snippet_records_pending_without_deleting_video(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)

    result = module.publish_reviewed_video(run_dir, manifest, now=now, uploader=lambda **_kwargs: {"key": "demo"})

    assert result["publication"]["status"] == "publication_pending"
    assert "usable snippets" in result["publication"]["failure_reason"]
    assert Path(manifest["video_path"]).is_file()


def test_pending_video_is_deleted_after_24_hours(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    started = datetime(2026, 8, 6, tzinfo=timezone.utc)
    manifest["publication"] = {
        "status": "publication_pending",
        "first_attempt_at": "2026-08-06T00:00:00Z",
        "retry_until": "2026-08-07T00:00:00Z",
    }

    result = module.expire_pending_video(run_dir, manifest, now=started + timedelta(hours=24))

    assert result["publication"]["status"] == "expired_deleted"
    assert not Path(manifest["video_path"]).exists()
    assert (run_dir / "transcript.txt").is_file()
    assert result["publication"]["failure_reason"] == "OpenCode response-media proof embed did not complete within 24 hours."


def test_cleanup_rejects_paths_outside_manifest_run_directory(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"must remain")
    manifest["disposable_artifacts"].append(
        {"path": str(outside), "kind": "derived_video", "sha256": f"sha256:{hashlib.sha256(outside.read_bytes()).hexdigest()}"}
    )

    try:
        module.delete_disposable_artifacts(run_dir, manifest)
    except module.DemonstrationError as exc:
        assert "outside" in str(exc)
    else:
        raise AssertionError("cleanup must reject paths outside the run directory")
    assert outside.is_file()


def test_cleanup_rejects_retained_or_hash_mismatched_artifacts(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    transcript = run_dir / "transcript.txt"
    manifest["disposable_artifacts"].append(
        {"path": str(transcript), "kind": "review_frame", "sha256": "sha256:wrong"}
    )

    try:
        module.delete_disposable_artifacts(run_dir, manifest)
    except module.DemonstrationError as exc:
        assert "retained" in str(exc) or "hash" in str(exc)
    else:
        raise AssertionError("cleanup must reject retained or hash-mismatched artifacts")
    assert transcript.is_file()


def test_expiry_sweep_processes_due_manifests(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    manifest["publication"] = {
        "status": "publication_pending",
        "first_attempt_at": "2026-08-06T00:00:00Z",
        "retry_until": "2026-08-07T00:00:00Z",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = module.sweep_expired_videos(tmp_path, now=datetime(2026, 8, 7, tzinfo=timezone.utc))

    assert result == {"scanned": 1, "expired_deleted": 1}


def test_publication_sweep_retries_due_pending_delivery(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    manifest["publication"] = {
        "status": "publication_pending",
        "first_attempt_at": "2026-08-06T00:00:00Z",
        "retry_until": "2026-08-07T00:00:00Z",
        "next_retry_at": "2026-08-06T00:15:00Z",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = module.sweep_publications(
        tmp_path,
        now=datetime(2026, 8, 6, 0, 15, tzinfo=timezone.utc),
        uploader=lambda **_kwargs: response_media_result(),
    )

    assert result == {"scanned": 1, "retried": 1, "delivered": 1, "expired_deleted": 0}


def test_publication_sweep_retries_failed_response_media_upload(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)

    def fail_upload(**_kwargs):
        raise RuntimeError("synthetic upload failure")

    module.publish_reviewed_video(
        run_dir,
        manifest,
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        uploader=fail_upload,
    )
    assert Path(manifest["video_path"]).is_file()

    result = module.sweep_publications(
        tmp_path,
        now=datetime(2026, 8, 6, 0, 15, tzinfo=timezone.utc),
        uploader=lambda **_kwargs: response_media_result(),
    )

    assert result["delivered"] == 1
    assert not Path(manifest["video_path"]).exists()


def test_publication_sweep_skips_root_already_claimed_by_another_runner(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    demo_run(tmp_path)
    lock_path = tmp_path / ".publication-sweep.lock"
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        result = module.sweep_publications(
            tmp_path,
            now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        )

    assert result == {"scanned": 0, "retried": 0, "delivered": 0, "expired_deleted": 0}
