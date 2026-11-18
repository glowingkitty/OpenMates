"""Times the per-sentence and per-turn voice gates in isolation (dev api container, synthetic text).

completion: the AI end-of-turn check on finished and unfinished sentences.
safety:     the per-clause speech safety check (deterministic + Groq safeguard), trusted narration.
tts_cold:   ElevenLabs realtime: connect + first audio for one clause on a new socket.
tts_warm:   first audio for one clause on an already open socket (what prewarm gives).
Env: REPEATS.
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "/app")
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.voice_turn_completion import (
    classify_voice_turn_completion,
    prewarm_voice_turn_completion,
)
from backend.apps.audio.skills.speak_skill import classify_audio_speech_safety
from backend.apps.audio.assistant_speech.voice_profiles import (
    ASSISTANT_VOICE_PROVIDER_IDS,
)
from backend.shared.providers.elevenlabs.realtime import ElevenLabsRealtimeSession

DONE = [
    "What is the capital of France?",
    "Why is the sky blue?",
    "How far away is the moon?",
    "Give me three quick tips for sleeping better.",
    "What is a good name for a grey cat?",
]
OPEN = [
    "What is the capital of",
    "Can you tell me why the",
    "I was wondering whether maybe",
]
CLAUSES = [
    "The capital of France is Paris.",
    "The sky looks blue because air scatters blue light more than red light.",
    "The moon is about 384,000 kilometres away from Earth.",
    "Keep a regular bedtime, even on weekends.",
]


async def tts(key, text, warm):
    s = ElevenLabsRealtimeSession(
        api_key=key,
        voice_id=ASSISTANT_VOICE_PROVIDER_IDS["george"],
        receive_timeout_seconds=15,
        max_session_seconds=60,
        max_input_characters=500,
        max_input_count=4,
        max_audio_bytes=4 << 20,
    )
    t0 = time.perf_counter()
    await s.open()
    opened = time.perf_counter()
    if warm:
        await asyncio.sleep(1.0)
    t1 = time.perf_counter()
    await s.append_text(text + " ")
    await s.flush()
    first = None
    async for ev in s.audio_events():
        if ev.audio_bytes:
            first = time.perf_counter()
            break
    await s.cancel()
    base = t1 if warm else t0
    return {
        "open_ms": (opened - t0) * 1000,
        "first_audio_ms": (first - base) * 1000 if first else None,
    }


async def main():
    sm = SecretsManager()
    await sm.initialize()
    eleven = await sm.get_secret("kv/data/providers/elevenlabs", "api_key")
    await prewarm_voice_turn_completion()
    rows = []
    for rep in range(int(os.environ.get("REPEATS", "5"))):
        for text in DONE + OPEN:
            t = time.perf_counter()
            verdict = await classify_voice_turn_completion(text, sm)
            rows.append(
                {
                    "gate": "completion",
                    "finished": text in DONE,
                    "ms": (time.perf_counter() - t) * 1000,
                    "verdict": verdict,
                }
            )
        for text in CLAUSES:
            t = time.perf_counter()
            d = await classify_audio_speech_safety(
                text=text,
                voice="george",
                accent="en_us",
                style="natural",
                secrets_manager=sm,
                trusted_narration=True,
            )
            rows.append(
                {
                    "gate": "safety",
                    "ms": (time.perf_counter() - t) * 1000,
                    "approved": d.approved,
                }
            )
        for warm in (False, True):
            try:
                rows.append(
                    {
                        "gate": "tts_warm" if warm else "tts_cold",
                        **(await tts(eleven, CLAUSES[rep % len(CLAUSES)], warm)),
                    }
                )
            except Exception as exc:  # probe only: record any TTS failure as a data row instead of aborting the run
                rows.append(
                    {
                        "gate": "tts_warm" if warm else "tts_cold",
                        "error": type(exc).__name__ + ":" + str(exc)[:80],
                    }
                )
    print(json.dumps(rows))


asyncio.run(main())
