"""Tests for specification demonstration capture and rendering.

Purpose: prove exact CLI and Playwright provenance before review or publication.
Architecture: exercise the local PTY, FFmpeg, manifest, and privacy boundaries.
Privacy: all commands, frames, secrets, and account identifiers are synthetic.
Tests: python3 -m pytest scripts/tests/test_spec_demonstration_pipeline.py.
"""

# contract-test-file: tooling

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


def test_resolve_run_artifact_path_accepts_run_local_and_repository_relative_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    monkeypatch.setattr(module, "__file__", str(tmp_path / "scripts" / "spec_demo.py"))
    run_dir = tmp_path / "test-results" / "proof-videos" / "session" / "proof"

    assert module.resolve_run_artifact_path(run_dir, "demo.mp4") == run_dir / "demo.mp4"
    assert module.resolve_run_artifact_path(
        run_dir,
        "test-results/proof-videos/session/proof/demo.mp4",
    ) == run_dir / "demo.mp4"
    assert module.resolve_run_artifact_path(run_dir, run_dir / "demo.mp4") == run_dir / "demo.mp4"
    with pytest.raises(module.DemonstrationError, match="escapes the run directory"):
        module.resolve_run_artifact_path(run_dir, "../outside.mp4")
    with pytest.raises(module.DemonstrationError, match="escapes the run directory"):
        module.resolve_run_artifact_path(run_dir, tmp_path / "outside.mp4")


def write_synthetic_audio(path: Path, *, duration: float = 1.0) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def synthetic_audio_metadata(path: Path) -> dict[str, object]:
    return {
        "status": "passed",
        "provider": "elevenlabs",
        "model": "eleven_flash_v2_5",
        "voice": "warm_neutral",
        "path": str(path),
        "sha256": "sha256:" + "a" * 64,
        "mime_type": "audio/wav",
        "duration_seconds": 1.0,
        "reused_from": "",
    }


def test_tutorial_timeline_uses_attested_checkpoint_frame_and_quantized_hold() -> None:
    module = load_module()
    contract = {
        "transcript": [
            {
                "id": "result",
                "text": "The result is visible inside the OpenMates browser window.",
                "checkpoint": "result-visible",
                "devices": ["web-laptop"],
            }
        ],
        "tutorial": {"readingWordsPerSecond": 2.5, "minimumHoldMs": 1200, "maximumHoldMs": 5000},
    }
    events = [
        {"id": "open-result", "kind": "action", "start_ms": 200, "end_ms": 700},
        {"id": "result-visible", "kind": "checkpoint", "at_ms": 740},
    ]

    timeline = module.build_tutorial_timeline(
        contract=contract,
        events=events,
        device_profile="web-laptop",
        checkpoint_frames={
            "result-visible": {"path": "/proof/result.png", "sha256": "sha256:" + "a" * 64}
        },
        source_duration_ms=740,
    )

    assert timeline == [
        {"kind": "video", "source_from_ms": 0, "source_to_ms": 740, "duration_ms": 733.333},
        {
            "kind": "freeze",
            "source_image": "/proof/result.png",
            "source_sha256": "sha256:" + "a" * 64,
            "duration_ms": 3600.0,
            "cue_id": "result",
        },
    ]


def test_tutorial_timeline_scopes_review_intervals_to_checkpoint_frames() -> None:
    module = load_module()
    contract = {
        "transcript": [
            {
                "id": "welcome",
                "text": "The welcome screen is visible inside the OpenMates browser window.",
                "checkpoint": "welcome-visible",
                "devices": ["web-laptop"],
            },
            {
                "id": "result",
                "text": "Select the next story to show the actionable result card.",
                "checkpoint": "result-visible",
                "devices": ["web-laptop"],
            },
        ],
        "assertions": [
            {
                "id": "welcome.visible",
                "visual": "The welcome screen is visible.",
                "checkpoint": "welcome-visible",
                "devices": ["web-laptop"],
            },
            {
                "id": "result.visible",
                "visual": "The result card is visible.",
                "checkpoint": "result-visible",
                "devices": ["web-laptop"],
            },
        ],
        "tutorial": {"readingWordsPerSecond": 2.5, "minimumHoldMs": 1200, "maximumHoldMs": 5000},
    }
    events = [
        {"id": "welcome-visible", "kind": "checkpoint", "at_ms": 1000},
        {"id": "open-result", "kind": "action", "start_ms": 1000, "end_ms": 1500},
        {"id": "result-visible", "kind": "checkpoint", "at_ms": 1600},
    ]

    timeline = module.build_tutorial_timeline(
        contract=contract,
        events=events,
        device_profile="web-laptop",
        checkpoint_frames={
            "welcome-visible": {"path": "/proof/welcome.png", "sha256": "sha256:" + "a" * 64},
            "result-visible": {"path": "/proof/result.png", "sha256": "sha256:" + "b" * 64},
        },
        source_duration_ms=2000,
    )
    captions, evidence = module.build_tutorial_review_timing(
        contract=contract,
        segments=timeline,
        device_profile="web-laptop",
        narration_id="NARR-1",
    )

    assert [segment["kind"] for segment in timeline] == ["video", "freeze", "video", "freeze", "video"]
    assert [(segment["source_from_ms"], segment["source_to_ms"]) for segment in timeline if segment["kind"] == "video"] == [
        (0, 1000),
        (1000, 1600),
        (1600, 2000),
    ]
    assert [segment["source_image"] for segment in timeline if segment["kind"] == "freeze"] == [
        "/proof/welcome.png",
        "/proof/result.png",
    ]
    assert captions[0]["start"] == 0.0
    assert captions[0]["end"] == 5.0
    assert captions[0]["claim_ids"] == ["welcome.visible"]
    assert captions[1]["start"] == 5.0
    assert captions[1]["end"] == 9.6
    assert captions[1]["claim_ids"] == ["result.visible"]
    assert evidence == {
        "welcome.visible": [[1.0, 5.0]],
        "result.visible": [[5.6, 9.6]],
    }


def test_tutorial_timeline_rejects_missing_frames_and_non_monotonic_checkpoints() -> None:
    module = load_module()
    policy = {"readingWordsPerSecond": 2.5, "minimumHoldMs": 1200, "maximumHoldMs": 5000}
    cue = {
        "id": "first",
        "text": "The first result remains visible in the browser window.",
        "checkpoint": "first-visible",
        "devices": ["web-laptop"],
    }
    with pytest.raises(module.DemonstrationError, match="lacks an attested frame"):
        module.build_tutorial_timeline(
            contract={"transcript": [cue], "tutorial": policy},
            events=[{"id": "first-visible", "kind": "checkpoint", "at_ms": 700}],
            device_profile="web-laptop",
            checkpoint_frames={},
            source_duration_ms=700,
        )

    second_cue = {
        **cue,
        "id": "second",
        "text": "The second result remains visible in the browser window.",
        "checkpoint": "second-visible",
    }
    with pytest.raises(module.DemonstrationError, match="strictly increasing"):
        module.build_tutorial_timeline(
            contract={"transcript": [cue, second_cue], "tutorial": policy},
            events=[
                {"id": "first-visible", "kind": "checkpoint", "at_ms": 800},
                {"id": "second-visible", "kind": "checkpoint", "at_ms": 500},
            ],
            device_profile="web-laptop",
            checkpoint_frames={
                "first-visible": {"path": "/proof/first.png", "sha256": "sha256:" + "a" * 64},
                "second-visible": {"path": "/proof/second.png", "sha256": "sha256:" + "b" * 64},
            },
            source_duration_ms=800,
        )


def test_tutorial_video_duration_matches_quantized_source_frame_range() -> None:
    module = load_module()
    timeline = module.build_tutorial_timeline(
        contract={
            "transcript": [
                {"id": "first", "text": "First state.", "checkpoint": "first", "devices": ["web-laptop"]},
                {"id": "second", "text": "Second state.", "checkpoint": "second", "devices": ["web-laptop"]},
            ],
            "tutorial": {"readingWordsPerSecond": 2.5, "minimumHoldMs": 1200, "maximumHoldMs": 5000},
        },
        events=[
            {"id": "first", "kind": "checkpoint", "at_ms": 2022},
            {"id": "second", "kind": "checkpoint", "at_ms": 6178},
        ],
        device_profile="web-laptop",
        checkpoint_frames={
            "first": {"path": "/proof/first.png", "sha256": "sha256:" + "a" * 64},
            "second": {"path": "/proof/second.png", "sha256": "sha256:" + "b" * 64},
        },
        source_duration_ms=6178,
    )

    video = timeline[2]
    source_frames = round(video["source_to_ms"] * 30 / 1000) - round(video["source_from_ms"] * 30 / 1000)
    assert round(video["duration_ms"] * 30 / 1000) == source_frames


def test_tutorial_review_timing_rejects_unmapped_assertions_and_clamps_encoded_duration() -> None:
    module = load_module()
    contract = {
        "transcript": [
            {
                "id": "result",
                "text": "The result remains visible inside the OpenMates browser window.",
                "checkpoint": "result-visible",
                "devices": ["web-laptop"],
            }
        ],
        "assertions": [
            {
                "id": "result.visible",
                "visual": "The result is visible.",
                "checkpoint": "result-visible",
                "devices": ["web-laptop"],
            },
            {
                "id": "unmapped.visible",
                "visual": "An unmapped result is visible.",
                "checkpoint": "unmapped-visible",
                "devices": ["web-laptop"],
            },
        ],
    }
    segments = [{
        "kind": "freeze",
        "source_image": "/proof/result.png",
        "source_sha256": "sha256:" + "a" * 64,
        "duration_ms": 4000,
        "cue_id": "result",
    }]

    with pytest.raises(module.DemonstrationError, match="Every device-scoped assertion"):
        module.build_tutorial_review_timing(
            contract=contract,
            segments=segments,
            device_profile="web-laptop",
            narration_id="NARR-1",
        )

    assert module.clamp_evidence_to_duration(
        {"result.visible": [[0.0, 4.0]]},
        duration_seconds=3.967,
    ) == {"result.visible": [[0.0, 3.967]]}

    captions = [{"text": "The canonical proof caption."}]
    assert module.validate_tutorial_caption_text("The  canonical proof caption.", captions) == (
        "The canonical proof caption."
    )
    with pytest.raises(module.DemonstrationError, match="does not match"):
        module.validate_tutorial_caption_text("Different retained transcript.", captions)


def test_browser_render_request_binds_domain_viewport_and_input_hashes(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.webm"
    source.write_bytes(b"real playwright pixels")
    checkpoint = tmp_path / "ready.png"
    checkpoint.write_bytes(b"attested checkpoint pixels")
    request = module.build_browser_render_request(
        source_video=source,
        domain="app.dev.openmates.org",
        device_profile="web-laptop",
        segments=[
            {"kind": "video", "source_from_ms": 0, "source_to_ms": 600, "duration_ms": 600},
            {
                "kind": "freeze",
                "source_image": str(checkpoint),
                "source_sha256": module.sha256_file(checkpoint),
                "duration_ms": 1200,
                "cue_id": "ready",
            },
        ],
        contract_hash="sha256:" + "a" * 64,
        timeline_hash="sha256:" + "b" * 64,
    )

    assert request["domain"] == "app.dev.openmates.org"
    assert request["viewport"] == {"width": 1440, "height": 900}
    assert request["source_sha256"] == module.sha256_file(source)
    assert request["renderer"] == "openmates-remotion-browser-v1"
    assert request["output"]["width"] == request["viewport"]["width"]
    assert request["output"]["height"] == request["viewport"]["height"]


def test_browser_proof_uses_only_renderer_domain_chrome() -> None:
    renderer = (ROOT / "tooling/proof-video-remotion/src/BrowserTutorial.tsx").read_text(encoding="utf-8")
    proof_spec = (ROOT / "frontend/apps/web_app/tests/proof-video-architecture.spec.ts").read_text(encoding="utf-8")

    assert "openmates-proof-domain-badge" not in proof_spec
    assert "#22c55e" not in renderer
    assert ">OpenMates</div>" not in renderer
    assert "aria-label=\"New tab\"" in renderer
    assert "maxWidth" in renderer
    assert "Paused for review" in renderer


def test_remotion_renders_real_playwright_pixels_inside_browser_frame(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.webm"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=1440x900:r=30:d=1",
            "-c:v", "libvpx-vp9", "-an", str(source),
        ],
        check=True,
        capture_output=True,
    )
    checkpoint = tmp_path / "checkpoint.png"
    module.extract_frame(source, timestamp_seconds=0.1, output_path=checkpoint)
    request = module.build_browser_render_request(
        source_video=source,
        domain="app.dev.openmates.org",
        device_profile="web-laptop",
        segments=[
            {"kind": "video", "source_from_ms": 0, "source_to_ms": 600, "duration_ms": 600},
            {
                "kind": "freeze",
                "source_image": str(checkpoint),
                "source_sha256": module.sha256_file(checkpoint),
                "duration_ms": 1200,
                "cue_id": "ready",
            },
        ],
        contract_hash="sha256:" + "a" * 64,
        timeline_hash="sha256:" + "b" * 64,
    )

    metadata = module.render_browser_tutorial(request, tmp_path / "browser-tutorial.mp4")

    assert metadata["renderer"] == "openmates-remotion-browser-v1"
    assert metadata["browser_domain"] == "app.dev.openmates.org"
    assert metadata["renderer_source_sha256"] == module.renderer_source_hash()
    assert metadata["browser_runtime"] != "unknown"
    assert metadata["render_request_sha256"] == module.sha256_file(tmp_path / "browser-tutorial.render-request.json")
    assert (metadata["width"], metadata["height"]) == (1440, 900)
    assert metadata["duration_seconds"] == pytest.approx(1.8, abs=0.1)

    def sample(path: Path, x: int, y: int, *, timestamp: float | None = None) -> bytes:
        seek = ["-ss", str(timestamp)] if timestamp is not None else []
        result = subprocess.run(
            [
                "ffmpeg", "-v", "error", *seek, "-i", str(path),
                "-vf", f"crop=1:1:{x}:{y},format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-",
            ],
            check=True,
            capture_output=True,
        )
        return result.stdout

    def sample_page_region(timestamp: float) -> bytes:
        result = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(tmp_path / "browser-tutorial.mp4"),
                "-vf", "crop=120:80:660:430,format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-",
            ],
            check=True,
            capture_output=True,
        )
        return result.stdout

    # The output must be a browser scene, not a full-frame replay: the toolbar
    # area differs from source pixels, while the page area still contains the
    # real Playwright checkpoint scaled into the browser DOM viewport.
    assert sample_page_region(0.1) != sample_page_region(0.4)

    toolbar_pixel = sample(tmp_path / "browser-tutorial.mp4", 720, 60, timestamp=0.9)
    source_toolbar_coordinate = sample(checkpoint, 720, 60)
    assert any(abs(expected - rendered) > 24 for expected, rendered in zip(source_toolbar_coordinate, toolbar_pixel, strict=True))

    expected_page_pixel = sample(checkpoint, 1000, 450)
    rendered_page_pixel = sample(tmp_path / "browser-tutorial.mp4", 963, 478, timestamp=0.9)
    assert all(abs(expected - rendered) <= 28 for expected, rendered in zip(expected_page_pixel, rendered_page_pixel, strict=True))


def test_remotion_freezes_exact_source_frames(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.webm"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=white:s=1440x900:r=30:d=0.5",
            "-f", "lavfi", "-i", "color=c=black:s=1440x900:r=30:d=0.5",
            "-f", "lavfi", "-i", "color=c=red:s=1440x900:r=30:d=0.5",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map", "[v]", "-c:v", "libvpx-vp9", "-an", str(source),
        ],
        check=True,
        capture_output=True,
    )
    checkpoint_paths = []
    for index, timestamp in enumerate((0.1, 0.6, 1.1)):
        checkpoint_path = tmp_path / f"checkpoint-{index}.png"
        module.extract_frame(source, timestamp_seconds=timestamp, output_path=checkpoint_path)
        checkpoint_paths.append(checkpoint_path)
    request = module.build_browser_render_request(
        source_video=source,
        domain="app.dev.openmates.org",
        device_profile="web-laptop",
        segments=[
            {
                "kind": "freeze", "source_image": str(checkpoint_paths[0]),
                "source_sha256": module.sha256_file(checkpoint_paths[0]), "duration_ms": 300, "cue_id": "white",
            },
            {
                "kind": "freeze", "source_image": str(checkpoint_paths[1]),
                "source_sha256": module.sha256_file(checkpoint_paths[1]), "duration_ms": 300, "cue_id": "black",
            },
            {
                "kind": "freeze", "source_image": str(checkpoint_paths[2]),
                "source_sha256": module.sha256_file(checkpoint_paths[2]), "duration_ms": 300, "cue_id": "red",
            },
        ],
        contract_hash="sha256:" + "a" * 64,
        timeline_hash="sha256:" + "b" * 64,
    )
    output = tmp_path / "browser-freezes.mp4"
    module.render_browser_tutorial(request, output)

    def sample(timestamp: float) -> bytes:
        result = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(output),
                "-vf", "crop=1:1:720:500,format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-",
            ],
            check=True,
            capture_output=True,
        )
        return result.stdout

    white, black, red = sample(0.15), sample(0.45), sample(0.75)
    assert min(white) > 200
    assert max(black) < 20
    assert red[0] > red[1] * 2 and red[0] > red[2] * 2



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
            "artifact_sha256": module.sha256_file(video),
            "test_account_provenance": "synthetic fixture account",
        },
        {
            "command_or_spec": "example.spec.ts",
            "target": "app.dev.openmates.org",
            "deployment_reference": "abc1234",
            "run_id": "run-1",
            "subject_commit": "abc1234",
            "artifact_path": str(video),
            "artifact_sha256": module.sha256_file(video),
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


def test_pty_capture_returns_when_child_exits_before_inherited_pty_closes(tmp_path: Path) -> None:
    module = load_module()
    started = time.monotonic()

    result = module.capture_pty(
        [sys.executable, "-c", "import os, time; pid = os.fork(); print('parent done'); os._exit(0) if pid else time.sleep(5)"],
        run_id="inherited-pty",
        target_environment="local synthetic fixture",
        output_dir=tmp_path,
        test_account_provenance="no account used",
        timeout_seconds=2,
    )

    assert result["exit_status"] == 0
    assert time.monotonic() - started < 2
    assert "parent done" in (tmp_path / "transcript.txt").read_text(encoding="utf-8")


def test_reconstruction_requires_visible_label_and_matching_transcript_hash() -> None:
    module = load_module()
    source = {"transcript_hash": "sha256:exact", "reconstructed": False}

    reconstructed = module.mark_reconstructed(source, displayed_transcript_hash="sha256:exact")

    assert reconstructed["reconstructed"] is True
    assert reconstructed["visible_label"] == "Reconstructed from exact terminal transcript"
    with pytest.raises(module.DemonstrationError, match="transcript hash"):
        module.mark_reconstructed(source, displayed_transcript_hash="sha256:different")


def test_ffmpeg_terminal_render_uses_full_terminal_frame(tmp_path: Path) -> None:
    module = load_module()
    timeline = module.build_cli_terminal_timeline(
        argv=["openmates", "demo"],
        events=[{"time_seconds": 0.8, "stream": "output", "text": "exact terminal output\n"}],
    )
    output = tmp_path / "demo.mp4"
    audio = write_synthetic_audio(tmp_path / "narration.wav")

    module.render_terminal_video(timeline, audio, output)

    assert output.is_file() and output.stat().st_size > 0
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert float(json.loads(probe.stdout)["format"]["duration"]) >= 1.0
    metadata = module.video_metadata(output)
    assert (metadata["width"], metadata["height"]) == (1280, 720)
    assert metadata["has_audio"] is True
    end_frame = module.extract_frame(
        output,
        timestamp_seconds=module.video_metadata(output)["duration_seconds"],
        output_path=tmp_path / "end-frame.png",
    )
    assert Path(end_frame["path"]).is_file()
    assert end_frame["timestamp_seconds"] == pytest.approx(
        module.video_metadata(output)["duration_seconds"] - module.END_FRAME_OFFSET_SECONDS,
    )
    between_frame = module.extract_frame(
        output,
        timestamp_seconds=0.515,
        output_path=tmp_path / "between-frame.png",
    )
    assert between_frame["timestamp_seconds"] == pytest.approx(0.533, abs=0.002)


def test_cli_terminal_timeline_types_command_then_replays_real_output_delay() -> None:
    module = load_module()
    timeline = module.build_cli_terminal_timeline(
        argv=["openmates", "plans", "create", "--title", "Tutorial plan"],
        events=[
            {"time_seconds": 1.25, "stream": "output", "text": "Plan PLAN-"},
            {"time_seconds": 1.5, "stream": "output", "text": "123456\nStatus: draft\n"},
        ],
    )

    states = timeline["states"]
    assert states[0]["text"] == "$ openmates plans create --title 'Tutorial plan'"
    assert states[-1]["text"].endswith("Status: draft\n")
    assert timeline["first_output_at"] == pytest.approx(
        timeline["typing_completed_at"] + module.TERMINAL_MAX_OUTPUT_GAP_SECONDS,
    )
    assert timeline["duration_seconds"] >= 15
    assert all("exit_status" not in state["text"] for state in states)
    assert all("run_id" not in state["text"] for state in states)


def test_cli_terminal_timeline_caps_slow_network_gaps() -> None:
    module = load_module()
    timeline = module.build_cli_terminal_timeline(
        argv=["openmates", "teams", "create", "--name", "T95"],
        events=[
            {"time_seconds": 20.0, "stream": "output", "text": "team created\n"},
            {"time_seconds": 55.0, "stream": "output", "text": "credits visible\n"},
        ],
    )

    assert timeline["first_output_at"] == pytest.approx(
        timeline["typing_completed_at"] + module.TERMINAL_MAX_OUTPUT_GAP_SECONDS,
    )
    assert timeline["duration_seconds"] < 20
    assert timeline["states"][-1]["text"].endswith("credits visible\n")


def test_terminal_ass_text_tails_latest_visible_lines() -> None:
    module = load_module()
    text = "\n".join(f"line {index}" for index in range(module.TERMINAL_VISIBLE_LINES + 3))

    rendered = module._terminal_ass_text(text)

    assert "line 0" not in rendered
    assert f"line {module.TERMINAL_VISIBLE_LINES + 2}" in rendered


def test_cli_display_command_replaces_test_harness_and_dist_cli_paths() -> None:
    module = load_module()

    assert module.user_facing_cli_argv([
        "node",
        "scripts/openmates_cli_test_account.mjs",
        "chat",
        "Explain teams",
        "--api-url",
        "https://api.dev.openmates.org",
    ]) == [
        "openmates",
        "chat",
        "Explain teams",
        "--api-url",
        "https://api.dev.openmates.org",
    ]
    assert module.user_facing_cli_argv(["node", "dist/cli.js", "teams", "list"]) == ["openmates", "teams", "list"]
    assert module.user_facing_cli_argv(["node", "./dist/cli.js", "teams", "list"]) == ["openmates", "teams", "list"]
    assert module.user_facing_cli_argv([
        "node",
        "frontend/packages/openmates-cli/dist/cli.js",
        "teams",
        "list",
    ]) == ["openmates", "teams", "list"]
    assert module.user_facing_cli_argv([
        "node",
        "scripts/teams_cli_proof.mjs",
        "--name",
        "CLI Proof Team",
        "--slug",
        "cli-proof-team",
    ]) == ["openmates", "teams", "create", "--name", "CLI Proof Team", "--slug", "cli-proof-team", "--switch"]
    assert module.user_facing_cli_argv(["openmates", "teams", "list"]) == ["openmates", "teams", "list"]


def test_teams_cli_proof_helper_prints_approved_visible_commands() -> None:
    source = (ROOT / "scripts" / "teams_cli_proof.mjs").read_text(encoding="utf-8")

    for command in (
        "openmates teams create --name",
        "openmates switch-to personal",
        "openmates switch-to ${slug}",
        "openmates teams ${slug} switch-to",
        "openmates chats list",
    ):
        assert command in source
    assert "&& openmates switch-to" not in source
    assert "Team created and selected: ${options.slug}" in source


def test_teams_cli_proof_helper_validates_visible_chat_isolation() -> None:
    source = (ROOT / "scripts" / "teams_cli_proof.mjs").read_text(encoding="utf-8")

    assert "function listChatsForIsolation" in source
    assert source.count('printCommand("openmates chats list")') >= 2
    assert "Personal chat list unexpectedly included the team chat" in source
    assert "Team chat list did not include the created team chat" in source
    assert "CHAT_LIST_RETRY_ATTEMPTS" in source
    assert "CHAT_LIST_RETRY_DELAY_MS" in source
    assert "Personal chats listed: created team chat" in source
    assert "Team chats listed: created team chat" in source
    assert "is absent" in source
    assert "is present" in source


def test_tutorial_narration_is_split_into_readable_caption_cues(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "captions.vtt"

    segments = module.write_tutorial_captions(
        path,
        text="First, the terminal shows the plan command being typed at a readable pace. Next, the screen lists the returned plan fields so the reviewer can confirm the created result. The final message explains that the undo command is visible if the plan should be reversed.",
        duration_seconds=15,
        narration_id="NARR-1",
        first_transition_at=7,
    )

    assert [segment["id"] for segment in segments] == ["CAP-1", "CAP-2", "CAP-3"]
    assert segments[0]["start"] == 0
    assert segments[0]["end"] == 7
    assert segments[-1]["end"] == 15
    assert path.read_text(encoding="utf-8").count(" --> ") == 3


def test_prepare_review_artifacts_clamps_captions_to_encoded_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"synthetic")
    captions = tmp_path / "captions.vtt"
    captions.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:15.967\nVisible.\n", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "video_metadata",
        lambda _path: {
            "duration_seconds": 15.967,
            "width": 1280,
            "height": 720,
            "sha256": "sha256:" + "b" * 64,
            "has_audio": False,
            "tags": {},
        },
    )

    def extract(_video_path: Path, *, timestamp_seconds: float, output_path: Path) -> dict[str, object]:
        return {
            "timestamp_seconds": round(timestamp_seconds, 3),
            "path": str(output_path),
            "sha256": "sha256:" + "c" * 64,
        }

    monkeypatch.setattr(module, "extract_frame", extract)

    manifest = module.prepare_review_artifacts(
        run_dir=tmp_path,
        video_path=video,
        spec_id="teams-v1",
        subject_commit="abc1234",
        narration_id="NARR-1",
        caption_text="First, the terminal shows team creation output. Next, visible context output confirms the selected team. Finally, credits output stays visible for review.",
        captions_path=captions,
        expected_proof="The terminal shows team CLI output.",
        acceptance_criteria=["AC-1"],
        source={"kind": "cli", "argv": ["openmates", "teams", "create"]},
        narration_audio=module.narration_audio_not_required(),
        caption_segments=[
            {
                "id": "CAP-1",
                "narration_id": "NARR-1",
                "text": "First, the terminal shows team creation output.",
                "start": 0.0,
                "end": 15.978,
                "claim_ids": ["CLAIM-1"],
            }
        ],
        scene_times=[2.0],
        action_times=[7.0],
        state_change_times=[12.0],
    )

    assert manifest["captions"][0]["end"] == 15.967
    assert manifest["expected_proof"][0]["evidence_intervals"] == [[0.0, 15.967]]
    assert manifest["privacy"] == {
        "status": "not_applicable",
        "scan": "disabled",
        "reason": "proof_video_pii_detection_disabled",
    }
    request = json.loads((tmp_path / "review-request.json").read_text(encoding="utf-8"))
    assert request["captions"][0]["end"] == 15.967
    timestamps = {frame["timestamp_seconds"] for frame in request["frames"]}
    assert {2.0, 6.75, 7.0, 7.25, 11.75, 12.0, 12.25}.issubset(timestamps)


def test_scene_change_detection_extracts_ffmpeg_showinfo_timestamps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"synthetic")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {"returncode": 0, "stdout": "", "stderr": "showinfo pts_time:1.250 x\nshowinfo pts_time:4.5 x\n"},
        )(),
    )

    assert module.detect_scene_change_times(video) == [1.25, 4.5]


def test_tutorial_narration_rejects_generic_non_visible_claims(tmp_path: Path) -> None:
    module = load_module()

    with pytest.raises(module.DemonstrationError, match="too generic|visible action"):
        module.write_tutorial_captions(
            tmp_path / "captions.vtt",
            text="The feature works correctly.",
            duration_seconds=5,
            narration_id="NARR-1",
        )


def test_device_profile_dimensions_reject_landscape_mobile_wrapper() -> None:
    module = load_module()
    profile = module.resolve_device_profile("web-phone")

    with pytest.raises(module.DemonstrationError, match="390x844"):
        module.assert_device_profile_dimensions({"width": 800, "height": 450}, profile)


def test_black_bar_scan_rejects_letterboxed_source(tmp_path: Path) -> None:
    module = load_module()
    video = tmp_path / "letterbox.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=390x844:r=10",
            "-vf",
            "drawbox=x=0:y=160:w=390:h=524:color=white:t=fill",
            "-t",
            "1",
            str(video),
        ],
        check=True,
        capture_output=True,
    )

    with pytest.raises(module.DemonstrationError, match="letterboxed|pillarboxed"):
        module.assert_no_letterbox_or_pillarbox(video, module.video_metadata(video))


@pytest.mark.parametrize("suffix", ["_", "-", "=", "/"])
def test_canonical_redaction_helper_never_retains_secret_punctuation_suffixes(
    suffix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    secret = f"synthetic-command-secret-value{suffix}"
    monkeypatch.setenv("SYNTHETIC_COMMAND_TOKEN", secret)

    result = module.redact_text_with_canonical_scanner(f"token={secret}")

    assert secret not in result["text"]
    assert "synthetic-command-secret-value" not in result["text"]
    assert "[REDACTED_" in result["text"]


def test_canonical_redaction_helper_preserves_benign_placeholder_shaped_output() -> None:
    module = load_module()
    text = "Build completed [BUILD_abc] without findings."

    result = module.redact_text_with_canonical_scanner(text)

    assert result["text"] == text
    assert result["count"] == 0


def test_playwright_render_input_must_match_selected_artifact(tmp_path: Path) -> None:
    module = load_module()
    selected_video = tmp_path / "selected.webm"
    other_video = tmp_path / "other.webm"
    selected_video.write_bytes(b"selected")
    other_video.write_bytes(b"other")
    selected = {"artifact_path": str(selected_video), "artifact_hash": module.sha256_file(selected_video)}

    with pytest.raises(module.DemonstrationError, match="selected Playwright artifact"):
        module.verify_playwright_render_input(selected, other_video)


def test_clean_render_strips_source_metadata_without_caption_or_scale_filters(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    audio = write_synthetic_audio(tmp_path / "narration.wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=320x240:r=10", "-t", "1",
            "-metadata", "comment=private synthetic metadata", str(source),
        ],
        check=True,
        capture_output=True,
    )

    assert module.video_metadata(source)["tags"]["comment"] == "private synthetic metadata"
    observed: list[list[str]] = []
    real_run = module.subprocess.run

    def capture_run(command, **kwargs):
        observed.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", capture_run)
    module.render_clean_video(source, audio, output)

    assert "comment" not in module.video_metadata(output)["tags"]
    assert module.video_metadata(output)["has_audio"] is True
    render_command = next(command for command in observed if command and command[0] == "ffmpeg" and str(output) in command)
    filters = " ".join(render_command)
    assert "subtitles=" not in filters
    assert "scale=" not in filters
    assert "pad=" not in filters
    assert module.video_metadata(output)["width"] == module.video_metadata(source)["width"]
    assert module.video_metadata(output)["height"] == module.video_metadata(source)["height"]


def test_clean_render_defaults_to_video_without_audio(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:s=320x240:r=10", "-t", "1", str(source)],
        check=True,
        capture_output=True,
    )

    module.render_clean_video(source, None, output)

    assert output.is_file()
    assert module.video_metadata(output)["has_audio"] is False


def test_tutorial_captions_are_written_as_webvtt(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "captions.vtt"

    segments = module.write_tutorial_captions(
        path,
        text="The screen shows the first visible action and its controls. The selected result remains clearly visible for careful review. The final screen confirms the expected completed state for the viewer.",
        duration_seconds=9.0,
        narration_id="NARR-1",
    )

    content = path.read_text(encoding="utf-8")
    assert content.startswith("WEBVTT\n\n")
    assert "00:00:00.000 -->" in content
    assert ",000" not in content
    assert len(segments) == 3


def test_ready_marker_trim_uses_fixed_lead_and_preserves_dimensions(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    output = tmp_path / "trimmed.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:s=320x240:r=10", "-t", "2", str(source)],
        check=True,
        capture_output=True,
    )

    result = module.trim_source_to_ready_marker(
        source,
        output,
        ready_timestamp_seconds=1.0,
        lead_seconds=0.15,
    )

    assert result["trim_start_seconds"] == pytest.approx(0.85)
    assert result["ready_timestamp_seconds"] == 1.0
    assert module.video_metadata(output)["duration_seconds"] == pytest.approx(1.15, abs=0.15)
    assert (module.video_metadata(output)["width"], module.video_metadata(output)["height"]) == (320, 240)


def test_playwright_production_enforces_focused_pacing_bounds(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:s=390x844:r=10", "-t", "5", str(source)],
        check=True,
        capture_output=True,
    )
    source_record = {
        "command_or_spec": "example.spec.ts",
        "target": "https://app.dev.openmates.org",
        "deployment_reference": "abc1234",
        "run_id": "run-one",
        "subject_commit": "abc1234",
        "artifact_path": str(source),
        "artifact_sha256": module.sha256_file(source),
        "test_account_provenance": "synthetic fixture account",
    }
    kwargs = {
        "run_dir": tmp_path / "proof",
        "source_video": source,
        "source": source_record,
        "spec_id": "example",
        "subject_commit": "abc1234",
        "narration_id": "NARR-1",
        "caption_text": "The screen shows the first visible action. The selected result remains visible for review. The final screen confirms the expected state.",
        "expected_proof": "The expected state is visible.",
        "acceptance_criteria": ["AC-1"],
        "narration_audio_path": None,
        "device_profile_name": "web-phone",
    }

    with pytest.raises(module.DemonstrationError, match="0.75"):
        module.produce_playwright_demonstration(**kwargs, playback_rate=0.5)
    with pytest.raises(module.DemonstrationError, match="35 seconds"):
        module.produce_playwright_demonstration(**kwargs, playback_rate=0.75, hold_last_frame_seconds=30)


def test_product_audio_requires_explicit_narration_audio(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    product_audio = write_synthetic_audio(tmp_path / "product.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:s=320x240:r=10", "-t", "1", str(source)],
        check=True,
        capture_output=True,
    )

    with pytest.raises(module.DemonstrationError, match="Product audio requires explicit narration audio"):
        module.render_clean_video(source, None, tmp_path / "output.mp4", demo_audio_path=product_audio)


def test_terminal_render_rejects_output_over_35_seconds(tmp_path: Path) -> None:
    module = load_module()
    with pytest.raises(module.DemonstrationError, match="35 seconds"):
        module.render_terminal_video(
            {"duration_seconds": 35.1, "states": [{"start": 0.0, "end": 35.1, "text": "$ safe"}]},
            None,
            tmp_path / "output.mp4",
        )


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


def test_cli_production_preserves_real_terminal_video_and_records_claim_traceability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    observed = {}
    monkeypatch.setattr(module, "render_terminal_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "render_clean_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "media_duration_seconds", lambda _path: 15.0)
    monkeypatch.setattr(
        module,
        "prepare_narration_audio",
        lambda **_kwargs: synthetic_audio_metadata(tmp_path / "narration.wav"),
    )

    def prepare(**kwargs):
        observed.update(kwargs)
        assert (tmp_path / "events.jsonl").exists()
        return {"status": "review_ready"}

    def capture(*, argv: list[str], output_dir: Path, target_environment: str, timeout_seconds: float) -> dict[str, object]:
        video = output_dir / "raw-terminal.mp4"
        transcript = output_dir / "transcript.txt"
        events = output_dir / "events.jsonl"
        video.write_bytes(b"real terminal pixels")
        transcript.write_text("$ openmates apps list\nOpenMates\n", encoding="utf-8")
        events.write_text('{"time_seconds":0.1,"stream":"output","text":"OpenMates"}\n', encoding="utf-8")
        return {
            "argv": argv,
            "target_environment": target_environment,
            "exit_status": 0,
            "video_path": str(video),
            "video_sha256": module.sha256_file(video),
            "transcript_path": str(transcript),
            "transcript_sha256": module.sha256_file(transcript),
            "events_path": str(events),
            "events_sha256": module.sha256_file(events),
            "capture_kind": "real_terminal_screen",
            "reconstructed": False,
        }

    monkeypatch.setattr(module, "capture_real_cli_video", capture)
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
        caption_text="First, the terminal shows the safe local command being captured. Next, the visible output confirms the synthetic result without account data. The final caption keeps review focused on the command screen and retained evidence.",
        expected_proof="Safe output is visible.",
        acceptance_criteria=["AC-1"],
        narration_audio_path=tmp_path / "narration.wav",
    )

    assert result["status"] == "review_ready"
    assert observed["acceptance_criteria"] == ["AC-1"]


def test_cli_production_rejects_failed_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    monkeypatch.setattr(
        module,
        "capture_real_cli_video",
        lambda **_kwargs: {
            "argv": ["openmates", "demo"],
            "target_environment": "local fixture",
            "exit_status": 1,
        },
    )

    with pytest.raises(module.DemonstrationError, match="exited with status 1"):
        module.produce_cli_demonstration(
            run_dir=tmp_path,
            argv=["openmates", "demo"],
            spec_id="example",
            subject_commit="abc1234",
            run_id="run-1",
            target_environment="local fixture",
            test_account_provenance="no account used",
            narration_id="NARR-1",
            caption_text="First, the terminal shows the safe local command being captured. Next, the visible output confirms the synthetic result without account data. The final caption keeps review focused on the command screen and retained evidence.",
            expected_proof="Safe output is visible.",
            acceptance_criteria=["AC-1"],
            narration_audio_path=None,
        )


def test_cli_production_renders_user_facing_openmates_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    observed: dict[str, object] = {}
    monkeypatch.setattr(module, "render_terminal_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "render_clean_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "media_duration_seconds", lambda _path: 15.0)
    monkeypatch.setattr(
        module,
        "prepare_narration_audio",
        lambda **_kwargs: synthetic_audio_metadata(tmp_path / "narration.wav"),
    )

    def capture(*, argv: list[str], output_dir: Path, target_environment: str, timeout_seconds: float) -> dict[str, object]:
        video = output_dir / "raw-terminal.mp4"
        transcript = output_dir / "transcript.txt"
        events = output_dir / "events.jsonl"
        video.write_bytes(b"real terminal pixels")
        events.write_text(
            json.dumps({"time_seconds": 0.0, "stream": "input", "argv": argv}) + "\n"
            + json.dumps({"time_seconds": 0.2, "stream": "output", "text": "visible team output\n"}) + "\n",
            encoding="utf-8",
        )
        transcript.write_text("raw harness transcript\n", encoding="utf-8")
        return {
            "argv": argv,
            "target_environment": target_environment,
            "exit_status": 0,
            "video_path": str(video),
            "video_sha256": module.sha256_file(video),
            "transcript_path": str(transcript),
            "transcript_sha256": module.sha256_file(transcript),
            "events_path": str(events),
            "events_sha256": module.sha256_file(events),
            "capture_kind": "real_terminal_screen",
            "reconstructed": False,
        }

    def prepare(**kwargs: object) -> dict[str, str]:
        observed.update(kwargs)
        return {"status": "review_ready"}

    monkeypatch.setattr(module, "capture_real_cli_video", capture)
    monkeypatch.setattr(module, "prepare_review_artifacts", prepare)

    result = module.produce_cli_demonstration(
        run_dir=tmp_path,
        argv=["node", "scripts/openmates_cli_test_account.mjs", "teams", "list", "--json"],
        spec_id="teams-cli",
        subject_commit="abc1234",
        run_id="run-1",
        target_environment="local fixture",
        test_account_provenance="synthetic account",
        narration_id="NARR-1",
        caption_text="First, the terminal shows the teams list command as a normal openmates command. Next, the visible output confirms the team result in the terminal. The final caption keeps review focused on realistic user-facing CLI output.",
        expected_proof="The regular openmates teams command is visible.",
        acceptance_criteria=["AC-1"],
        narration_audio_path=tmp_path / "narration.wav",
    )

    assert result["status"] == "review_ready"
    assert observed["source"]["argv"] == ["node", "scripts/openmates_cli_test_account.mjs", "teams", "list", "--json"]
    assert observed["source"]["display_argv"] == ["openmates", "teams", "list", "--json"]
    assert observed["source"]["reconstructed"] is False


def test_cli_production_preserves_captured_argv_before_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    secret = "synthetic-sensitive-command-value"
    observed: dict[str, object] = {}
    monkeypatch.setenv("SYNTHETIC_COMMAND_TOKEN", secret)
    monkeypatch.setattr(module, "render_terminal_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "render_clean_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "media_duration_seconds", lambda _path: 15.0)
    monkeypatch.setattr(
        module,
        "prepare_narration_audio",
        lambda **_kwargs: synthetic_audio_metadata(tmp_path / "narration.wav"),
    )

    def prepare(**kwargs: object) -> dict[str, str]:
        observed.update(kwargs)
        return {"status": "review_ready"}

    def capture(*, argv: list[str], output_dir: Path, target_environment: str, timeout_seconds: float) -> dict[str, object]:
        video = output_dir / "raw-terminal.mp4"
        transcript = output_dir / "transcript.txt"
        events = output_dir / "events.jsonl"
        video.write_bytes(b"real terminal pixels")
        transcript.write_text(f"$ openmates demo {secret}\ncreated\n", encoding="utf-8")
        events.write_text('{"time_seconds":0.1,"stream":"output","text":"created"}\n', encoding="utf-8")
        return {
            "argv": argv,
            "target_environment": target_environment,
            "exit_status": 0,
            "video_path": str(video),
            "video_sha256": module.sha256_file(video),
            "transcript_path": str(transcript),
            "transcript_sha256": module.sha256_file(transcript),
            "events_path": str(events),
            "events_sha256": module.sha256_file(events),
            "capture_kind": "real_terminal_screen",
            "reconstructed": False,
        }

    monkeypatch.setattr(module, "capture_real_cli_video", capture)
    monkeypatch.setattr(module, "prepare_review_artifacts", prepare)

    result = module.produce_cli_demonstration(
        run_dir=tmp_path,
        argv=[sys.executable, "-c", "print('created')", secret],
        spec_id="example",
        subject_commit="abc1234",
        run_id="run-1",
        target_environment="local fixture",
        test_account_provenance="no account used",
        narration_id="NARR-1",
        caption_text="First, the terminal shows the safe local command being captured. Next, the visible output confirms the synthetic result without account data. The final caption keeps review focused on the command screen and retained evidence.",
        expected_proof="Safe output is visible.",
        acceptance_criteria=["AC-1"],
        narration_audio_path=tmp_path / "narration.wav",
    )

    assert result["status"] == "review_ready"
    assert secret in json.dumps(observed["source"])
    assert secret in (tmp_path / "transcript.txt").read_text(encoding="utf-8")
