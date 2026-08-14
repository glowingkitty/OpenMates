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
    timeline = module.build_cli_terminal_timeline(
        argv=["openmates", "demo"],
        events=[{"time_seconds": 0.8, "stream": "output", "text": "exact terminal output\n"}],
    )
    captions = tmp_path / "captions.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nThe exact output is visible.\n",
        encoding="utf-8",
    )
    output = tmp_path / "demo.mp4"
    audio = write_synthetic_audio(tmp_path / "narration.wav")

    module.render_terminal_video(timeline, captions, audio, output)

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
        "openmates switch-to personal",
        "openmates switch-to ${slug}",
        "openmates teams ${slug} switch-to",
        "openmates chats list",
    ):
        assert command in source
    assert "&& openmates switch-to" not in source


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
    path = tmp_path / "captions.srt"

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
    monkeypatch.setattr(module, "scan_text_sources", lambda _values: {"status": "passed", "findings": []})
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
    )

    assert manifest["captions"][0]["end"] == 15.967
    assert manifest["expected_proof"][0]["evidence_intervals"] == [[0.0, 15.967]]
    request = json.loads((tmp_path / "review-request.json").read_text(encoding="utf-8"))
    assert request["captions"][0]["end"] == 15.967


def test_tutorial_narration_rejects_generic_non_visible_claims(tmp_path: Path) -> None:
    module = load_module()

    with pytest.raises(module.DemonstrationError, match="too generic|visible action"):
        module.write_tutorial_captions(
            tmp_path / "captions.srt",
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


def test_playwright_privacy_scan_does_not_treat_ci_run_id_as_phone_number() -> None:
    module = load_module()
    source = {
        "run_id": "31231661641",
        "subject_commit": "6150eb0",
        "target": "https://app.dev.openmates.org",
        "artifact_path": "/tmp/playwright-31231661641/video.webm",
    }

    payload = module.playwright_source_privacy_payload(source)

    assert "31231661641" not in payload
    assert "6150eb0" in payload
    assert module.scan_text_sources({"source_metadata": payload})["status"] == "passed"


def test_cli_anonymization_uses_visible_typed_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    secret = "synthetic-webhook-value-without-vendor-pattern"
    monkeypatch.setenv("SYNTHETIC_WEBHOOK_TOKEN", secret)
    transcript = tmp_path / "transcript.txt"
    transcript.write_text(f"token={secret}\n", encoding="utf-8")
    capture = {
        "argv": ["example", secret],
        "transcript_hash": module.sha256_file(transcript),
    }

    anonymized = module.anonymize_cli_capture(tmp_path, capture)
    rendered = transcript.read_text(encoding="utf-8")

    assert secret not in rendered
    assert secret[-8:] not in rendered
    assert "[REDACTED_GENERIC_SECRET_1]" in rendered
    assert all(secret not in value for value in anonymized["argv"])
    assert all(secret[-8:] not in value for value in anonymized["argv"])
    assert anonymized["anonymization"]["applied"] is True
    assert anonymized["transcript_hash"] == module.sha256_file(transcript)


def test_cli_anonymization_failure_removes_raw_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    monkeypatch.setattr(
        module,
        "anonymize_cli_capture",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(module.DemonstrationError("scanner failed")),
    )

    with pytest.raises(module.DemonstrationError, match="scanner failed"):
        module.produce_cli_demonstration(
            run_dir=tmp_path,
            argv=[sys.executable, "-c", "print('raw sensitive output')"],
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
            anonymize_sensitive=True,
        )

    assert not (tmp_path / "transcript.txt").exists()
    assert not (tmp_path / "events.jsonl").exists()


@pytest.mark.parametrize("suffix", ["_", "-", "=", "/"])
def test_cli_anonymization_never_retains_secret_punctuation_suffixes(
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


def test_cli_anonymization_preserves_benign_placeholder_shaped_output() -> None:
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


def test_caption_render_strips_source_metadata(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.srt"
    output = tmp_path / "output.mp4"
    audio = write_synthetic_audio(tmp_path / "narration.wav")
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
    module.render_captioned_video(source, captions, audio, output)

    assert "comment" not in module.video_metadata(output)["tags"]
    assert module.video_metadata(output)["has_audio"] is True


def test_caption_render_defaults_to_video_without_audio(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.srt"
    output = tmp_path / "output.mp4"
    captions.write_text("1\n00:00:00,000 --> 00:00:00,800\nSafe caption.\n", encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:s=320x240:r=10", "-t", "1", str(source)],
        check=True,
        capture_output=True,
    )

    module.render_captioned_video(source, captions, None, output)

    assert output.is_file()
    assert module.video_metadata(output)["has_audio"] is False


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
    captions = tmp_path / "captions.srt"
    product_audio = write_synthetic_audio(tmp_path / "product.wav")
    captions.write_text("1\n00:00:00,000 --> 00:00:00,800\nSafe caption.\n", encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:s=320x240:r=10", "-t", "1", str(source)],
        check=True,
        capture_output=True,
    )

    with pytest.raises(module.DemonstrationError, match="Product audio requires explicit narration audio"):
        module.render_captioned_video(source, captions, None, tmp_path / "output.mp4", demo_audio_path=product_audio)


def test_terminal_render_rejects_output_over_35_seconds(tmp_path: Path) -> None:
    module = load_module()
    captions = tmp_path / "captions.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nSafe caption.\n", encoding="utf-8")

    with pytest.raises(module.DemonstrationError, match="35 seconds"):
        module.render_terminal_video(
            {"duration_seconds": 35.1, "states": [{"start": 0.0, "end": 35.1, "text": "$ safe"}]},
            captions,
            None,
            tmp_path / "output.mp4",
        )


def test_playwright_caption_style_scales_down_for_phone_frames() -> None:
    module = load_module()

    phone_style = module._playwright_caption_force_style({"width": 390, "height": 844})
    laptop_style = module._playwright_caption_force_style({"width": 1440, "height": 900})

    assert "FontSize=6" in phone_style
    assert "MarginV=92" in phone_style
    assert "Alignment=2" in phone_style
    assert "FontSize=14" in laptop_style
    assert "MarginV=16" in laptop_style
    assert "Alignment=2" in laptop_style


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
    monkeypatch.setattr(module, "scan_text_sources", lambda _values: {"status": "passed", "findings": []})
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


def test_cli_production_anonymizes_sensitive_argv_before_review(
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
        anonymize_sensitive=True,
    )

    assert result["status"] == "review_ready"
    assert secret not in json.dumps(observed["source"])
    assert secret[-8:] not in json.dumps(observed["source"])
    assert "[REDACTED_" in (tmp_path / "transcript.txt").read_text(encoding="utf-8")
