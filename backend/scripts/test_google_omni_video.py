#!/usr/bin/env python3
# contract-test-file: tooling
"""
Purpose: Real-call proof for the Gemini Omni video wrapper (text-to-video, clip
         chaining from an extracted last frame, first+last-frame interpolation,
         and an extension of a source video).
Architecture: Runs inside the api container where Vault is available.
Data sources: Gemini API Interactions endpoint (costs money: four short 720p clips).
Tests: Manual verification; writes mp4s and JPEG frames to OUT_DIR.
Usage: docker exec api python /app/backend/scripts/test_google_omni_video.py [out_dir]
"""

from __future__ import annotations

import asyncio
import os
import sys

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.google.omni_video import generate_omni_video
from backend.shared.python_utils.video_frames import extract_frame

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/omni_proof"


def save(name: str, data: bytes) -> str:
    path = os.path.join(OUT_DIR, name)
    with open(path, "wb") as file:
        file.write(data)
    print("wrote", path, len(data), "bytes")
    return path


async def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    secrets = SecretsManager()
    await secrets.initialize()

    clip1 = await generate_omni_video(
        "A single continuous shot: a red paper boat drifts across a calm pond at dawn.",
        duration_seconds=4, resolution="720p", secrets_manager=secrets,
    )
    print("clip1", clip1.duration_seconds, clip1.width, clip1.height, clip1.output_tokens)
    save("clip1.mp4", clip1.mp4)
    last = await extract_frame(clip1.mp4, position="last")
    save("clip1_last.jpg", last)

    clip2 = await generate_omni_video(
        "The scene continues: the paper boat keeps drifting toward the reeds.",
        duration_seconds=4, resolution="720p", first_frame=last,
        secrets_manager=secrets,
    )
    print("clip2", clip2.duration_seconds, clip2.width, clip2.height, clip2.output_tokens)
    save("clip2.mp4", clip2.mp4)
    save("clip2_first.jpg", await extract_frame(clip2.mp4, position="first"))
    clip2_last = await extract_frame(clip2.mp4, position="last")
    save("clip2_last.jpg", clip2_last)

    try:
        clip3 = await generate_omni_video(
            "The boat glides smoothly between the two moments.",
            duration_seconds=4, resolution="720p", first_frame=last, last_frame=clip2_last,
            delivery="uri", secrets_manager=secrets,
        )
        print("interp", clip3.duration_seconds, clip3.width, clip3.height, clip3.output_tokens)
        save("interp.mp4", clip3.mp4)
        save("interp_first.jpg", await extract_frame(clip3.mp4, position="first"))
        save("interp_last.jpg", await extract_frame(clip3.mp4, position="last"))
    except Exception as exc:  # proof script: report and continue
        print("interp FAILED", type(exc).__name__, exc)

    try:
        ext = await generate_omni_video(
            "Continue the scene as the boat reaches the reeds.",
            duration_seconds=3, resolution="720p", source_video=clip1.mp4,
            secrets_manager=secrets,
        )
        print("extend", ext.duration_seconds, ext.width, ext.height, ext.output_tokens)
        save("extend.mp4", ext.mp4)
    except Exception as exc:  # proof script: report and continue
        print("extend FAILED", type(exc).__name__, exc)


if __name__ == "__main__":
    asyncio.run(main())
