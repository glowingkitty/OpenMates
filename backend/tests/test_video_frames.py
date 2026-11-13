"""ffmpeg frame extraction and probing on a tiny generated MP4."""

# contract-test-file: infrastructure
import asyncio
import os
import shutil
import subprocess
import tempfile

import pytest

from backend.shared.python_utils.video_frames import (
    VideoFrameError,
    extract_frame,
    probe_video,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")


@pytest.fixture(scope="module")
def tiny_mp4() -> bytes:
    # 2 s, 64x48, 10 fps: red for the first second, blue for the second.
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "t.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x48:r=10:d=1",
             "-f", "lavfi", "-i", "color=blue:s=64x48:r=10:d=1",
             "-filter_complex", "[0][1]concat=n=2:v=1", "-pix_fmt", "yuv420p", out],
            check=True,
        )
        with open(out, "rb") as f:
            return f.read()


def _mean_rgb(jpeg: bytes) -> tuple[int, int, int]:
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "f.jpg")
        with open(src, "wb") as f:
            f.write(jpeg)
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", src, "-vf", "scale=1:1", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    return raw[0], raw[1], raw[2]


def test_probe_reports_measured_values(tiny_mp4):
    info = asyncio.run(probe_video(tiny_mp4))
    assert (info.width, info.height) == (64, 48)
    assert 1.8 <= info.duration_seconds <= 2.2
    assert 9 <= info.fps <= 11


def test_first_and_last_frame_differ_and_are_jpeg(tiny_mp4):
    first = asyncio.run(extract_frame(tiny_mp4, position="first"))
    last = asyncio.run(extract_frame(tiny_mp4, position="last"))
    assert first[:2] == b"\xff\xd8" and last[:2] == b"\xff\xd8"
    r1, _, b1 = _mean_rgb(first)
    r2, _, b2 = _mean_rgb(last)
    assert r1 > 150 > b1
    assert b2 > 150 > r2


def test_invalid_input_raises_typed_error():
    with pytest.raises(VideoFrameError):
        asyncio.run(probe_video(b"not a video"))
    with pytest.raises(VideoFrameError):
        asyncio.run(extract_frame(b"not a video", position="last"))
