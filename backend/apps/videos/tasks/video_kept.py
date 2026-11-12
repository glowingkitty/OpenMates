"""What a videos.generate result keeps server-readable so it can be changed later.

The chat stores a result client-encrypted only, so the server cannot read the
composition or the clips of a video afterwards. Every stored version therefore
also writes one kept record (assertion videos-generate.change.same-video-next-version):

- the version it describes, how it was made, format and size;
- the stored MP4 of this version (to take its first or last frame);
- a composed video: its composition source and encrypted copies of the input
  pictures (with names, kinds, titles and the original embed ids/refs), so a
  change renders again from the original pictures even after an upload window,
  and the generated audio clips (encrypted, with content hash, kind, measured
  length and mime type), so a change generates only new or changed clips;
- a generative video: its clips in play order, each an encrypted stored MP4
  with its full length and the frames trimmed at its start and end.

Retention: unlike images.modify (24 hours in the cache), changing a video days
later is normal, so the record is a durable S3 object next to the video, at a
key derived from the owner and the embed version, encrypted with the owner's
Vault key. Its key, like every kept file, is in the embed's file index, so it
is deleted together with the video. A missing record means the video cannot be
changed; the change then fails explicitly and is not charged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.apps.videos.tasks.video_storage import CHATFILES, StoredObject

KEPT_FORMAT = 1
MAX_KEPT_SOURCE_CHARS = 120_000
MADE_BY = ("generative", "composed")


class KeptVideoError(RuntimeError):
    """A kept record exists but cannot be read back; the change fails instead of guessing."""


@dataclass(frozen=True)
class KeptInput:
    """A picture the composition shows, as a stored encrypted copy."""

    stored: StoredObject
    name: str  # sandbox file name, e.g. "input-1.jpg"
    mime_type: str
    width: int
    height: int
    title: str
    kind: str  # "image" | "search_result"
    embed_id: str
    ref: str


@dataclass(frozen=True)
class KeptAudio:
    """One generated audio clip of a composed video, identified by the hash of its defining content."""

    stored: StoredObject
    hash: str
    kind: str  # "speech" | "sound" | "music"
    duration_seconds: float
    mime_type: str
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class KeptClip:
    """One generated clip of a generative video, in play order."""

    stored: StoredObject
    duration_in_frames: int  # full clip length at 30 fps
    trim_before_frames: int
    trim_after_frames: int
    label: str
    model: str = ""

    @property
    def visible_frames(self) -> int:
        return self.duration_in_frames - self.trim_before_frames - self.trim_after_frames


@dataclass(frozen=True)
class KeptVideo:
    version: int
    made_by: str
    aspect_ratio: str
    resolution: str
    width: int
    height: int
    video: StoredObject
    source: Optional[str] = None
    inputs: tuple[KeptInput, ...] = field(default_factory=tuple)
    clips: Optional[tuple[KeptClip, ...]] = None  # None once the clips were replaced by an authored composition
    audio: tuple[KeptAudio, ...] = field(default_factory=tuple)  # one per distinct clip content

    def object_keys(self) -> list[str]:
        """Every stored file the record refers to (all are in the embed's file index)."""
        keys = [self.video.s3_key, *(item.stored.s3_key for item in self.inputs),
                *(clip.stored.s3_key for clip in self.clips or ()), *(item.stored.s3_key for item in self.audio)]
        return list(dict.fromkeys(keys))


def kept_record_key(*, user_id: str, embed_id: str, version: int) -> str:
    return f"{user_id}/videos_kept/{embed_id}/v{version}.json"


def _to_json(kept: KeptVideo) -> str:
    return json.dumps({
        "format": KEPT_FORMAT, "version": kept.version, "made_by": kept.made_by, "aspect_ratio": kept.aspect_ratio,
        "resolution": kept.resolution, "width": kept.width, "height": kept.height, "video": kept.video.to_json(),
        "source": kept.source,
        "inputs": [{"stored": item.stored.to_json(), "name": item.name, "mime_type": item.mime_type,
                    "width": item.width, "height": item.height, "title": item.title, "kind": item.kind,
                    "embed_id": item.embed_id, "ref": item.ref} for item in kept.inputs],
        "clips": None if kept.clips is None else [
            {"stored": clip.stored.to_json(), "duration_in_frames": clip.duration_in_frames,
             "trim_before_frames": clip.trim_before_frames, "trim_after_frames": clip.trim_after_frames,
             "label": clip.label, "model": clip.model} for clip in kept.clips],
        "audio": [{"stored": item.stored.to_json(), "hash": item.hash, "kind": item.kind,
                   "duration_seconds": item.duration_seconds, "mime_type": item.mime_type,
                   "provider": item.provider, "model": item.model} for item in kept.audio],
    })


def _from_json(text: str) -> KeptVideo:
    try:
        data = json.loads(text)
        if data["format"] != KEPT_FORMAT or data["made_by"] not in MADE_BY:
            raise ValueError("unknown kept record format")
        clips = data.get("clips")
        return KeptVideo(
            version=int(data["version"]), made_by=data["made_by"], aspect_ratio=str(data["aspect_ratio"]),
            resolution=str(data["resolution"]), width=int(data["width"]), height=int(data["height"]),
            video=StoredObject.from_json(data["video"]), source=data.get("source"),
            inputs=tuple(KeptInput(
                stored=StoredObject.from_json(item["stored"]), name=str(item["name"]),
                mime_type=str(item["mime_type"]), width=int(item["width"]), height=int(item["height"]),
                title=str(item.get("title") or ""), kind=str(item["kind"]), embed_id=str(item["embed_id"]),
                ref=str(item["ref"]),
            ) for item in data.get("inputs") or []),
            clips=None if clips is None else tuple(KeptClip(
                stored=StoredObject.from_json(clip["stored"]), duration_in_frames=int(clip["duration_in_frames"]),
                trim_before_frames=int(clip["trim_before_frames"]), trim_after_frames=int(clip["trim_after_frames"]),
                label=str(clip.get("label") or ""), model=str(clip.get("model") or ""),
            ) for clip in clips),
            audio=tuple(KeptAudio(
                stored=StoredObject.from_json(item["stored"]), hash=str(item["hash"]), kind=str(item["kind"]),
                duration_seconds=float(item["duration_seconds"]), mime_type=str(item["mime_type"]),
                provider=str(item.get("provider") or ""), model=str(item.get("model") or ""),
            ) for item in data.get("audio") or []),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise KeptVideoError("The kept material of this video is unreadable") from exc


async def remember_video(task: Any, *, s3_service: Any, kept: KeptVideo, user_id: str, embed_id: str,
                         vault_key_id: str) -> str:
    """Encrypt the record with the owner's Vault key and store it; return its object key."""
    if kept.source is not None and len(kept.source) > MAX_KEPT_SOURCE_CHARS:
        raise KeptVideoError("The composition is too large to keep")
    ciphertext, _ = await task._encryption_service.encrypt_with_user_key(_to_json(kept), vault_key_id)
    if not ciphertext:
        raise KeptVideoError("The kept material of this video could not be encrypted")
    key = kept_record_key(user_id=user_id, embed_id=embed_id, version=kept.version)
    await s3_service.upload_file(CHATFILES, key, ciphertext.encode("utf-8"), "application/octet-stream")
    return key


async def recall_video(task: Any, *, s3_service: Any, bucket_name: str, user_id: str, embed_id: str, version: int,
                       vault_key_id: str) -> Optional[KeptVideo]:
    """The kept record of ``embed_id`` at ``version``, or ``None`` when none is kept."""
    encrypted = await s3_service.get_file(
        bucket_name=bucket_name, object_key=kept_record_key(user_id=user_id, embed_id=embed_id, version=version))
    if not encrypted:
        return None
    plaintext = await task._encryption_service.decrypt_with_user_key(encrypted.decode("utf-8"), vault_key_id)
    if not plaintext:
        raise KeptVideoError("The kept material of this video could not be decrypted")
    kept = _from_json(plaintext)
    if kept.version != version:
        raise KeptVideoError("The kept material belongs to another version of this video")
    return kept
