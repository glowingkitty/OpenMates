#!/usr/bin/env python3
"""Write finalized Playwright video timestamps before CI artifact upload.

The test processor uses this sidecar to map absolute spec event timestamps to
WebM presentation timestamps without taking screenshots during recording.
Run only after the Playwright process exits and closes its video files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    videos = []
    for path in sorted(args.video_root.rglob("*.webm")):
        stat = path.stat()
        videos.append({
            "path": path.as_posix(),
            "finalized_at_epoch_ms": stat.st_mtime_ns / 1_000_000,
            "size_bytes": stat.st_size,
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"schema_version": 1, "videos": videos}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
