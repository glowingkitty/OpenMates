"""Tests for reviewed demonstration Discord delivery and cleanup.

Purpose: confirm delivery before deleting video and bound failed-delivery storage.
Architecture: use a shared multipart helper plus manifest-owned cleanup functions.
Privacy: webhook URLs, response bodies, media, and identifiers are synthetic.
Tests: python3 -m pytest scripts/tests/test_spec_demonstration_discord.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


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
    caption = run_dir / "captions.srt"
    frame = frames / "frame-001.png"
    video.write_bytes(b"synthetic-video")
    transcript.write_text("sanitized transcript", encoding="utf-8")
    caption.write_text("sanitized captions", encoding="utf-8")
    frame.write_bytes(b"synthetic-frame")
    manifest = {
        "spec_id": "example",
        "subject_commit": "abc1234",
        "video_path": str(video),
        "retained_paths": [str(transcript), str(caption)],
        "disposable_artifacts": [
            {"path": str(video), "kind": "derived_video", "sha256": f"sha256:{hashlib.sha256(video.read_bytes()).hexdigest()}"},
            {"path": str(frame), "kind": "review_frame", "sha256": f"sha256:{hashlib.sha256(frame.read_bytes()).hexdigest()}"},
        ],
        "privacy": {"status": "passed"},
        "review": {"status": "passed"},
        "publication": {"status": "pending"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir, manifest


def test_multipart_body_uses_video_content_type_and_no_webhook_value() -> None:
    discord = load_module("discord_webhook")

    body, content_type = discord.build_multipart_body(
        {"content": "Reviewed example at abc1234"},
        [("files[0]", b"video", "demo.mp4")],
    )

    assert content_type.startswith("multipart/form-data; boundary=")
    assert b"Content-Type: video/mp4" in body
    assert b"Reviewed example at abc1234" in body
    assert b"discord.invalid" not in body


def test_text_only_discord_delivery_confirms_message_id() -> None:
    discord = load_module("discord_webhook")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"id":"msg-1"}'

    result = discord.post_message(
        webhook_url="https://discord.invalid/<PLACEHOLDER>",
        payload={"content": "Access-controlled artifact: https://artifacts.invalid/demo"},
        opener=lambda *_args, **_kwargs: Response(),
    )

    assert result == {"message_id": "msg-1"}


def test_confirmed_delivery_deletes_video_and_frames_but_retains_text(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        webhook_url="https://discord.invalid/<PLACEHOLDER>",
        now=now,
        send=lambda **_kwargs: {"message_id": "msg-1", "attachment_id": "att-1"},
    )

    assert result["publication"]["status"] == "delivered"
    assert result["publication"]["message_id"] == "msg-1"
    assert "webhook" not in json.dumps(result).lower()
    assert not Path(manifest["video_path"]).exists()
    assert not (run_dir / "frames" / "frame-001.png").exists()
    assert (run_dir / "transcript.txt").is_file()
    assert (run_dir / "captions.srt").is_file()


def test_failed_delivery_keeps_video_during_retry_window(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        webhook_url="https://discord.invalid/<PLACEHOLDER>",
        now=now,
        send=lambda **_kwargs: None,
    )

    assert result["publication"]["status"] == "publication_pending"
    assert result["publication"]["retry_until"] == "2026-08-07T00:00:00Z"
    assert Path(manifest["video_path"]).is_file()


def test_missing_webhook_records_not_configured_without_value(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)

    result = module.publish_reviewed_video(run_dir, manifest, webhook_url="", now=now)

    assert result["publication"]["status"] == "not_configured"
    assert "webhook_url" not in result["publication"]


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
    assert result["publication"]["failure_reason"] == "Discord delivery did not complete within 24 hours."


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


def test_oversized_video_stays_pending_without_send(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    called = False

    def send(**_kwargs):
        nonlocal called
        called = True
        return {"message_id": "unexpected", "attachment_id": "unexpected"}

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        webhook_url="https://discord.invalid/<PLACEHOLDER>",
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        send=send,
        max_attachment_bytes=1,
    )

    assert called is False
    assert result["publication"]["status"] == "publication_pending"


def test_oversized_video_uses_explicit_approved_artifact_link(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    payloads = []

    result = module.publish_reviewed_video(
        run_dir,
        manifest,
        webhook_url="https://discord.invalid/<PLACEHOLDER>",
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        send=lambda **kwargs: payloads.append(kwargs) or {"message_id": "msg-1"},
        max_attachment_bytes=1,
        approved_artifact_link="https://artifacts.invalid/access-controlled/demo",
        approved_artifact_hosts={"artifacts.invalid"},
    )

    assert result["publication"]["status"] == "delivered"
    assert payloads[0]["content"] is None
    assert "access-controlled" in payloads[0]["payload"]["content"]
    assert not Path(manifest["video_path"]).exists()


def test_artifact_link_requires_configured_https_host(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)

    try:
        module.publish_reviewed_video(
            run_dir,
            manifest,
            webhook_url="https://discord.invalid/<PLACEHOLDER>",
            now=datetime(2026, 8, 6, tzinfo=timezone.utc),
            max_attachment_bytes=1,
            approved_artifact_link="http://public.invalid/demo",
            approved_artifact_hosts={"artifacts.invalid"},
        )
    except module.DemonstrationError as exc:
        assert "approved HTTPS artifact host" in str(exc)
    else:
        raise AssertionError("public artifact URLs must not be accepted")


def test_discord_destination_never_implicitly_uses_dev_nightly() -> None:
    module = load_module("spec_demo")

    assert module.resolve_discord_webhook(
        {"DISCORD_WEBHOOK_SPEC_DEMOS": "", "DISCORD_WEBHOOK_DEV_NIGHTLY": "https://discord.invalid/nightly"}
    ) == ""


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
        webhook_url="https://discord.invalid/<PLACEHOLDER>",
        send=lambda **_kwargs: {"message_id": "msg-1", "attachment_id": "att-1"},
    )

    assert result == {"scanned": 1, "retried": 1, "delivered": 1, "expired_deleted": 0}


def test_publication_sweep_retries_failed_approved_link_delivery(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    run_dir, manifest = demo_run(tmp_path)
    module.publish_reviewed_video(
        run_dir,
        manifest,
        webhook_url="https://discord.invalid/<PLACEHOLDER>",
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        send=lambda **_kwargs: None,
        max_attachment_bytes=1,
        approved_artifact_link="https://artifacts.invalid/access-controlled/demo",
        approved_artifact_hosts={"artifacts.invalid"},
    )
    assert (run_dir / ".publication-link").is_file()

    result = module.sweep_publications(
        tmp_path,
        now=datetime(2026, 8, 6, 0, 15, tzinfo=timezone.utc),
        webhook_url="https://discord.invalid/<PLACEHOLDER>",
        send=lambda **_kwargs: {"message_id": "msg-1"},
        max_attachment_bytes=1,
        approved_artifact_hosts={"artifacts.invalid"},
    )

    assert result["delivered"] == 1
    assert not Path(manifest["video_path"]).exists()
    assert not (run_dir / ".publication-link").exists()


def test_publication_sweep_skips_root_already_claimed_by_another_runner(tmp_path: Path) -> None:
    module = load_module("spec_demo")
    demo_run(tmp_path)
    lock_path = tmp_path / ".publication-sweep.lock"
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        result = module.sweep_publications(
            tmp_path,
            now=datetime(2026, 8, 6, tzinfo=timezone.utc),
            webhook_url="https://discord.invalid/<PLACEHOLDER>",
        )

    assert result == {"scanned": 0, "retried": 0, "delivered": 0, "expired_deleted": 0}
