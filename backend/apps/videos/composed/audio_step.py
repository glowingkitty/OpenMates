"""The audio step of one composed-video request: reuse what is already generated, generate only what is new.

``AudioStep`` sits between the sandbox check and the render of every round
(``rounds.py``). A clip is identified by a hash of its defining content (kind,
text or prompt, voice, pronunciations, duration for sound and music; not its
id, start or volume). Within one request a later round never generates a clip
again that an earlier round made, and a change of an existing video starts with
the clips of its previous version (``previous``), so only new or changed clips
reach a provider and are billed. Order of work for the clips still missing: the
balance check (``afford``), the progress stage (``on_kinds``), generation. The
clips generated in this request are kept in ``generated`` for billing.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Sequence

from backend.apps.videos.composed.audio_clips import (
    GeneratedAudio,
    GeneratedClip,
    audio_assets,
    audio_tracks,
    generate_audio,
)
from backend.apps.videos.composed.audio_plan import KINDS, AudioEntry, AudioPlan
from backend.apps.videos.tasks.generate_billing import estimate_audio_credits

LABEL_CHARS = 40

AffordCheck = Callable[[int], Awaitable[None]]
KindsCallback = Callable[[tuple[str, ...]], Awaitable[None]]
ResumeCallback = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class UsedClip:
    """A clip of the final plan with its content hash (what a later change can reuse)."""

    hash: str
    clip: GeneratedClip


@dataclass(frozen=True)
class PreparedAudio:
    """Everything the renderer needs for one round, plus the clips of the plan with their hashes."""

    plan: AudioPlan
    generated: GeneratedAudio
    used: tuple[UsedClip, ...]
    assets: list[Any]
    tracks: list[dict[str, Any]]


def clip_hash(entry: AudioEntry, fps: int) -> str:
    """Hash of everything that decides the generated sound of ``entry``."""
    if entry.kind == "speech":
        content: list[Any] = [entry.text, entry.voice, [list(pair) for pair in entry.pronunciations]]
    elif entry.kind == "sound":
        content = [entry.prompt, entry.duration_seconds, entry.loop]
    else:
        content = [entry.prompt, max(1, math.ceil(entry.duration_frames / fps))]
    return hashlib.sha256(json.dumps([entry.kind, content], ensure_ascii=False).encode("utf-8")).hexdigest()


def _label(entry: AudioEntry) -> str:
    source = entry.text if entry.kind == "speech" else entry.prompt
    return " ".join(source.split())[:LABEL_CHARS]


def timeline_audio(prepared: PreparedAudio) -> list[dict[str, Any]]:
    """The ``audio`` list of the stored timeline: what really plays, in frames at the timeline fps."""
    result = []
    for entry, track in zip(prepared.plan.entries, prepared.tracks):
        item: dict[str, Any] = {"id": entry.id, "kind": entry.kind, "label": _label(entry), "from": entry.from_frame,
                                "durationInFrames": track["durationInFrames"]}
        if entry.kind == "speech":
            item["text"] = entry.text
        result.append(item)
    return result


@dataclass
class AudioStep:
    """Per-request audio state; one instance serves every round (and keeps the cache between them)."""

    secrets_manager: Any
    previous: Sequence[UsedClip] = ()
    afford: Optional[AffordCheck] = None
    on_kinds: Optional[KindsCallback] = None
    resume: Optional[ResumeCallback] = None
    generate: Callable[..., Awaitable[GeneratedAudio]] = generate_audio
    generated: dict[str, GeneratedClip] = field(default_factory=dict)
    _known: dict[str, GeneratedClip] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._known.update({item.hash: item.clip for item in self.previous})

    async def prepare(self, plan: AudioPlan) -> PreparedAudio:
        """Clips for every entry of ``plan``; only entries without an equal known clip reach a provider."""
        hashes = {entry.id: clip_hash(entry, plan.fps) for entry in plan.entries}
        missing: list[AudioEntry] = []
        queued: set[str] = set()
        for entry in plan.entries:
            digest = hashes[entry.id]
            if digest not in self._known and digest not in queued:
                queued.add(digest)
                missing.append(entry)
        if missing:
            await self._generate(AudioPlan(entries=tuple(missing), fps=plan.fps, video_frames=plan.video_frames),
                                 hashes)
        clips = tuple(dataclasses.replace(self._known[hashes[entry.id]], id=entry.id) for entry in plan.entries)
        generated = GeneratedAudio(clips=clips)
        used = tuple(UsedClip(hashes[clip.id], clip) for clip in clips)
        return PreparedAudio(plan=plan, generated=generated, used=used, assets=audio_assets(generated),
                             tracks=audio_tracks(plan, generated))

    async def _generate(self, missing: AudioPlan, hashes: dict[str, str]) -> None:
        if self.afford is not None:
            await self.afford(estimate_audio_credits(missing))
        if self.on_kinds is not None:
            await self.on_kinds(tuple(kind for kind in KINDS if missing.of_kind(kind)))
        made = await self.generate(missing, secrets_manager=self.secrets_manager)
        for clip in made.clips:
            digest = hashes[clip.id]
            self._known[digest] = clip
            self.generated[digest] = clip
        if self.resume is not None:
            await self.resume()
