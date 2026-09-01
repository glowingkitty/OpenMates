"""Tests for finalized Playwright video timing manifests.

The manifest must preserve each video path, byte size, and filesystem write
timestamp so post-recording extraction can map absolute test timestamps.
"""

import json
import subprocess
from pathlib import Path


# contract-test: tooling
def test_writes_finalized_video_metadata(tmp_path: Path) -> None:
    video_root = tmp_path / "frontend" / "apps" / "web_app" / "test-results"
    video = video_root / "flow" / "video.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    output = tmp_path / "playwright-video-timing.json"

    subprocess.run(
        ["python3", "scripts/write_playwright_video_timing.py", str(video_root), str(output)],
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["videos"] == [{
        "path": video.as_posix(),
        "finalized_at_epoch_ms": video.stat().st_mtime_ns / 1_000_000,
        "size_bytes": 5,
    }]
