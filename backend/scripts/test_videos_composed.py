#!/usr/bin/env python3
# contract-test-file: tooling
"""
Purpose: Real proof of the composed-video engine of videos.generate (author model + Remotion on E2B).
Architecture: Runs inside the api container; calls backend.apps.videos.composed.author.compose_video
    with Vault-backed provider and E2B credentials, then optionally joins the result with itself
    through build_clip_join_source + render_source_directly.
Data sources: Two synthetic PNG pictures drawn with Pillow; no user data.
Tests: Manual verification - writes video.mp4, thumbnail.png and Composition.tsx (plus joined.mp4)
    to --out and prints the timeline, attempts, usage and sandbox seconds. Costs a few author
    calls and a few sandbox minutes.
Usage: docker exec api python /app/backend/scripts/test_videos_composed.py --out /tmp/videos-composed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from backend.apps.videos.composed.author import compose_video
from backend.apps.videos.composed.models import ComposedInput, ComposedRequest, ComposeFailure
from backend.apps.videos.composed.prompt import mp4_duration_seconds
from backend.apps.videos.composed.source import build_clip_join_source, render_source_directly
from backend.core.api.app.utils.secrets_manager import SecretsManager

INSTRUCTION = ("8 second product teaser: title 'OpenMates', then each picture full-screen with a caption "
               "('Your AI team' for the first, 'Private by design' for the second), then an outro "
               "'Try it today'.")


def _picture(size: tuple[int, int], colours: tuple[str, str], label: str) -> bytes:
    image = Image.new("RGB", size, colours[0])
    draw = ImageDraw.Draw(image)
    width, height = size
    for step in range(0, max(size), 60):
        draw.line([(step, 0), (0, step)], fill=colours[1], width=18)
    draw.ellipse([width * 0.3, height * 0.25, width * 0.7, height * 0.75], fill="white", outline=colours[1], width=12)
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(24, height // 8))
    draw.text((width / 2, height / 2), label, fill=colours[1], font=font, anchor="mm")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _inputs() -> tuple[ComposedInput, ...]:
    first = _picture((1600, 1000), ("#1d4ed8", "#f59e0b"), "TEAM")
    second = _picture((900, 1200), ("#065f46", "#f43f5e"), "LOCK")
    return (
        ComposedInput(name="input-1.png", content=first, mime_type="image/png", width=1600, height=1000,
                      title="Team illustration"),
        ComposedInput(name="input-2.png", content=second, mime_type="image/png", width=900, height=1200,
                      title="Privacy illustration"),
    )


def _usage(video) -> list[dict]:
    return [{"model": item.model, "provider": item.provider, "step": item.step,
             "input_tokens": item.input_tokens, "output_tokens": item.output_tokens} for item in video.usage]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/videos-composed")
    parser.add_argument("--instruction", default=INSTRUCTION)
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--duration", type=int, default=8)
    parser.add_argument("--skip-join", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    stages: list[str] = []

    async def on_stage(stage: str) -> None:
        stages.append(stage)
        print(f"stage: {stage}", flush=True)

    try:
        inputs = _inputs()
        for item in inputs:
            (out / item.name).write_bytes(item.content)
        request = ComposedRequest(instructions=args.instruction, aspect_ratio=args.aspect_ratio,
                                  duration_seconds=args.duration, inputs=inputs)
        started = time.monotonic()
        try:
            video = await compose_video(request, secrets_manager=secrets_manager, task_id="proof-composed",
                                        on_stage=on_stage)
        except ComposeFailure as exc:
            print(json.dumps({"status": "fail", "code": exc.code, "error": exc.message[-3000:], "stages": stages}))
            return 1
        (out / "video.mp4").write_bytes(video.mp4)
        (out / "thumbnail.png").write_bytes(video.thumbnail_png)
        (out / video.filename).write_text(video.source, encoding="utf-8")
        summary = {"status": "pass", "seconds": round(time.monotonic() - started, 1), "stages": stages,
                   "attempts": video.attempts, "author_model": video.author_model, "usage": _usage(video),
                   "sandbox_seconds": [round(value, 1) for value in video.sandbox_seconds],
                   "mp4_bytes": len(video.mp4), "mp4_seconds": mp4_duration_seconds(video.mp4),
                   "size": [video.width, video.height], "frames": video.duration_in_frames,
                   "timeline": video.timeline}
        if not args.skip_join:
            frames = video.duration_in_frames
            clips = [{"name": "clip-1.mp4", "duration_in_frames": frames, "trim_before_frames": 0,
                      "trim_after_frames": 30, "label": "First take"},
                     {"name": "clip-2.mp4", "duration_in_frames": frames, "trim_before_frames": 60,
                      "trim_after_frames": 0, "label": "Second take"}]
            clip_inputs = [ComposedInput(name=clip["name"], content=video.mp4, mime_type="video/mp4",
                                         width=video.width, height=video.height, kind="video_clip")
                           for clip in clips]
            joined = await render_source_directly(build_clip_join_source(clips, aspect_ratio=args.aspect_ratio),
                                                  clip_inputs, secrets_manager=secrets_manager,
                                                  task_id="proof-composed-join")
            (out / "joined.mp4").write_bytes(joined.mp4)
            summary["join"] = {"frames": joined.duration_in_frames, "mp4_seconds": mp4_duration_seconds(joined.mp4),
                               "sandbox_seconds": [round(value, 1) for value in joined.sandbox_seconds],
                               "timeline": joined.timeline}
    finally:
        await secrets_manager.aclose()
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
