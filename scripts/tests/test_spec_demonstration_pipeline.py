"""Tests for specification demonstration capture and rendering.

Purpose: prove exact CLI and Playwright provenance before review or publication.
Architecture: exercise the local PTY, FFmpeg, manifest, and privacy boundaries.
Privacy: all commands, frames, secrets, and account identifiers are synthetic.
Tests: python3 -m pytest scripts/tests/test_spec_demonstration_pipeline.py.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "spec_demo.py"


def load_module():
    spec = importlib.util.spec_from_file_location("spec_demo", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_playwright_source_requires_exact_run_commit_and_provenance(tmp_path: Path) -> None:
    module = load_module()
    video = tmp_path / "flow.webm"
    video.write_bytes(b"synthetic-video")
    candidates = [
        {
            "command_or_spec": "example.spec.ts",
            "target": "app.dev.openmates.org",
            "deployment_reference": "abc1234",
            "run_id": "run-old",
            "subject_commit": "old1234",
            "artifact_path": str(video),
            "test_account_provenance": "synthetic fixture account",
        },
        {
            "command_or_spec": "example.spec.ts",
            "target": "app.dev.openmates.org",
            "deployment_reference": "abc1234",
            "run_id": "run-1",
            "subject_commit": "abc1234",
            "artifact_path": str(video),
            "test_account_provenance": "synthetic fixture account",
        },
    ]

    selected = module.select_playwright_source(candidates, run_id="run-1", subject_commit="abc1234")

    assert selected["artifact_hash"].startswith("sha256:")
    assert selected["run_id"] == "run-1"
    assert selected["deployment_reference"] == "abc1234"


def test_playwright_source_rejects_missing_required_provenance(tmp_path: Path) -> None:
    module = load_module()
    video = tmp_path / "flow.webm"
    video.write_bytes(b"synthetic-video")

    with pytest.raises(module.DemonstrationError, match="test_account_provenance"):
        module.select_playwright_source(
            [
                {
                    "command_or_spec": "example.spec.ts",
                    "target": "app.dev.openmates.org",
                    "deployment_reference": "abc1234",
                    "run_id": "run-1",
                    "subject_commit": "abc1234",
                    "artifact_path": str(video),
                }
            ],
            run_id="run-1",
            subject_commit="abc1234",
        )


def test_pty_capture_records_exact_argv_output_timing_and_exit_status(tmp_path: Path) -> None:
    module = load_module()
    result = module.capture_pty(
        [sys.executable, "-c", "print('exact terminal output')"],
        run_id="cli-run-1",
        target_environment="local synthetic fixture",
        output_dir=tmp_path,
        test_account_provenance="no account used",
    )

    assert result["argv"] == [sys.executable, "-c", "print('exact terminal output')"]
    assert result["exit_status"] == 0
    transcript = (tmp_path / "transcript.txt").read_text(encoding="utf-8")
    assert "exact terminal output" in transcript
    assert "[exit_status=0]" in transcript
    assert "[run_id=cli-run-1]" in transcript
    assert "[target_environment=local synthetic fixture]" in transcript
    assert "[test_account_provenance=no account used]" in transcript
    assert result["transcript_hash"].startswith("sha256:")
    assert result["event_hash"].startswith("sha256:")
    assert result["artifact_hash"] == result["event_hash"]
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events
    assert events[0]["stream"] == "input"
    assert events[0]["argv"] == [sys.executable, "-c", "print('exact terminal output')"]
    assert all(event["time_seconds"] >= 0 for event in events)


def test_pty_capture_times_out_and_caps_output(tmp_path: Path) -> None:
    module = load_module()
    started = time.monotonic()
    with pytest.raises(module.DemonstrationError, match="timed out"):
        module.capture_pty(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            run_id="timeout",
            target_environment="local synthetic fixture",
            output_dir=tmp_path / "timeout",
            test_account_provenance="no account used",
            timeout_seconds=0.1,
        )
    assert time.monotonic() - started < 2

    with pytest.raises(module.DemonstrationError, match="output limit"):
        module.capture_pty(
            [sys.executable, "-c", "print('x' * 10000)"],
            run_id="output-cap",
            target_environment="local synthetic fixture",
            output_dir=tmp_path / "output-cap",
            test_account_provenance="no account used",
            max_output_bytes=100,
        )


def test_reconstruction_requires_visible_label_and_matching_transcript_hash() -> None:
    module = load_module()
    source = {"transcript_hash": "sha256:exact", "reconstructed": False}

    reconstructed = module.mark_reconstructed(source, displayed_transcript_hash="sha256:exact")

    assert reconstructed["reconstructed"] is True
    assert reconstructed["visible_label"] == "Reconstructed from exact sanitized terminal transcript"
    with pytest.raises(module.DemonstrationError, match="transcript hash"):
        module.mark_reconstructed(source, displayed_transcript_hash="sha256:different")


def test_ffmpeg_terminal_render_and_caption_output(tmp_path: Path) -> None:
    module = load_module()
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("$ openmates demo\nexact terminal output\n", encoding="utf-8")
    captions = tmp_path / "captions.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nThe exact output is visible.\n",
        encoding="utf-8",
    )
    output = tmp_path / "demo.mp4"

    module.render_terminal_video(transcript, captions, output, duration_seconds=1.2)

    assert output.is_file() and output.stat().st_size > 0
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert float(json.loads(probe.stdout)["format"]["duration"]) >= 1.0
    privacy = module.scan_video_privacy(output)
    assert privacy["status"] == "passed"
    assert privacy["decoded_frame_count"] >= 30
    end_frame = module.extract_frame(
        output,
        timestamp_seconds=module.video_metadata(output)["duration_seconds"],
        output_path=tmp_path / "end-frame.png",
    )
    assert Path(end_frame["path"]).is_file()
    assert end_frame["timestamp_seconds"] == module.video_metadata(output)["duration_seconds"]


def test_complete_frame_scan_detects_secret_visible_for_one_frame() -> None:
    module = load_module()
    frames = [b"same", b"safe", b"one-frame-secret", b"safe"]

    result = module.scan_distinct_frames(
        frames,
        ocr=lambda frame: "token sk-proj-synthetic123456789" if frame == b"one-frame-secret" else "safe",
        scan_text=lambda text: ["openai_api_key"] if "sk-proj-" in text else [],
    )

    assert result["decoded_frame_count"] == 4
    assert result["distinct_frame_count"] == 3
    assert result["status"] == "failed"
    assert result["findings"] == [{"frame_index": 2, "types": ["openai_api_key"]}]


def test_complete_frame_scan_fails_closed_when_ocr_errors() -> None:
    module = load_module()

    with pytest.raises(module.DemonstrationError, match="OCR failed"):
        module.scan_distinct_frames(
            [b"frame"],
            ocr=lambda _frame: (_ for _ in ()).throw(RuntimeError("broken OCR")),
            scan_text=lambda _text: [],
        )


def test_text_scan_detects_known_environment_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    secret = "synthetic-webhook-value-without-vendor-pattern"
    monkeypatch.setenv("SYNTHETIC_WEBHOOK_TOKEN", secret)

    assert module.scan_text_with_canonical_scanner(f"visible {secret}")


def test_text_scan_detects_dedicated_discord_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    secret = "https://discord.invalid/api/webhooks/synthetic/private-value"
    monkeypatch.setenv("DISCORD_WEBHOOK_SPEC_DEMOS", secret)

    assert module.scan_text_with_canonical_scanner(f"visible {secret}")


def test_playwright_render_input_must_match_selected_artifact(tmp_path: Path) -> None:
    module = load_module()
    selected_video = tmp_path / "selected.webm"
    other_video = tmp_path / "other.webm"
    selected_video.write_bytes(b"selected")
    other_video.write_bytes(b"other")
    selected = {"artifact_path": str(selected_video), "artifact_hash": module.sha256_file(selected_video)}

    with pytest.raises(module.DemonstrationError, match="selected Playwright artifact"):
        module.verify_playwright_render_input(selected, other_video)


def test_caption_render_strips_source_metadata(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.srt"
    output = tmp_path / "output.mp4"
    captions.write_text("1\n00:00:00,000 --> 00:00:00,800\nSafe caption.\n", encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=320x240:r=10", "-t", "1",
            "-metadata", "comment=private synthetic metadata", str(source),
        ],
        check=True,
        capture_output=True,
    )

    assert module.video_metadata(source)["tags"]["comment"] == "private synthetic metadata"
    module.render_captioned_video(source, captions, output)

    assert "comment" not in module.video_metadata(output)["tags"]


def test_manifest_keeps_raw_and_derived_artifacts_distinct(tmp_path: Path) -> None:
    module = load_module()
    raw = tmp_path / "raw.webm"
    derived = tmp_path / "demo.mp4"
    raw.write_bytes(b"raw")
    derived.write_bytes(b"derived")

    manifest = module.build_artifact_manifest(raw=raw, derived=derived, subject_commit="abc1234")

    assert manifest["raw"]["kind"] == "raw"
    assert manifest["derived"]["kind"] == "derived"
    assert manifest["raw"]["hash"] != manifest["derived"]["hash"]


def test_cli_production_deletes_raw_events_and_records_claim_traceability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    observed = {}
    monkeypatch.setattr(module, "scan_text_sources", lambda _values: {"status": "passed", "findings": []})
    monkeypatch.setattr(module, "render_terminal_video", lambda *_args, **_kwargs: None)

    def prepare(**kwargs):
        observed.update(kwargs)
        assert not (tmp_path / "events.jsonl").exists()
        return {"status": "review_ready"}

    monkeypatch.setattr(module, "prepare_review_artifacts", prepare)

    result = module.produce_cli_demonstration(
        run_dir=tmp_path,
        argv=[sys.executable, "-c", "print('safe output')"],
        spec_id="example",
        subject_commit="abc1234",
        run_id="run-1",
        target_environment="local fixture",
        test_account_provenance="no account used",
        narration_id="NARR-1",
        caption_text="Safe caption.",
        expected_proof="Safe output is visible.",
        acceptance_criteria=["AC-1"],
    )

    assert result["status"] == "review_ready"
    assert observed["acceptance_criteria"] == ["AC-1"]
