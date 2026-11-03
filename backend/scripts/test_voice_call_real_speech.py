"""Live voice-call turn check with real speech, real STT and the real completion decision.

Generates public synthetic utterances with Mistral TTS, streams them in real
time as 16 kHz PCM through the actual ``/v1/voice-call`` route handler, with
real Voxtral realtime STT and the real Jev completion decision. Only auth,
chat ownership, locks, billing, registry and message-id issuance are stubbed,
so no account, chat or assistant inference is touched.

Each scenario must produce exactly one final transcript containing every spoken
segment, no submission during a thinking pause, and (when the ending is
unambiguous) a final transcript soon after speech ends.

Usage (dev host, Vault credentials):
  docker exec -w /app api python /app/backend/scripts/test_voice_call_real_speech.py [scenario ...]
"""
# contract-test-file: tooling
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any
import uuid

from backend.core.api.app.routes import voice_call as route
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.mistral_speech import MistralSpeechClient

RATE = 16_000
CHUNK = 3_200  # 100 ms of s16le mono
VOICE_ID = "voice_3150"
OWNER = "voice-real-speech-owner"
# (spoken segments with the silence after each, required words, max seconds
# from end of speech to final transcript or None when the ending is ambiguous)
SCENARIOS: dict[str, tuple[list[tuple[str, float]], list[str], float | None]] = {
    "simple_question": ([("What is the capital of France?", 0)], ["capital", "france"], 2.0),
    "short_answer": ([("Yes.", 0)], ["yes"], 2.0),
    "thinking_pause": ([("I would like to know", 2.6), ("what the weather will be in Berlin tomorrow.", 0)],
                       ["know", "berlin"], None),
    "trailing_conjunction": ([("Can you recommend a book about history and", 3.0),
                              ("maybe one about science too?", 0)], ["history", "science"], None),
}


class _Profile:
    def __init__(self) -> None:
        self.chat = self

    async def get_chat_metadata(self, chat_id: str, *, admin_required: bool) -> dict[str, Any]:
        return {"id": chat_id, "hashed_user_id": hashlib.sha256(OWNER.encode()).hexdigest(), "storage_state": "active"}

    async def get_user_fields_direct(self, user_id: str, fields: list[str], *, no_cache: bool) -> dict[str, Any]:
        return {field: 1_800_000_000 for field in fields}

    async def update_user(self, user_id: str, fields: dict[str, Any]) -> bool:
        return True


class _Cache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def set(self, key: str, value: Any, *, ttl: int) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class _Socket:
    def __init__(self, secrets: SecretsManager) -> None:
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.app = SimpleNamespace(state=SimpleNamespace(
            cache_service=_Cache(), directus_service=_Profile(), secrets_manager=secrets))

    def push(self, event: dict[str, Any]) -> None:
        self.incoming.put_nowait(json.dumps(event))

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        return await self.incoming.get()

    async def send_json(self, event: dict[str, Any]) -> None:
        self.sent.append({**event, "_t": time.monotonic()})

    async def close(self, **_kwargs: Any) -> None:
        return None

    def finals(self) -> list[dict[str, Any]]:
        return [event for event in self.sent if event["type"] == "transcript" and event.get("final")]


async def _speech_pcm(key: str, text: str) -> bytes:
    for attempt in range(3):
        try:
            audio = await MistralSpeechClient(api_key=key).text_to_speech(text=text, voice_id=VOICE_ID)
            break
        except RuntimeError:
            if attempt == 2:
                raise
            await asyncio.sleep(2)
    return subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
        input=audio.audio_bytes, capture_output=True, check=True,
    ).stdout


def _stub_route() -> None:
    async def allowed(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def lock(*_args: Any) -> tuple[object, str, str]:
        return object(), "lock", "owner-token"

    async def lease(*_args: Any) -> None:
        await asyncio.Future()

    async def recovery(_self: Any, _operation: str, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"eligible": False}

    route._browser_request_is_allowed = allowed
    route._session_still_valid = allowed
    route.is_payment_enabled = lambda: False
    route._acquire_lock = lock
    route._release_lock = nothing
    route._renew_lock = lease
    route.register_active_call = nothing
    route.renew_active_call = nothing
    route.issue_message_id = nothing
    route.finalize_active_call = nothing
    route._charge_voice = nothing
    ChatRecoveryService.execute = recovery


async def _run(name: str, secrets: SecretsManager, key: str) -> dict[str, Any]:
    spoken, required, latency_limit = SCENARIOS[name]
    segments = [(await _speech_pcm(key, text), pause) for text, pause in spoken]
    socket = _Socket(secrets)
    socket.push({"type": "start", "speech_output_transport": route.SPEECH_OUTPUT_TRANSPORT,
                 "chat_id": str(uuid.uuid4()), "startup_audio_allowance_ms": 0})
    task = asyncio.create_task(route.voice_call(socket, {"user_id": OWNER, "session_hash": "session"}))
    for _ in range(500):
        if task.done() or any(event["type"] == "ready" for event in socket.sent):
            break
        await asyncio.sleep(0.02)
    if not any(event["type"] == "ready" for event in socket.sent):
        task.cancel()
        return {"scenario": name, "passed": False, "failure": "call_not_ready",
                "events": [event["type"] for event in socket.sent]}

    async def stream(pcm: bytes) -> None:
        for offset in range(0, len(pcm), CHUNK):
            socket.push({"type": "mic_audio", "data": base64.b64encode(pcm[offset:offset + CHUNK]).decode()})
            await asyncio.sleep(0.1)

    premature = False
    for index, (pcm, pause) in enumerate(segments):
        await stream(pcm)
        if index < len(segments) - 1:
            await stream(b"\0\0" * int(RATE * pause))
            premature = premature or bool(socket.finals())
    speech_end = time.monotonic()
    # Keep sending silence like an open microphone; collect any duplicate.
    settle_until = speech_end + 12
    while time.monotonic() < settle_until and not socket.finals():
        await stream(b"\0\0" * (CHUNK // 2))
    await stream(b"\0\0" * RATE * 2)
    socket.push({"type": "hangup"})
    await asyncio.wait_for(task, 10)

    finals = socket.finals()
    text = " ".join(str(event.get("text", "")) for event in finals).lower()
    latency = round(finals[0]["_t"] - speech_end, 2) if finals else None
    failure = None
    if premature:
        failure = "submitted_during_thinking_pause"
    elif len(finals) != 1:
        failure = f"expected_one_final_got_{len(finals)}"
    elif not all(word in text for word in required):
        failure = "final_transcript_missing_spoken_segment"
    elif latency_limit is not None and (latency is None or latency > latency_limit):
        failure = "final_transcript_too_slow"
    return {"scenario": name, "passed": failure is None, "failure": failure,
            "speech_end_to_final_s": latency, "final_text": [event.get("text") for event in finals],
            "live_partials": sum(1 for event in socket.sent if event["type"] == "transcript" and not event.get("final"))}


async def main() -> int:
    names = sys.argv[1:] or list(SCENARIOS)
    unknown = [name for name in names if name not in SCENARIOS]
    if unknown:
        raise SystemExit(f"Unknown scenarios: {', '.join(unknown)}")
    secrets = SecretsManager()
    await secrets.initialize()
    key = await secrets.get_secret("kv/data/providers/mistral_ai", "api_key")
    if not key:
        raise SystemExit("Mistral credentials unavailable")
    _stub_route()
    results = [await _run(name, secrets, key) for name in names]
    for result in results:
        print(json.dumps(result), flush=True)
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
