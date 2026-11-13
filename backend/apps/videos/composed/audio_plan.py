"""The ``audio`` export of a composition: validation into an ``AudioPlan``.

The author may export ``audio`` (a plain literal array like ``parts``) to
declare spoken narration, sound effects and one instrumental background
track. The sandbox bundle step reports it; ``build_audio_plan`` validates it
without any provider call, so a plan that cannot work (too long, overlapping
speech, unknown voice) goes back to the author through the normal correction
round before anything is generated or paid. An absent or empty ``audio`` is a
silent video, exactly as before.

Entries (``from`` is a frame):
- ``{id, kind: 'speech', text, voice?, from, pronunciations?: [{word, ipa}], volume?}``
- ``{id, kind: 'sound', prompt, durationSeconds, from, volume?, loop?}``
- ``{id, kind: 'music', prompt, from, durationInFrames, volume?}``
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Optional

from backend.apps.audio.pricing import estimate_speech_duration_seconds
from backend.apps.audio.voice_presets import VOICE_PRESET_TO_ELEVENLABS_ID
from backend.apps.videos.composed.contract import ID_PATTERN, InvalidCompositionError

MAX_SPEECH_LINES = 12
MAX_SPEECH_CHARS_TOTAL = 1500
MAX_SPEECH_CHARS_LINE = 400
MAX_SOUNDS = 8
MAX_MUSIC = 1
MAX_PROMPT_CHARS = 400
MIN_SOUND_SECONDS = 0.5
MAX_SOUND_SECONDS = 10.0
MAX_PRONUNCIATIONS = 8
MAX_IPA_CHARS = 60
MAX_WORD_CHARS = 60
DEFAULT_VOICE = next(iter(VOICE_PRESET_TO_ELEVENLABS_ID))
DEFAULT_VOLUME = {"speech": 1.0, "sound": 0.7, "music": 0.25}
KINDS = ("speech", "sound", "music")
_FORBIDDEN_IPA = re.compile(r"[/<>\n\r]")


@dataclass(frozen=True)
class AudioEntry:
    """One validated audio declaration. Fields that do not apply to the kind stay empty."""

    id: str
    kind: str
    from_frame: int
    volume: float
    text: str = ""
    voice: str = ""
    pronunciations: tuple[tuple[str, str], ...] = ()
    prompt: str = ""
    duration_seconds: float = 0.0
    duration_frames: int = 0
    loop: bool = False


@dataclass(frozen=True)
class AudioPlan:
    """Validated entries in declaration order plus the video they belong to."""

    entries: tuple[AudioEntry, ...]
    fps: int
    video_frames: int

    def of_kind(self, kind: str) -> tuple[AudioEntry, ...]:
        return tuple(entry for entry in self.entries if entry.kind == kind)

    @property
    def is_empty(self) -> bool:
        return not self.entries


def apply_pronunciations(text: str, pronunciations: tuple[tuple[str, str], ...]) -> str:
    """Replace whole-word occurrences of each word by ``/ipa/`` (Eleven v4 IPA notation; no XML tags)."""
    for word, ipa in pronunciations:
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", lambda _match, ipa=ipa: f"/{ipa}/", text)
    return text


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text_field(entry: dict[str, Any], key: str, where: str, limit: int) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidCompositionError(f"{where}.{key} must be a non-empty string")
    if len(value) > limit:
        raise InvalidCompositionError(f"{where}.{key} has {len(value)} characters; at most {limit} are allowed")
    return value.strip()


def _pronunciations(entry: dict[str, Any], where: str, text: str) -> tuple[tuple[str, str], ...]:
    raw = entry.get("pronunciations")
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_PRONUNCIATIONS:
        raise InvalidCompositionError(f"{where}.pronunciations must be an array of at most {MAX_PRONUNCIATIONS} "
                                      "{word, ipa} objects")
    result = []
    for number, item in enumerate(raw):
        spot = f"{where}.pronunciations[{number}]"
        if not isinstance(item, dict):
            raise InvalidCompositionError(f"{spot} must be an object {{word, ipa}}")
        word, ipa = item.get("word"), item.get("ipa")
        if not isinstance(word, str) or not word.strip() or len(word) > MAX_WORD_CHARS or "\n" in word:
            raise InvalidCompositionError(f"{spot}.word must be a short word of the narration text")
        if not isinstance(ipa, str) or not ipa.strip() or len(ipa) > MAX_IPA_CHARS or _FORBIDDEN_IPA.search(ipa):
            raise InvalidCompositionError(f"{spot}.ipa must be an IPA transcription of at most {MAX_IPA_CHARS} "
                                          "characters without slashes, angle brackets or line breaks")
        word, ipa = word.strip(), ipa.strip()
        if not re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text):
            raise InvalidCompositionError(f"{spot}.word {word!r} does not occur as a whole word in the text")
        result.append((word, ipa))
    return tuple(result)


def _volume(entry: dict[str, Any], where: str, kind: str) -> float:
    value = entry.get("volume")
    if value is None:
        return DEFAULT_VOLUME[kind]
    if not _number(value) or not 0 <= value <= 1:
        raise InvalidCompositionError(f"{where}.volume must be a number from 0 to 1")
    return float(value)


def _parse(entry: Any, index: int, video_frames: int, seen: set[str]) -> AudioEntry:
    where = f"audio[{index}]"
    if not isinstance(entry, dict):
        raise InvalidCompositionError(f"{where} must be an object")
    entry_id, kind = entry.get("id"), entry.get("kind")
    if not isinstance(entry_id, str) or not ID_PATTERN.match(entry_id):
        raise InvalidCompositionError(f"{where}.id must be a short identifier like 'voice-1'")
    if entry_id in seen:
        raise InvalidCompositionError(f"audio id {entry_id!r} is used twice; ids must be unique")
    seen.add(entry_id)
    if kind not in KINDS:
        raise InvalidCompositionError(f"{where}.kind must be one of {', '.join(KINDS)}")
    start = entry.get("from")
    if not _whole(start) or not 0 <= start < video_frames:
        raise InvalidCompositionError(f"{where}.from must be a whole frame inside the video (0-{video_frames - 1})")
    volume = _volume(entry, where, kind)
    if kind == "speech":
        text = _text_field(entry, "text", where, MAX_SPEECH_CHARS_LINE)
        voice = entry.get("voice", DEFAULT_VOICE)
        if voice not in VOICE_PRESET_TO_ELEVENLABS_ID:
            raise InvalidCompositionError(f"{where}.voice must be one of {', '.join(VOICE_PRESET_TO_ELEVENLABS_ID)}")
        return AudioEntry(entry_id, kind, start, volume, text=text, voice=voice,
                          pronunciations=_pronunciations(entry, where, text))
    prompt = _text_field(entry, "prompt", where, MAX_PROMPT_CHARS)
    if kind == "sound":
        seconds = entry.get("durationSeconds")
        if not _number(seconds) or not MIN_SOUND_SECONDS <= seconds <= MAX_SOUND_SECONDS:
            raise InvalidCompositionError(f"{where}.durationSeconds must be a number from {MIN_SOUND_SECONDS} "
                                          f"to {MAX_SOUND_SECONDS}")
        loop = entry.get("loop", False)
        if not isinstance(loop, bool):
            raise InvalidCompositionError(f"{where}.loop must be true or false")
        return AudioEntry(entry_id, kind, start, volume, prompt=prompt, duration_seconds=float(seconds), loop=loop)
    frames = entry.get("durationInFrames")
    if not _whole(frames) or frames < 1 or start + frames > video_frames:
        raise InvalidCompositionError(f"{where}.durationInFrames must be a whole number of frames that ends inside "
                                      f"the video ({video_frames} frames)")
    return AudioEntry(entry_id, kind, start, volume, prompt=prompt, duration_frames=frames)


def _check_speech_timing(speech: tuple[AudioEntry, ...], fps: int, video_frames: int) -> None:
    previous_end: Optional[float] = None
    previous_id = ""
    for entry in sorted(speech, key=lambda item: item.from_frame):
        begin = entry.from_frame / fps
        end = begin + estimate_speech_duration_seconds(entry.text)
        if end > video_frames / fps:
            raise InvalidCompositionError(
                f"speech {entry.id!r} needs about {end - begin:.1f} s (about 15 characters per second) from "
                f"{begin:.1f} s but the video ends at {video_frames / fps:.1f} s; shorten the text, start it "
                "earlier or make the video longer")
        if previous_end is not None and begin < previous_end:
            raise InvalidCompositionError(
                f"speech {entry.id!r} starts at {begin:.1f} s while {previous_id!r} still speaks until about "
                f"{previous_end:.1f} s; speech lines must not overlap, move it later or shorten the text")
        previous_end, previous_id = end, entry.id


def build_audio_plan(raw: Any, video: dict[str, Any]) -> AudioPlan:
    """Validate the reported ``audio`` export against the reported ``video``; raise ``InvalidCompositionError``."""
    fps, frames = int(video["fps"]), int(video["durationInFrames"])
    if raw is None or raw == []:
        return AudioPlan(entries=(), fps=fps, video_frames=frames)
    if not isinstance(raw, list):
        raise InvalidCompositionError("audio must be an array of speech, sound and music entries")
    seen: set[str] = set()
    entries = tuple(_parse(entry, index, frames, seen) for index, entry in enumerate(raw))
    speech = tuple(entry for entry in entries if entry.kind == "speech")
    for kind, limit in (("speech", MAX_SPEECH_LINES), ("sound", MAX_SOUNDS), ("music", MAX_MUSIC)):
        count = sum(1 for entry in entries if entry.kind == kind)
        if count > limit:
            raise InvalidCompositionError(f"audio has {count} {kind} entries; at most {limit} are allowed")
    characters = sum(len(entry.text) for entry in speech)
    if characters > MAX_SPEECH_CHARS_TOTAL:
        raise InvalidCompositionError(f"the speech texts have {characters} characters in total; at most "
                                      f"{MAX_SPEECH_CHARS_TOTAL} are allowed")
    _check_speech_timing(speech, fps, frames)
    return AudioPlan(entries=entries, fps=fps, video_frames=frames)
