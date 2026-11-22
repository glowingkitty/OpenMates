"""Tests for muxing in-page proof audio into Playwright videos (scripts/proof_video_audio.py)."""
# contract-test-file: tooling

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proof_video_audio  # noqa: E402 - the scripts folder is added to the path above

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")


def test_mux_command_delays_each_segment_and_copies_the_video(monkeypatch) -> None:
    monkeypatch.setattr(proof_video_audio, "ffmpeg", lambda: "ffmpeg")
    command = proof_video_audio.mux_command(Path("v.webm"), [(Path("a.webm"), 1.25), (Path("b.webm"), -0.5)],
                                            Path("out.webm"))
    graph = command[command.index("-filter_complex") + 1]
    assert "[1:a]aresample=48000,adelay=1250:all=1[a1]" in graph
    assert "[2:a]aresample=48000,atrim=start=0.500,asetpts=PTS-STARTPTS[a2]" in graph
    assert "amix=inputs=2:normalize=0:duration=longest" in graph
    assert command[command.index("-c:v") + 1] == "copy"


def test_unreadable_manifest_is_an_error(tmp_path: Path) -> None:
    manifest = tmp_path / proof_video_audio.MANIFEST_NAME
    manifest.write_text("{not json")
    with pytest.raises(proof_video_audio.MuxError):
        proof_video_audio.mux(manifest)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, timeout=120)


@needs_ffmpeg
def test_mux_places_audio_at_its_recorded_time(tmp_path: Path) -> None:
    _ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=160x120:d=6:r=10", "-c:v", "libvpx", str(tmp_path / "video-0.webm"))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libopus", str(tmp_path / "audio-0-a.webm"))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:duration=1", "-c:a", "libopus", str(tmp_path / "audio-0-b.webm"))
    manifest = tmp_path / proof_video_audio.MANIFEST_NAME
    manifest.write_text(json.dumps({"schema_version": 1, "pages": [{
        "video": "video-0.webm", "created_epoch_ms": 10_000,
        "segments": [{"file": "audio-0-a.webm", "start_epoch_ms": 11_000},
                     {"file": "audio-0-b.webm", "start_epoch_ms": 13_500}]}]}))
    [output] = proof_video_audio.mux_all(tmp_path)
    assert output.name == "video-0-with-audio.webm"
    assert proof_video_audio.loudness(output, 0.0, 0.8) < -50
    assert proof_video_audio.loudness(output, 1.2, 0.5) > -30
    assert proof_video_audio.loudness(output, 2.3, 1.0) < -50
    assert proof_video_audio.loudness(output, 3.7, 0.5) > -30
    assert proof_video_audio.mux_all(tmp_path) == []  # already muxed and up to date
