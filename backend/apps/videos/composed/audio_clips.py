"""Generate the clips of an ``AudioPlan`` with the providers already in the repo.

Speech: ElevenLabs ``text_to_speech`` (model ``eleven_v4``; pronunciations are
IPA wrapped in slashes inside the text, never XML tags). Sound effects:
ElevenLabs ``generate_sound_effect``. Music: Google Lyria, instrumental. Every
prompt passes the same safety validation the audio and music skills apply
before a provider is called. All clips run concurrently (small semaphore); a
provider failure raises ``AudioGenerationError`` and a safety rejection
``AudioRejectedError``, no clip is ever skipped silently.

A speech clip that turns out longer than its window to the video end is cut
by its Sequence at render time; it is not regenerated. Music length is
guided by the prompt, so the Sequence trims or loops it to the declared
frames; the renderer names every file by its real extension.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import httpx

from backend.apps.audio.pricing import ELEVEN_V4_SPEECH_MODEL, estimate_speech_duration_seconds
from backend.apps.audio.speech_safety import classify_audio_speech_safety
from backend.apps.audio.voice_presets import VOICE_PRESET_TO_ELEVENLABS_ID
from backend.apps.videos.composed.audio_measure import audio_duration_seconds
from backend.apps.videos.composed.audio_plan import AudioEntry, AudioPlan, apply_pronunciations
from backend.shared.providers.e2b_remotion_renderer import RemotionAsset
from backend.shared.providers.elevenlabs import ElevenLabsClient
from backend.shared.providers.google.gemini_music import DEFAULT_LYRIA_MODEL, generate_music_google_lyria
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

logger = logging.getLogger(__name__)

CONCURRENCY = 4
MUSIC_FADE_OUT_SECONDS = 0.5
ELEVENLABS = "ElevenLabs"
GOOGLE = "Google Vertex AI"
EXTENSIONS = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
              "audio/wave": "wav", "audio/mp4": "m4a", "audio/m4a": "m4a", "audio/ogg": "ogg"}
_PROVIDER_ERRORS = (RuntimeError, ValueError, httpx.HTTPError)

SpeechSafety = Callable[..., Awaitable[Any]]
KindStarted = Callable[[str], Any]


class AudioGenerationError(Exception):
    """A provider failed for clip ``id`` of ``kind``; the whole audio step fails (nothing is skipped)."""

    def __init__(self, kind: str, clip_id: str, message: str = "") -> None:
        super().__init__(f"{kind} clip {clip_id!r} could not be generated" + (f": {message[:200]}" if message else ""))
        self.kind = kind
        self.clip_id = clip_id


class AudioRejectedError(Exception):
    """The safety check refused a prompt; ``reason`` is safe to show to the user."""

    def __init__(self, kind: str, clip_id: str, reason: str) -> None:
        super().__init__(f"{kind} clip {clip_id!r} was refused: {reason}")
        self.kind = kind
        self.clip_id = clip_id
        self.reason = reason


@dataclass(frozen=True)
class GeneratedClip:
    """One generated audio file. ``units`` is the billable amount: seconds for speech and sound, 1 per music track."""

    id: str
    kind: str
    data: bytes
    mime_type: str
    duration_seconds: float
    provider: str
    model: str
    units: float

    @property
    def extension(self) -> str:
        return EXTENSIONS.get(self.mime_type.split(";", 1)[0].lower(), "mp3")

    @property
    def file_name(self) -> str:
        return f"{self.id}.{self.extension}"


@dataclass(frozen=True)
class GeneratedAudio:
    """Every clip of a plan, in plan order."""

    clips: tuple[GeneratedClip, ...]

    def of_kind(self, kind: str) -> tuple[GeneratedClip, ...]:
        return tuple(clip for clip in self.clips if clip.kind == kind)


async def default_speech_safety(*, text: str, voice: str, secrets_manager: Any) -> Any:
    """The audio.speak safety check (deterministic rules plus the safeguard model)."""
    return await classify_audio_speech_safety(text=text, voice=voice, accent="en_us", style="natural",
                                              secrets_manager=secrets_manager)


def _check_prompt(media_type: str, entry: AudioEntry, prompt: str) -> None:
    decision = validate_media_generation_request(media_type=media_type, prompt=prompt, request_count=1,
                                                 mode="background" if media_type == "music" else None)
    if not decision.allowed:
        raise AudioRejectedError(entry.kind, entry.id, decision.user_facing_message or "This audio could not be made.")


async def _speech(entry: AudioEntry, client: Any, safety: SpeechSafety, secrets_manager: Any) -> GeneratedClip:
    verdict = await safety(text=entry.text, voice=entry.voice, secrets_manager=secrets_manager)
    if not verdict.approved:
        raise AudioRejectedError(entry.kind, entry.id, verdict.user_facing_message)
    try:
        result = await client.text_to_speech(
            text=apply_pronunciations(entry.text, entry.pronunciations),
            voice_id=VOICE_PRESET_TO_ELEVENLABS_ID[entry.voice], model=ELEVEN_V4_SPEECH_MODEL)
    except _PROVIDER_ERRORS as exc:
        raise AudioGenerationError(entry.kind, entry.id, str(exc)) from exc
    seconds = audio_duration_seconds(result.audio_bytes, result.mime_type) or result.duration_seconds
    if not seconds:
        seconds = estimate_speech_duration_seconds(entry.text)
        logger.warning("Speech clip %s has no measurable length; using the pricing estimate", entry.id)
    return GeneratedClip(entry.id, "speech", result.audio_bytes, result.mime_type, float(seconds), ELEVENLABS,
                         result.model, float(seconds))


async def _sound(entry: AudioEntry, client: Any) -> GeneratedClip:
    _check_prompt("sound_effect", entry, entry.prompt)
    try:
        result = await client.generate_sound_effect(prompt=entry.prompt, duration_seconds=entry.duration_seconds,
                                                    loop=entry.loop)
    except _PROVIDER_ERRORS as exc:
        raise AudioGenerationError(entry.kind, entry.id, str(exc)) from exc
    seconds = audio_duration_seconds(result.audio_bytes, result.mime_type) or entry.duration_seconds
    return GeneratedClip(entry.id, "sound", result.audio_bytes, result.mime_type, float(seconds), ELEVENLABS,
                         result.model, float(seconds))


async def _music(entry: AudioEntry, make_music: Callable[..., Awaitable[Any]], secrets_manager: Any,
                 fps: int) -> GeneratedClip:
    _check_prompt("music", entry, entry.prompt)
    wanted = max(1, math.ceil(entry.duration_frames / fps))
    try:
        result = await make_music(
            prompt=f"{entry.prompt}\nInstrumental only, no vocals, no lyrics. Use case: background music for a video.",
            secrets_manager=secrets_manager, duration_seconds=wanted)
    except _PROVIDER_ERRORS as exc:
        raise AudioGenerationError(entry.kind, entry.id, str(exc)) from exc
    seconds = audio_duration_seconds(result.audio_bytes, result.mime_type)
    if not seconds:
        seconds = float(wanted)
        logger.warning("Music clip %s has no measurable length; the Sequence trims it to %s s", entry.id, wanted)
    return GeneratedClip(entry.id, "music", result.audio_bytes, result.mime_type, float(seconds), GOOGLE,
                         result.model or DEFAULT_LYRIA_MODEL, 1.0)


async def generate_audio(
    plan: AudioPlan, *, secrets_manager: Any, on_kind_started: Optional[KindStarted] = None,
    elevenlabs_client: Any = None, music_generator: Optional[Callable[..., Awaitable[Any]]] = None,
    speech_safety: Optional[SpeechSafety] = None,
) -> GeneratedAudio:
    """Generate every clip of ``plan`` concurrently; ``on_kind_started(kind)`` fires once per kind at its first clip.

    The last three parameters inject the provider clients and the speech safety check (tests need no network).
    """
    client = elevenlabs_client or ElevenLabsClient(secrets_manager=secrets_manager)
    make_music = music_generator or generate_music_google_lyria
    safety = speech_safety or default_speech_safety
    gate = asyncio.Semaphore(CONCURRENCY)
    announced: set[str] = set()

    async def one(entry: AudioEntry) -> GeneratedClip:
        async with gate:
            if on_kind_started and entry.kind not in announced:
                announced.add(entry.kind)
                outcome = on_kind_started(entry.kind)
                if asyncio.iscoroutine(outcome):
                    await outcome
            if entry.kind == "speech":
                return await _speech(entry, client, safety, secrets_manager)
            if entry.kind == "sound":
                return await _sound(entry, client)
            return await _music(entry, make_music, secrets_manager, plan.fps)

    tasks = [asyncio.ensure_future(one(entry)) for entry in plan.entries]
    try:
        clips = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return GeneratedAudio(clips=tuple(clips))


def audio_assets(generated: GeneratedAudio) -> list[RemotionAsset]:
    """The files for ``RemotionSession.upload_audio`` (named by their real extension)."""
    return [RemotionAsset(name=clip.file_name, data=clip.data) for clip in generated.clips]


def audio_tracks(plan: AudioPlan, generated: GeneratedAudio) -> list[dict[str, Any]]:
    """The track list for ``RemotionSession.upload_audio``: one entry per clip for the renderer's Audio sequences.

    Speech and sound play their measured length, cut at the video end; music plays its declared frames, looped
    when the clip is shorter, with a short fade-out.
    """
    clips = {clip.id: clip for clip in generated.clips}
    tracks = []
    for entry in plan.entries:
        clip = clips[entry.id]
        room = plan.video_frames - entry.from_frame
        if entry.kind == "music":
            length, fade, loop = min(entry.duration_frames, room), round(MUSIC_FADE_OUT_SECONDS * plan.fps), True
        else:
            length, fade, loop = min(max(1, math.ceil(clip.duration_seconds * plan.fps)), room), 0, False
        tracks.append({"file": f"audio/{clip.file_name}", "from": entry.from_frame, "durationInFrames": length,
                       "volume": entry.volume, "fadeOutFrames": min(fade, length), "loop": loop})
    return tracks
