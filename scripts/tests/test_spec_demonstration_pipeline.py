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


def test_browser_tutorial_plan_preserves_one_continuous_source_video(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.webm"
    source.write_bytes(b"video")
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    timeline = {
        "contract": {
            "surface": "web",
            "domain": "app.dev.openmates.org",
            "devices": ["web-laptop"],
            "tutorial": {"readingWordsPerSecond": 2, "minimumHoldMs": 1000, "maximumHoldMs": 3000},
            "transcript": [
                {"id": "first", "text": "First state.", "checkpoint": "first-ready", "devices": ["web-laptop"]},
                {"id": "second", "text": "Second stable state.", "checkpoint": "second-ready", "devices": ["web-laptop"]},
            ],
            "assertions": [
                {"id": "first.visible", "checkpoint": "first-ready", "devices": ["web-laptop"]},
                {"id": "second.visible", "checkpoint": "second-ready", "devices": ["web-laptop"]},
            ],
        },
        "events": [
            {"kind": "checkpoint", "id": "first-ready", "at_ms": 1000},
            {"kind": "action", "id": "open-second", "start_ms": 1500, "end_ms": 1700},
            {"kind": "checkpoint", "id": "second-ready", "at_ms": 3000},
        ],
        "assertion_results": [
            {"id": "first.visible", "status": "passed", "at_ms": 1000},
            {"id": "second.visible", "status": "passed", "at_ms": 2200},
        ],
        "checkpoint_frames": [
            {"checkpoint": "first-ready", "path": str(first), "sha256": module.sha256_file(first)},
            {"checkpoint": "second-ready", "path": str(second), "sha256": module.sha256_file(second)},
        ],
    }

    plan = module.build_browser_tutorial_plan(
        timeline,
        source_video=source,
        source_end_seconds=4.0,
        device_profile_name="web-laptop",
        contract_hash="sha256:" + "a" * 64,
        timeline_hash="sha256:" + "b" * 64,
        narration_id="NARR-1",
    )

    assert plan["request"]["renderer"] == "openmates-remotion-browser-v1"
    assert plan["request"]["presentationMode"] == "browser-frame-scaled-full-viewport"
    assert plan["request"]["domain"] == "app.dev.openmates.org"
    assert plan["request"]["sourceHash"] == module.sha256_file(source)
    assert plan["request"]["segments"] == [
        {"kind": "video", "source_from_ms": 850, "source_to_ms": 4000, "duration_ms": 3150},
    ]
    assert plan["caption_segments"] == [
        {"id": "CAP-1", "narration_id": "NARR-1", "text": "First state.", "start": 0.0, "end": 0.65, "claim_ids": ["first.visible"]},
        {"id": "CAP-2", "narration_id": "NARR-1", "text": "Second stable state.", "start": 0.65, "end": 3.15, "claim_ids": ["second.visible"]},
    ]
    assert plan["claim_anchor_times"] == {"first.visible": 0.15, "second.visible": 1.35}
    assert plan["claim_evidence_intervals"] == {
        "first.visible": [[0.15, 0.55]],
        "second.visible": [[1.35, 3.15]],
    }
    assert plan["duration_seconds"] == 3.15

    timeline["contract"]["assertions"][1]["checkpoint"] = "missing"
    with pytest.raises(module.DemonstrationError, match="must map to one captured transcript checkpoint"):
        module.build_browser_tutorial_plan(
            timeline,
            source_video=source,
            source_end_seconds=4.0,
            device_profile_name="web-laptop",
            contract_hash="sha256:" + "a" * 64,
            timeline_hash="sha256:" + "b" * 64,
            narration_id="NARR-1",
        )

    timeline["contract"]["assertions"][1]["checkpoint"] = "second-ready"
    timeline["contract"]["assertions"][0]["checkpoint"] = "second-ready"
    with pytest.raises(module.DemonstrationError, match="transcript checkpoint must carry an assertion"):
        module.build_browser_tutorial_plan(
            timeline,
            source_video=source,
            source_end_seconds=4.0,
            device_profile_name="web-laptop",
            contract_hash="sha256:" + "a" * 64,
            timeline_hash="sha256:" + "b" * 64,
            narration_id="NARR-1",
        )
    timeline["contract"]["assertions"][0]["checkpoint"] = "first-ready"
    plan = module.build_browser_tutorial_plan(
        timeline,
        source_video=source,
        source_end_seconds=4.0,
        device_profile_name="web-laptop",
        contract_hash="sha256:" + "a" * 64,
        timeline_hash="sha256:" + "b" * 64,
        narration_id="NARR-1",
    )
    source.write_bytes(b"changed")
    with pytest.raises(module.DemonstrationError, match="source video is missing or changed"):
        module.render_browser_tutorial(plan["request"], tmp_path / "output.mp4")
    source.write_bytes(b"video")
    first.write_bytes(b"changed-frame")
    with pytest.raises(module.DemonstrationError, match="checkpoint frame is missing or changed"):
        module.build_browser_tutorial_plan(
            timeline,
            source_video=source,
            source_end_seconds=4.0,
            device_profile_name="web-laptop",
            contract_hash="sha256:" + "a" * 64,
            timeline_hash="sha256:" + "b" * 64,
            narration_id="NARR-1",
        )


def test_browser_tutorial_plan_uses_stable_video_intervals_after_actions(tmp_path: Path) -> None:
    module = load_module()
    source_dir = tmp_path / "recording" / "videos"
    source_dir.mkdir(parents=True)
    source = source_dir / "source.webm"
    source.write_bytes(b"video")
    first = tmp_path / "first.png"
    late_second = tmp_path / "late-second.png"
    first.write_bytes(b"first")
    late_second.write_bytes(b"late-second")
    timeline = {
        "contract": {
            "surface": "web",
            "domain": "app.dev.openmates.org",
            "devices": ["web-laptop"],
            "tutorial": {"readingWordsPerSecond": 2, "minimumHoldMs": 1000, "maximumHoldMs": 3000},
            "transcript": [
                {"id": "first", "text": "First state.", "checkpoint": "first-ready", "devices": ["web-laptop"]},
                {"id": "second", "text": "Second stable state.", "checkpoint": "second-ready", "devices": ["web-laptop"]},
            ],
            "assertions": [
                {"id": "first.visible", "checkpoint": "first-ready", "devices": ["web-laptop"]},
                {"id": "second.visible", "checkpoint": "second-ready", "devices": ["web-laptop"]},
            ],
        },
        "events": [
            {"kind": "checkpoint", "id": "first-ready", "at_ms": 1000},
            {"kind": "action", "id": "open-second", "start_ms": 1400, "end_ms": 1600},
            {"kind": "checkpoint", "id": "second-ready", "at_ms": 3000},
        ],
        "assertion_results": [
            {"id": "first.visible", "status": "passed", "at_ms": 1000},
            {"id": "second.visible", "status": "passed", "at_ms": 2000},
        ],
        "checkpoint_frames": [
            {"checkpoint": "first-ready", "path": str(first), "sha256": module.sha256_file(first)},
            {"checkpoint": "second-ready", "path": str(late_second), "sha256": module.sha256_file(late_second)},
        ],
    }

    plan = module.build_browser_tutorial_plan(
        timeline,
        source_video=source,
        source_end_seconds=4.0,
        device_profile_name="web-laptop",
        contract_hash="sha256:" + "a" * 64,
        timeline_hash="sha256:" + "b" * 64,
        narration_id="NARR-1",
    )

    assert plan["request"]["segments"] == [
        {"kind": "video", "source_from_ms": 850, "source_to_ms": 4000, "duration_ms": 3150},
    ]
    assert plan["caption_segments"][1]["start"] == 0.55
    assert plan["claim_anchor_times"]["second.visible"] == 1.15
    assert plan["claim_evidence_intervals"]["second.visible"] == [[1.15, 3.15]]


def test_web_phone_tutorial_plan_uses_iphone_safari_content_viewport(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.webm"
    frame = tmp_path / "ready.png"
    source.write_bytes(b"video")
    frame.write_bytes(b"frame")
    timeline = {
        "contract": {
            "surface": "web",
            "domain": "app.dev.openmates.org",
            "devices": ["web-phone"],
            "tutorial": {"readingWordsPerSecond": 2, "minimumHoldMs": 1000, "maximumHoldMs": 3000},
            "transcript": [
                {"id": "ready", "text": "The phone page is visible.", "checkpoint": "ready", "devices": ["web-phone"]},
            ],
            "assertions": [
                {"id": "phone.visible", "checkpoint": "ready", "devices": ["web-phone"]},
            ],
        },
        "events": [{"kind": "checkpoint", "id": "ready", "at_ms": 1000}],
        "assertion_results": [{"id": "phone.visible", "status": "passed", "at_ms": 800}],
        "checkpoint_frames": [{"checkpoint": "ready", "path": str(frame), "sha256": module.sha256_file(frame)}],
    }

    plan = module.build_browser_tutorial_plan(
        timeline,
        source_video=source,
        source_end_seconds=2.0,
        device_profile_name="web-phone",
        contract_hash="sha256:" + "a" * 64,
        timeline_hash="sha256:" + "b" * 64,
        narration_id="NARR-1",
    )

    assert plan["request"]["viewport"] == {"width": 390, "height": 630}
    assert plan["request"]["output"] == {"width": 390, "height": 844, "fps": 30}
    assert plan["request"]["browserChrome"] == {
        "kind": "iphone13-pro-safari",
        "tabGroupLabel": "Personal",
        "topInset": 128,
        "bottomInset": 86,
        "devicePixelRatio": 3,
    }


def test_node_remotion_renderer_rejects_tampered_browser_inputs(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.webm"
    frame = tmp_path / "frame.png"
    source.write_bytes(b"source")
    frame.write_bytes(b"frame")
    request = {
        "renderer": "openmates-remotion-browser-v1",
        "sourceVideo": str(source),
        "sourceHash": "sha256:" + "0" * 64,
        "segments": [],
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    renderer = ROOT / "tooling/proof-video-remotion/src/render.mjs"

    source_result = subprocess.run(
        ["node", str(renderer), str(request_path), str(tmp_path / "output.mp4")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert source_result.returncode != 0
    assert "source hash changed after planning" in source_result.stderr

    request["sourceHash"] = module.sha256_file(source)
    request["segments"] = [
        {
            "kind": "freeze",
            "source_image": str(frame),
            "source_sha256": "sha256:" + "0" * 64,
            "duration_ms": 1000,
            "cue_id": "ready",
        }
    ]
    request_path.write_text(json.dumps(request), encoding="utf-8")
    frame_result = subprocess.run(
        ["node", str(renderer), str(request_path), str(tmp_path / "output.mp4")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert frame_result.returncode != 0
    assert "accepts only real source-video segments" in frame_result.stderr

    request = {
        "renderer": "openmates-remotion-terminal-v1",
        "sourceVideo": str(source),
        "sourceHash": module.sha256_file(source),
        "sourceSha256": "sha256:" + "0" * 64,
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    terminal_result = subprocess.run(
        ["node", str(renderer), str(request_path), str(tmp_path / "output.mp4")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert terminal_result.returncode != 0
    assert "source hash changed after planning" in terminal_result.stderr


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


def test_prepare_review_artifacts_maps_ordered_claim_intervals_to_action_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"synthetic")
    captions = tmp_path / "captions.vtt"
    captions.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:16.000\nVisible.\n", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "video_metadata",
        lambda _path: {
            "duration_seconds": 16.0,
            "width": 1440,
            "height": 900,
            "sha256": "sha256:" + "b" * 64,
            "has_audio": False,
            "tags": {},
        },
    )
    monkeypatch.setattr(
        module,
        "extract_frame",
        lambda _video_path, *, timestamp_seconds, output_path: {
            "timestamp_seconds": round(timestamp_seconds, 3),
            "path": str(output_path),
            "sha256": "sha256:" + "c" * 64,
        },
    )

    manifest = module.prepare_review_artifacts(
        run_dir=tmp_path,
        video_path=video,
        spec_id="events-search-map-response",
        subject_commit="abc1234",
        narration_id="NARR-1",
        caption_text="Request visible. Cards visible. Map visible. Reload preserves results.",
        captions_path=captions,
        expected_proof="Events search proof.",
        acceptance_criteria=["request-visible"],
        source={"kind": "playwright"},
        narration_audio=module.narration_audio_not_required(),
        caption_segments=[
            {"id": "CAP-1", "narration_id": "NARR-1", "text": "Request visible.", "start": 0.0, "end": 4.0, "claim_ids": ["CLAIM-1"]},
            {"id": "CAP-2", "narration_id": "NARR-1", "text": "Cards visible.", "start": 4.0, "end": 8.0, "claim_ids": ["CLAIM-1"]},
            {"id": "CAP-3", "narration_id": "NARR-1", "text": "Map visible.", "start": 8.0, "end": 13.0, "claim_ids": ["CLAIM-1"]},
            {"id": "CAP-4", "narration_id": "NARR-1", "text": "Reload preserves results.", "start": 13.0, "end": 16.0, "claim_ids": ["CLAIM-1"]},
        ],
        proof_assertions=[
            {"id": "request-visible", "description": "The request is visible."},
            {"id": "events-embed-visible", "description": "The cards are visible."},
            {"id": "map-view-populated", "description": "The map is visible."},
            {"id": "reload-preserves-results", "description": "Reload preserves the map."},
        ],
        action_times=[12.0, 14.0],
    )

    assert [caption["claim_ids"] for caption in manifest["captions"]] == [
        ["request-visible"],
        ["events-embed-visible"],
        ["map-view-populated"],
        ["reload-preserves-results"],
    ]
    assert manifest["captions"][2]["end"] == 12.0
    assert manifest["captions"][3]["start"] == 12.0
    assert manifest["expected_proof"][2]["evidence_intervals"] == [[8.0, 11.9]]
    assert manifest["expected_proof"][3]["evidence_intervals"] == [[12.0, 16.0]]


def test_prepare_review_artifacts_preserves_explicit_caption_claim_intervals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"synthetic")
    captions = tmp_path / "captions.vtt"
    captions.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:12.000\nVisible.\n", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "video_metadata",
        lambda _path: {
            "duration_seconds": 12.0,
            "width": 390,
            "height": 844,
            "sha256": "sha256:" + "b" * 64,
            "has_audio": False,
            "tags": {},
        },
    )
    monkeypatch.setattr(
        module,
        "extract_frame",
        lambda _video_path, *, timestamp_seconds, output_path: {
            "timestamp_seconds": round(timestamp_seconds, 3),
            "path": str(output_path),
            "sha256": "sha256:" + "c" * 64,
        },
    )

    manifest = module.prepare_review_artifacts(
        run_dir=tmp_path,
        video_path=video,
        spec_id="chat-streaming-phone-parity",
        subject_commit="abc1234",
        narration_id="NARR-1",
        caption_text="Request visible. Processing visible. Response chunk visible.",
        captions_path=captions,
        expected_proof="Chat streaming proof.",
        acceptance_criteria=["request", "processing", "composer", "chunk"],
        source={"kind": "playwright"},
        narration_audio=module.narration_audio_not_required(),
        caption_segments=[
            {"id": "CAP-1", "narration_id": "NARR-1", "text": "Request visible.", "start": 0.0, "end": 3.0, "claim_ids": ["request"]},
            {
                "id": "CAP-2",
                "narration_id": "NARR-1",
                "text": "Processing visible.",
                "start": 3.0,
                "end": 7.0,
                "claim_ids": ["processing", "composer"],
            },
            {"id": "CAP-3", "narration_id": "NARR-1", "text": "Response chunk visible.", "start": 7.0, "end": 12.0, "claim_ids": ["chunk"]},
        ],
        proof_assertions=[
            {"id": "request", "description": "The request is visible."},
            {"id": "processing", "description": "The processing state is visible."},
            {"id": "composer", "description": "The composer is visible."},
            {"id": "chunk", "description": "The response chunk is visible."},
        ],
    )

    assert [caption["claim_ids"] for caption in manifest["captions"]] == [
        ["request"],
        ["processing", "composer"],
        ["chunk"],
    ]
    assert manifest["expected_proof"][1]["evidence_intervals"] == [[3.0, 6.9]]
    assert manifest["expected_proof"][2]["evidence_intervals"] == [[3.0, 6.9]]


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


def test_playwright_event_timestamps_follow_trim_and_retiming() -> None:
    module = load_module()

    assert module.scale_source_event_times(
        [-1, 5, 10, 20, "not-a-time"],
        trim_start_seconds=5,
        playback_rate=2,
        output_duration_seconds=8,
    ) == [0.0, 2.5, 7.5]


def test_review_frame_times_prioritize_action_events_over_scene_noise() -> None:
    module = load_module()

    times = module.build_review_frame_times(
        duration_seconds=30,
        interval_seconds=5,
        scene_times=[1.5, 2.8, 4.1, 6.4, 8.7, 11.0, 13.3, 17.2],
        action_times=[12.2],
    )

    assert {11.95, 12.2, 12.45}.issubset(set(times))


def test_review_frame_times_keep_later_action_centers_before_nearby_variants() -> None:
    module = load_module()

    times = module.build_review_frame_times(
        duration_seconds=30,
        interval_seconds=5,
        action_times=[6.0, 12.0, 18.0, 24.0],
    )

    assert {6.0, 12.0, 18.0, 24.0}.issubset(set(times))


def test_review_frame_times_prioritize_claim_anchors_before_transition_ends() -> None:
    module = load_module()

    times = module.build_review_frame_times(
        duration_seconds=27.883,
        interval_seconds=5,
        action_times=[4.0, 14.709, 19.056, 24.316],
        caption_intervals=[(0.0, 4.0), (11.042, 14.709), (16.056, 19.056), (20.983, 24.316)],
        state_change_times=[0.0, 11.042, 16.056, 20.983],
    )

    assert {11.042, 16.056, 20.983}.issubset(set(times))


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


def test_web_phone_source_recording_uses_constrained_safari_viewport() -> None:
    module = load_module()
    profile = module.resolve_device_profile("web-phone")

    module.assert_source_device_profile_dimensions({"width": 390, "height": 630}, profile)
    module.assert_device_profile_dimensions({"width": 390, "height": 844}, profile)
    with pytest.raises(module.DemonstrationError, match="390x630"):
        module.assert_source_device_profile_dimensions({"width": 390, "height": 844}, profile)


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


def test_black_bar_scan_allows_dark_iphone_safari_top_and_bottom_chrome(tmp_path: Path) -> None:
    module = load_module()
    video = tmp_path / "safari-chrome.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=white:s=390x844:r=10",
            "-vf",
            "drawbox=x=0:y=0:w=390:h=128:color=black:t=fill,drawbox=x=0:y=758:w=390:h=86:color=black:t=fill",
            "-t",
            "1",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    metadata = module.video_metadata(video)

    with pytest.raises(module.DemonstrationError, match="letterboxed|pillarboxed"):
        module.assert_no_letterbox_or_pillarbox(video, metadata)
    result = module.assert_no_letterbox_or_pillarbox(
        video,
        metadata,
        device_profile=module.resolve_device_profile("web-phone"),
    )

    assert result["ignored_dark_horizontal_edges"] is True


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


def test_ready_marker_trim_preserves_odd_apple_profile_dimensions(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "iphone-source.mp4"
    output = tmp_path / "iphone-trimmed.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:s=394x852:r=10",
            "-vf", "format=yuv444p,crop=393:852",
            "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv444p", str(source),
        ],
        check=True,
        capture_output=True,
    )

    module.trim_source_to_ready_marker(source, output, ready_timestamp_seconds=0.5, lead_seconds=0)

    metadata = module.video_metadata(output)
    assert (metadata["width"], metadata["height"]) == (393, 852)


def test_ready_marker_trim_starts_at_requested_visible_frame(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "black-then-blue.mp4"
    output = tmp_path / "trimmed.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=320x240:r=10:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=320x240:r=10:d=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            str(source),
        ],
        check=True,
        capture_output=True,
    )

    module.trim_source_to_ready_marker(source, output, ready_timestamp_seconds=1.2, lead_seconds=0)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout

    red, green, blue = raw[:3]
    assert blue > 100
    assert red < 50
    assert green < 50


def test_ready_marker_trim_can_exclude_cleanup_tail(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    output = tmp_path / "trimmed.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=320x240:r=10:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=320x240:r=10:d=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            str(source),
        ],
        check=True,
        capture_output=True,
    )

    metadata = module.trim_source_to_ready_marker(
        source,
        output,
        ready_timestamp_seconds=0,
        end_timestamp_seconds=1.0,
        lead_seconds=0,
    )

    assert metadata["trim_end_seconds"] == 1.0
    assert metadata["trimmed_duration_seconds"] < 1.2


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


def test_cli_production_deletes_raw_events_and_records_claim_traceability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    observed = {}
    monkeypatch.setattr(module, "render_terminal_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "prepare_narration_audio",
        lambda **_kwargs: synthetic_audio_metadata(tmp_path / "narration.wav"),
    )

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
        "capture_pty",
        lambda *_args, **_kwargs: {
            "argv": ["openmates", "demo"],
            "target_environment": "local fixture",
            "run_id": "run-1",
            "exit_status": 1,
            "transcript_hash": "sha256:" + "1" * 64,
            "event_hash": "sha256:" + "2" * 64,
            "artifact_hash": "sha256:" + "2" * 64,
            "test_account_provenance": "no account used",
            "duration_seconds": 0.2,
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
    monkeypatch.setattr(
        module,
        "prepare_narration_audio",
        lambda **_kwargs: synthetic_audio_metadata(tmp_path / "narration.wav"),
    )

    def capture(captured_argv: list[str], **kwargs: object) -> dict[str, object]:
        run_dir = Path(kwargs["output_dir"])
        (run_dir / "events.jsonl").write_text(
            json.dumps({"time_seconds": 0.0, "stream": "input", "argv": captured_argv}) + "\n"
            + json.dumps({"time_seconds": 0.2, "stream": "output", "text": "visible team output\n"}) + "\n",
            encoding="utf-8",
        )
        (run_dir / "transcript.txt").write_text("raw harness transcript\n", encoding="utf-8")
        return {
            "argv": captured_argv,
            "target_environment": kwargs["target_environment"],
            "run_id": kwargs["run_id"],
            "exit_status": 0,
            "transcript_hash": "sha256:" + "1" * 64,
            "event_hash": "sha256:" + "2" * 64,
            "artifact_hash": "sha256:" + "2" * 64,
            "test_account_provenance": kwargs["test_account_provenance"],
            "duration_seconds": 0.2,
        }

    def timeline(**kwargs: object) -> dict[str, object]:
        observed["timeline_argv"] = kwargs["argv"]
        return {
            "states": [{"start": 0.0, "end": 15.0, "text": "$ openmates teams list\nvisible team output\n"}],
            "typing_completed_at": 1.0,
            "first_output_at": 1.2,
            "duration_seconds": 15.0,
        }

    def prepare(**kwargs: object) -> dict[str, str]:
        observed.update(kwargs)
        return {"status": "review_ready"}

    monkeypatch.setattr(module, "capture_pty", capture)
    monkeypatch.setattr(module, "build_cli_terminal_timeline", timeline)
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
    assert observed["timeline_argv"] == ["openmates", "teams", "list", "--json"]
    assert observed["source"]["argv"] == ["node", "scripts/openmates_cli_test_account.mjs", "teams", "list", "--json"]
    assert observed["source"]["display_argv"] == ["openmates", "teams", "list", "--json"]


def test_cli_production_preserves_captured_argv_before_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    secret = "synthetic-sensitive-command-value"
    observed: dict[str, object] = {}
    monkeypatch.setenv("SYNTHETIC_COMMAND_TOKEN", secret)
    monkeypatch.setattr(module, "render_terminal_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "prepare_narration_audio",
        lambda **_kwargs: synthetic_audio_metadata(tmp_path / "narration.wav"),
    )

    def prepare(**kwargs: object) -> dict[str, str]:
        observed.update(kwargs)
        return {"status": "review_ready"}

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
