# contract-test-file: tooling
"""
Purpose: Real-call proof of videos.generate changes: a 4 s Gemini Omni clip made by
         the task's clip producer, then extend_end, extend_start and a structured
         trim run through the change flow's own steps (Omni from the last frame,
         opening still + first/last-frame clip, clip join rendered in the E2B
         sandbox). Directus, storage, billing and publication are not involved;
         the kept clips are read from the output directory instead of S3.
Architecture: backend/apps/videos/tasks/generate_change.py, change_edits.py.
Data sources: Gemini API (three 4 s 720p clips and one still) and E2B renders; costs money.
Tests: backend/tests/test_videos_generate_change.py covers the same flow without network.
Usage: docker exec -w <copy> -e PYTHONPATH=<copy> api python backend/scripts/test_videos_change.py \
       <out_dir> [generate|extend_end|extend_start|trim|all]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace

from backend.apps.videos.generate_request import parse_generate_request
from backend.apps.videos.tasks import generate_change
from backend.apps.videos.tasks.change_edits import apply_clip_edits, clip_frames
from backend.apps.videos.tasks.generate_task import _generate_omni_video
from backend.apps.videos.tasks.video_kept import KeptClip, KeptVideo
from backend.apps.videos.tasks.video_storage import StoredObject
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.video_frames import extract_frame, extract_frame_at, probe_video

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/videos_change_proof"
STEP = sys.argv[2] if len(sys.argv) > 2 else "all"
PROMPT = "A single continuous shot: a red paper boat drifts across a calm pond at dawn, soft mist."


def path(name: str) -> str:
    return os.path.join(OUT_DIR, name)


def save(name: str, data: bytes) -> None:
    with open(path(name), "wb") as file:
        file.write(data)
    print("wrote", path(name), len(data), "bytes")


def load(name: str) -> bytes:
    with open(path(name), "rb") as file:
        return file.read()


def stored(name: str) -> StoredObject:
    return StoredObject(s3_key=name, variant={}, vault_wrapped_aes_key="local", size_bytes=os.path.getsize(path(name)))


class LocalContext(generate_change._Context):
    """The change flow's context with kept files read from the output directory."""

    def __init__(self, secrets: SecretsManager, change: str, instructions: str, kept: KeptVideo) -> None:
        self.task = SimpleNamespace(_secrets_manager=secrets, request=SimpleNamespace(id=f"proof-{change}"))
        self.request = parse_generate_request({"instructions": instructions, "source_video": "generated-videos-proof",
                                               "change": change, "duration_seconds": 4 if change != "edit" else None})
        self.kept, self.log_prefix = kept, f"[proof {change}]"

    async def read(self, item: StoredObject) -> bytes:
        return load(item.s3_key)


async def kept_from(name: str) -> KeptVideo:
    info = await probe_video(load(name))
    item = stored(name)
    return KeptVideo(version=1, made_by="generative", aspect_ratio="16:9", resolution="720p", width=info.width,
                     height=info.height, video=item,
                     clips=(KeptClip(stored=item, duration_in_frames=clip_frames(info.duration_seconds),
                                     trim_before_frames=0, trim_after_frames=0, label="Paper boat"),))


async def frames_at_joins(name: str, mp4: bytes, joins: list[float]) -> None:
    info = await probe_video(mp4)
    print(name, "duration", info.duration_seconds, "size", info.width, info.height)
    for seconds in joins:
        for offset, label in ((-0.1, "before"), (0.05, "after")):
            at = max(0.0, seconds + offset)
            save(f"{name}_join{seconds:.2f}_{label}.jpg", await extract_frame_at(mp4, seconds=at))


async def step_generate(secrets: SecretsManager) -> None:
    task = SimpleNamespace(_secrets_manager=secrets)
    clip = await _generate_omni_video(task, prompt=PROMPT, user_id="proof", source_ids=[], aspect_ratio="16:9",
                                      duration_seconds=4, resolution="720p")
    print("generated", clip.duration_seconds, clip.width, clip.height)
    save("generative.mp4", clip.video_bytes)
    save("generative_first.jpg", await extract_frame(clip.video_bytes, position="first"))


async def step_extend(secrets: SecretsManager, change: str) -> None:
    kept = await kept_from("generative.mp4")
    words = ("The boat keeps drifting toward the reeds as the sun rises." if change == "extend_end"
             else "A still pond in the mist before the boat appears.")
    context = LocalContext(secrets, change, words, kept)
    made = await generate_change._extend(context, seconds=4, at_start=change == "extend_start")
    save(f"{change}.mp4", made.video.mp4)
    save(f"{change}_added_clip.mp4", made.new_clip)
    first_part = made.clips[0].visible_frames / 30
    print(change, "parts", [clip.visible_frames for clip in made.clips], "added", made.clip_seconds, "s",
          "still credits", made.still_credits)
    await frames_at_joins(change, made.video.mp4, [first_part])


async def step_trim(secrets: SecretsManager) -> None:
    kept = await kept_from("generative.mp4")
    text = ("Apply these edits to this video:\n"
            "- Trim the video: remove 0.5 s from the start and 1.0 s from the end")
    clips = apply_clip_edits(text, kept.clips)
    if clips is None:
        raise RuntimeError("the structured trim was not recognised")
    context = LocalContext(secrets, "edit", text, kept)
    video = await generate_change._join(context, clips, {})
    save("trim.mp4", video.mp4)
    info = await probe_video(video.mp4)
    print("trim", json.dumps([(c.trim_before_frames, c.trim_after_frames) for c in clips]),
          "duration", info.duration_seconds)
    save("trim_first.jpg", await extract_frame(video.mp4, position="first"))
    save("source_at_0.5s.jpg", await extract_frame_at(load("generative.mp4"), seconds=0.5))


async def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    secrets = SecretsManager()
    await secrets.initialize()
    try:
        if STEP in ("generate", "all"):
            await step_generate(secrets)
        if STEP in ("extend_end", "all"):
            await step_extend(secrets, "extend_end")
        if STEP in ("extend_start", "all"):
            await step_extend(secrets, "extend_start")
        if STEP in ("trim", "all"):
            await step_trim(secrets)
    finally:
        await secrets.aclose()


if __name__ == "__main__":
    asyncio.run(main())
