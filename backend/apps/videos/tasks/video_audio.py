"""Audio clips of a composed video as kept material (assertion videos-generate.change.same-video-next-version).

A stored version keeps every distinct generated clip next to the video, encrypted like the copies of the input
pictures (``video_storage.upload_video_files`` ``extra`` objects named ``audio-<n>``), and lists them in its kept
record (``KeptAudio``: stored object, content hash, kind, measured length, mime type). A later change reads them
back as reusable clips, so unchanged narration, effects and music are neither generated again nor charged again.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Sequence

from backend.apps.videos.composed.audio_clips import GeneratedClip
from backend.apps.videos.composed.audio_step import UsedClip
from backend.apps.videos.tasks.video_kept import KeptAudio
from backend.apps.videos.tasks.video_storage import StoredObject, StoredVideo

AUDIO_PREFIX = "audio-"


def _distinct(used: Sequence[UsedClip]) -> list[UsedClip]:
    return list({item.hash: item for item in used}.values())


def audio_extra(used: Sequence[UsedClip]) -> dict[str, tuple[bytes, str, str]]:
    """Upload entries (name → bytes, extension, mime type) for ``upload_video_files(extra=...)``, one per distinct clip."""
    return {f"{AUDIO_PREFIX}{number}": (item.clip.data, item.clip.extension, item.clip.mime_type)
            for number, item in enumerate(_distinct(used), start=1)}


def kept_audio(stored: StoredVideo, used: Sequence[UsedClip]) -> tuple[KeptAudio, ...]:
    """Kept-record entries of the clips uploaded with ``audio_extra``."""
    return tuple(KeptAudio(
        stored=stored.object(f"{AUDIO_PREFIX}{number}"), hash=item.hash, kind=item.clip.kind,
        duration_seconds=item.clip.duration_seconds, mime_type=item.clip.mime_type, provider=item.clip.provider,
        model=item.clip.model,
    ) for number, item in enumerate(_distinct(used), start=1))


async def recall_audio(kept: Sequence[KeptAudio], read: Callable[[StoredObject], Awaitable[bytes]]
                       ) -> tuple[UsedClip, ...]:
    """The kept clips of the previous version as reusable clips (``read`` decrypts one stored object)."""
    clips = []
    for item in kept:
        data = await read(item.stored)
        units = 1.0 if item.kind == "music" else item.duration_seconds
        clip = GeneratedClip(id=f"kept-{item.hash[:12]}", kind=item.kind, data=data, mime_type=item.mime_type,
                             duration_seconds=item.duration_seconds, provider=item.provider, model=item.model,
                             units=units)
        clips.append(UsedClip(hash=item.hash, clip=clip))
    return tuple(clips)
