"""Sound of composed videos: audio plan validation, clip generation, pricing and the renderer's Audio sequences.

Specification: feature.app-skill.videos-generate (videos-generate.composed.author-writes-composition,
videos-generate.billing.metered). Provider clients are fakes; no network.
"""

from __future__ import annotations

import asyncio
import re
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.apps.music.pricing import MUSIC_TRACK_CREDITS
from backend.apps.videos.composed.audio_clips import (
    AudioGenerationError,
    AudioRejectedError,
    GeneratedAudio,
    GeneratedClip,
    audio_assets,
    audio_tracks,
    generate_audio,
)
from backend.apps.videos.composed.audio_measure import mp3_duration_seconds, wav_duration_seconds
from backend.apps.videos.composed.audio_plan import apply_pronunciations, build_audio_plan
from backend.apps.videos.composed.contract import InvalidCompositionError, validate_source
from backend.apps.videos.composed.prompt import SYSTEM_PROMPT
from backend.apps.videos.tasks.generate_billing import (
    audio_credit_breakdown,
    audio_credits,
    estimate_audio_credit_breakdown,
    estimate_audio_credits,
)
from backend.shared.providers.e2b_remotion_renderer import (
    AUDIO_TRACKS_FILE,
    ROOT_TSX,
    RUNNER_MJS,
    MAX_AUDIO_FILES,
    RemotionAsset,
    RemotionSandboxError,
    validate_audio_assets,
)

VIDEO = {"fps": 30, "durationInFrames": 300, "width": 1280, "height": 720}  # 10 s
SPEECH = {"id": "voice-1", "kind": "speech", "text": "Hello from Lisbon.", "from": 0}
SOUND = {"id": "knock", "kind": "sound", "prompt": "soft door knock", "durationSeconds": 2, "from": 30}
MUSIC = {"id": "bed", "kind": "music", "prompt": "warm acoustic guitar", "from": 0, "durationInFrames": 300}


def plan_of(*entries, video=VIDEO):
    return build_audio_plan(list(entries), video)


def rejected(*entries, match):
    with pytest.raises(InvalidCompositionError, match=match):
        plan_of(*entries)


def mp3_bytes(seconds: float) -> bytes:
    """Silent MPEG-1 Layer III frames at 128 kbit/s, 44.1 kHz (417 bytes, 26.122 ms each)."""
    frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)
    return frame * round(seconds / 0.026122)


def wav_bytes(seconds: float) -> bytes:
    rate, data = 8000, bytes(int(8000 * seconds) * 2)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)


class FakeEleven:
    def __init__(self, fail_id_text: str = "") -> None:
        self.running = self.peak = 0
        self.calls: list[tuple[str, dict]] = []
        self.fail_text = fail_id_text

    async def _work(self):
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.01)
        self.running -= 1

    async def text_to_speech(self, **kwargs):
        self.calls.append(("speech", kwargs))
        await self._work()
        if self.fail_text and self.fail_text in kwargs["text"]:
            raise RuntimeError("ElevenLabs audio generation failed")
        return SimpleNamespace(audio_bytes=mp3_bytes(2.0), mime_type="audio/mpeg", model=kwargs["model"],
                               duration_seconds=2.0)

    async def generate_sound_effect(self, **kwargs):
        self.calls.append(("sound", kwargs))
        await self._work()
        return SimpleNamespace(audio_bytes=mp3_bytes(1.0), mime_type="audio/mpeg", model="sfx", duration_seconds=1.0)


async def fake_music(**kwargs):
    fake_music.calls.append(kwargs)
    return SimpleNamespace(audio_bytes=wav_bytes(4.0), mime_type="audio/wav", model="lyria-3-pro-preview",
                           duration_seconds=kwargs.get("duration_seconds"))

fake_music.calls = []


async def approve(**_kwargs):
    return SimpleNamespace(approved=True, category="", user_facing_message="")


def run_audio(plan, eleven=None, **kwargs):
    return asyncio.run(generate_audio(plan, secrets_manager=None, elevenlabs_client=eleven or FakeEleven(),
                                      music_generator=fake_music, speech_safety=approve, **kwargs))


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_absent_or_empty_audio_is_a_silent_plan():
    assert build_audio_plan(None, VIDEO).is_empty
    assert build_audio_plan([], VIDEO).is_empty


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_valid_plan_gets_defaults_and_default_voice():
    plan = plan_of(SPEECH, SOUND, MUSIC)
    speech, sound, music = plan.entries
    assert (speech.volume, sound.volume, music.volume) == (1.0, 0.7, 0.25)
    assert speech.voice == "warm_neutral" and sound.duration_seconds == 2.0 and music.duration_frames == 300


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_ids_must_match_the_pattern_and_be_unique():
    rejected({**SPEECH, "id": "bad id"}, match="short identifier")
    rejected(SPEECH, {**SOUND, "id": "voice-1"}, match="used twice")


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_count_and_character_caps():
    lines = [{"id": f"v{i}", "kind": "speech", "text": "Hi.", "from": i * 20} for i in range(13)]
    rejected(*lines, match="at most 12")
    rejected(*[{**SOUND, "id": f"s{i}"} for i in range(9)], match="at most 8")
    rejected(MUSIC, {**MUSIC, "id": "bed2"}, match="at most 1")
    rejected({**SPEECH, "text": "x" * 401}, match="at most 400")
    long_video = {**VIDEO, "durationInFrames": 1800}
    lines = [{"id": f"v{i}", "kind": "speech", "text": "y" * 300, "from": i * 290} for i in range(6)]
    with pytest.raises(InvalidCompositionError, match="1500"):
        build_audio_plan(lines, long_video)


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_volume_start_and_duration_rules():
    rejected({**SPEECH, "volume": 1.5}, match="0 to 1")
    rejected({**SPEECH, "from": 300}, match="inside the video")
    rejected({**SOUND, "durationSeconds": 0.2}, match="durationSeconds")
    rejected({**SOUND, "durationSeconds": 11}, match="durationSeconds")
    rejected({**MUSIC, "durationInFrames": 301}, match="ends inside")
    rejected({**SPEECH, "kind": "jingle"}, match="kind must be")


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_speech_must_fit_before_the_video_end_and_not_overlap_by_estimate():
    long_text = "word " * 40  # about 12 s at 15 characters per second
    rejected({**SPEECH, "text": long_text.strip()}, match="video ends")
    rejected({**SPEECH, "text": "a" * 60}, {**SPEECH, "id": "v2", "text": "Next.", "from": 60}, match="overlap")
    plan_of({**SPEECH, "text": "a" * 60}, {**SPEECH, "id": "v2", "text": "Next.", "from": 150})


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_voice_must_be_a_preset():
    rejected({**SPEECH, "voice": "robot"}, match="voice must be one of")
    assert plan_of({**SPEECH, "voice": "calm_narrator"}).entries[0].voice == "calm_narrator"


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_pronunciation_validation_and_whole_word_substitution():
    entry = {**SPEECH, "text": "Lisbon is not Lisbonne. Lisbon!", "pronunciations": [{"word": "Lisbon", "ipa": "ˈlɪzbən"}]}
    built = plan_of(entry).entries[0]
    assert apply_pronunciations(built.text, built.pronunciations) == "/ˈlɪzbən/ is not Lisbonne. /ˈlɪzbən/!"
    rejected({**entry, "pronunciations": [{"word": "Lisbon", "ipa": "a/b"}]}, match="ipa")
    rejected({**entry, "pronunciations": [{"word": "Lisbon", "ipa": "<x>"}]}, match="ipa")
    rejected({**entry, "pronunciations": [{"word": "Lisbon", "ipa": "a" * 61}]}, match="ipa")
    rejected({**entry, "pronunciations": [{"word": "Porto", "ipa": "ˈpoɾtu"}]}, match="whole word")


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_clips_run_concurrently_with_ipa_text_and_report_measured_data():
    plan = plan_of(*[{**SPEECH, "id": f"v{i}", "text": "Lisbon.", "from": i * 40,
                      "pronunciations": [{"word": "Lisbon", "ipa": "lɪz"}]} for i in range(4)], SOUND, MUSIC)
    eleven = FakeEleven()
    started: list[str] = []
    generated = run_audio(plan, eleven, on_kind_started=started.append)
    assert eleven.peak > 1 and eleven.peak <= 4
    assert sorted(started) == ["music", "sound", "speech"]
    speech_calls = [kwargs for kind, kwargs in eleven.calls if kind == "speech"]
    assert all(call["text"] == "/lɪz/." and call["model"] == "eleven_v4" for call in speech_calls)
    by_id = {clip.id: clip for clip in generated.clips}
    assert abs(by_id["v0"].duration_seconds - 2.0) < 0.1 and by_id["v0"].provider == "ElevenLabs"
    assert by_id["bed"].mime_type == "audio/wav" and by_id["bed"].file_name == "bed.wav"
    assert abs(by_id["bed"].duration_seconds - 4.0) < 0.01 and by_id["bed"].units == 1.0
    assert "Instrumental" in fake_music.calls[-1]["prompt"] and fake_music.calls[-1]["duration_seconds"] == 10


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_provider_failure_is_typed_and_not_skipped():
    plan = plan_of(SPEECH, {**SPEECH, "id": "v2", "text": "Boom.", "from": 100})
    with pytest.raises(AudioGenerationError) as caught:
        run_audio(plan, FakeEleven(fail_id_text="Boom"))
    assert (caught.value.kind, caught.value.clip_id) == ("speech", "v2")


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_safety_rejection_is_typed_with_a_user_safe_reason():
    async def refuse(**_kwargs):
        return SimpleNamespace(approved=False, category="x", user_facing_message="I can't create that speech audio.")

    eleven = FakeEleven()
    with pytest.raises(AudioRejectedError) as caught:
        asyncio.run(generate_audio(plan_of(SPEECH), secrets_manager=None, elevenlabs_client=eleven,
                                   music_generator=fake_music, speech_safety=refuse))
    assert caught.value.reason == "I can't create that speech audio." and eleven.calls == []


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_tracks_and_assets_follow_real_lengths_and_cut_at_video_end():
    plan = plan_of(SPEECH, {**SOUND, "from": 290}, MUSIC)
    generated = run_audio(plan)
    tracks = {track["file"]: track for track in audio_tracks(plan, generated)}
    assert tracks["audio/voice-1.mp3"]["durationInFrames"] in (60, 61) and tracks["audio/voice-1.mp3"]["fadeOutFrames"] == 0
    assert tracks["audio/knock.mp3"]["durationInFrames"] == 10  # cut at the video end
    assert tracks["audio/bed.wav"] == {"file": "audio/bed.wav", "from": 0, "durationInFrames": 300, "volume": 0.25,
                                       "fadeOutFrames": 15, "loop": True}
    assert [asset.name for asset in audio_assets(generated)] == ["voice-1.mp3", "knock.mp3", "bed.wav"]


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_audio_measure_reads_mp3_and_wav_lengths():
    assert abs(mp3_duration_seconds(b"ID3\x03\x00\x00\x00\x00\x00\x04abcd" + mp3_bytes(3.0)) - 3.0) < 0.05
    assert wav_duration_seconds(wav_bytes(1.5)) == 1.5 and mp3_duration_seconds(b"nothing") is None


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_audio_pricing_numbers_and_breakdown():
    clips = (GeneratedClip("a", "speech", b"x", "audio/mpeg", 2.5, "ElevenLabs", "eleven_v4", 2.5),
             GeneratedClip("b", "sound", b"x", "audio/mpeg", 1.5, "ElevenLabs", "sfx", 1.5),
             GeneratedClip("c", "music", b"x", "audio/wav", 30.0, "Google", "lyria", 1.0))
    generated = GeneratedAudio(clips)
    assert audio_credit_breakdown(generated) == {"speech": 5, "sound": 23, "music": MUSIC_TRACK_CREDITS}
    assert audio_credits(generated) == 5 + 23 + 120


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_audio_estimate_from_the_plan_and_music_price_matches_the_skill():
    plan = plan_of({**SPEECH, "text": "a" * 150}, SOUND, MUSIC)  # 150 chars = 9 s of speech
    assert estimate_audio_credit_breakdown(plan) == {"speech": 18, "sound": 30, "music": 120}
    assert estimate_audio_credits(plan) == 168 and estimate_audio_credits(build_audio_plan(None, VIDEO)) == 0
    yml = (Path(__file__).parents[1] / "apps/music/app.yml").read_text()
    assert re.search(rf"per_unit:\s*credits: {MUSIC_TRACK_CREDITS}\b", yml)


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_root_wrapper_renders_one_audio_sequence_per_track_and_runner_passes_them():
    assert "import Main, {parts, video} from './Composition'" in ROOT_TSX
    assert "<Sequence key={track.file} from={track.from} durationInFrames={track.durationInFrames}>" in ROOT_TSX
    assert "<Audio" in ROOT_TSX and "staticFile(track.file)" in ROOT_TSX and "track.fadeOutFrames" in ROOT_TSX
    assert "openmatesAudioPlan" in ROOT_TSX and "openmatesAudioPlan" in RUNNER_MJS
    assert "openmatesAudio" in RUNNER_MJS and AUDIO_TRACKS_FILE in RUNNER_MJS and "inputProps" in RUNNER_MJS


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_audio_assets_have_their_own_caps():
    validate_audio_assets([RemotionAsset(f"a{i}.mp3", b"x") for i in range(MAX_AUDIO_FILES)])
    with pytest.raises(RemotionSandboxError):
        validate_audio_assets([RemotionAsset(f"a{i}.mp3", b"x") for i in range(MAX_AUDIO_FILES + 1)])
    with pytest.raises(RemotionSandboxError):
        validate_audio_assets([RemotionAsset("big.mp3", b"x" * (15 * 1024 * 1024 + 1))])
    with pytest.raises(RemotionSandboxError):
        validate_audio_assets([RemotionAsset("../x.mp3", b"x")])


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_author_cannot_reference_audio_files_through_static_file():
    code = ("import React from 'react';\nimport {staticFile} from 'remotion';\n"
            "export const video = {fps: 30, durationInFrames: 90, width: 1280, height: 720};\n"
            "export const parts = [];\nconst a = staticFile('audio/voice-1.mp3');\nexport default () => null;\n")
    with pytest.raises(InvalidCompositionError, match="not one of the given files"):
        validate_source(code, input_names=[], aspect_ratio=None, duration_seconds=None)


# contract-test: supporting surface=rest_api assertions=videos-generate.composed.sound
def test_prompt_explains_audio_without_audio_components():
    assert "export const audio" in SYSTEM_PROMPT and "never write <Audio>" in SYSTEM_PROMPT
    assert "id: 'voice-1', kind: 'speech'" in SYSTEM_PROMPT and "pronunciations" in SYSTEM_PROMPT
