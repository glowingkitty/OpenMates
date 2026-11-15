"""Voxtral realtime end-of-speech probe: same speech, several turn_detection settings, in parallel.

Runs inside the dev api container. Env: WAV, TIMELINE, CONFIGS (json name->turn_detection), ROUNDS.
Per segment it reports seconds from the known end of speech to turn.eager_end / turn.end /
transcription text, and turn.end events that fire before speech ended (premature cuts).
"""

import asyncio
import base64
import json
import os
import sys
import time
import wave

sys.path.insert(0, "/app")
import aiohttp
from backend.core.api.app.utils.secrets_manager import SecretsManager

URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime?model=voxtral-mini-transcribe-realtime-3-0"
RATE = 16000
CHUNK = 1600  # 100 ms


def segments():
    w = wave.open(os.environ["WAV"])
    pcm = w.readframes(w.getnframes())
    qs = json.load(open(os.environ["TIMELINE"]))["questions"]

    def cut(a, b):
        return pcm[int(a * RATE) * 2 : int(b * RATE) * 2]

    out = []
    for i, q in enumerate(qs):  # plain question: 0.5 s lead, speech, 5 s silence
        audio = cut(q["voiced_start_s"] - 0.5, q["voiced_end_s"])
        out.append(
            {
                "name": f"q{i + 1}",
                "audio": audio + bytes(RATE * 2 * 5),
                "ends": [len(audio) / 2 / RATE],
                "pauses": [],
            }
        )
    for gap in (0.6, 1.0):  # one turn with a thinking pause between two questions
        a = cut(qs[0]["voiced_start_s"] - 0.5, qs[0]["voiced_end_s"])
        b = cut(qs[2]["voiced_start_s"], qs[2]["voiced_end_s"])
        audio = a + bytes(int(RATE * gap) * 2) + b
        out.append(
            {
                "name": f"pause{gap}",
                "audio": audio + bytes(RATE * 2 * 5),
                "ends": [len(audio) / 2 / RATE],
                "pauses": [[len(a) / 2 / RATE, len(a) / 2 / RATE + gap]],
            }
        )
    return out


async def run_config(name, td, segs, key):
    rows = []
    async with aiohttp.ClientSession() as http:
        ws = await http.ws_connect(
            URL, headers={"Authorization": f"Bearer {key}"}, max_msg_size=4 << 20
        )
        assert json.loads((await ws.receive()).data)["type"] == "session.created"
        await ws.send_json(
            {
                "type": "session.update",
                "session": {
                    "audio_format": {"encoding": "pcm_s16le", "sample_rate": RATE},
                    "target_streaming_delay_ms": 240,
                    "turn_detection": td,
                },
            }
        )
        ev = json.loads((await ws.receive()).data)
        if ev.get("type") != "session.updated":
            return [{"config": name, "error": str(ev)[:300]}]
        for seg in segs:
            events = []
            t0 = time.monotonic()

            async def reader():
                while True:
                    m = await ws.receive()
                    if m.type != aiohttp.WSMsgType.TEXT:
                        return
                    e = json.loads(m.data)
                    events.append((time.monotonic() - t0, e.get("type")))

            task = asyncio.create_task(reader())
            audio = seg["audio"]
            for k, off in enumerate(range(0, len(audio), CHUNK * 2)):
                await ws.send_json(
                    {
                        "type": "input_audio.append",
                        "audio": base64.b64encode(
                            audio[off : off + CHUNK * 2]
                        ).decode(),
                    }
                )
                await asyncio.sleep(max(0, t0 + (k + 1) * 0.1 - time.monotonic()))
            await asyncio.sleep(1.0)
            task.cancel()
            end = seg["ends"][0]

            def first(kind):
                return next(
                    (
                        round(t - end, 3)
                        for t, k in events
                        if k == kind and t > end - 0.3
                    ),
                    None,
                )

            premature = [
                round(t, 2) for t, k in events if k == "turn.end" and t < end - 0.3
            ]
            rows.append(
                {
                    "config": name,
                    "seg": seg["name"],
                    "eager_end": first("turn.eager_end"),
                    "turn_end": first("turn.end"),
                    "premature_turn_ends": premature,
                    "types": sorted({k for _, k in events}),
                }
            )
            # reset between segments with a forced boundary
        await ws.close()
    return rows


async def main():
    sm = SecretsManager()
    await sm.initialize()
    key = await sm.get_secret("kv/data/providers/mistral_ai", "api_key")
    segs = segments()
    configs = json.loads(os.environ["CONFIGS"])
    allrows = []
    for _ in range(int(os.environ.get("ROUNDS", "1"))):
        res = await asyncio.gather(
            *(run_config(n, td, segs, key) for n, td in configs.items())
        )
        for r in res:
            allrows += r
    print(json.dumps(allrows))


asyncio.run(main())
