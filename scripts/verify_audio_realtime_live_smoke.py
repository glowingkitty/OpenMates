#!/usr/bin/env python3
"""Run the paid message-input realtime transcription path against dev.

The committed WAV was generated once with OpenMates audio.speak. This script
never generates speech and is deliberately opt-in so scheduled tests cannot
incur provider charges.

Run:
  OPENMATES_LIVE_AUDIO_REALTIME_SMOKE=1 \
    backend/.venv/bin/python3 scripts/verify_audio_realtime_live_smoke.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import platform
import sys
import tempfile
import time
import uuid
import wave
from array import array
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import aiohttp
import websockets


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = (
    REPO_ROOT / "backend/tests/fixtures/realtime_transcription_speech.wav"
)
EXPECTED_FRAGMENT = "working correctly"
OPT_IN_ENV = "OPENMATES_LIVE_AUDIO_REALTIME_SMOKE"


def _cli_arch() -> str:
    machine = platform.machine().lower()
    return {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(
        machine, machine
    )


def _cli_headers(api_url: str) -> dict[str, str]:
    parsed = urlparse(api_url)
    if parsed.hostname == "api.openmates.org":
        origin = "https://app.openmates.org"
    elif parsed.hostname and parsed.hostname.startswith("api."):
        origin = f"{parsed.scheme}://app.{parsed.hostname[4:]}"
    else:
        origin = f"{parsed.scheme}://{parsed.netloc}"
    user_agent = f"OpenMates CLI/0.1 ({sys.platform} {platform.release()})"
    return {
        "User-Agent": user_agent,
        "X-OpenMates-SDK": "cli",
        "X-OpenMates-Device-Identity": f"cli:{sys.platform}:{_cli_arch()}",
        "Origin": origin,
    }


def _load_profile(profile: str) -> tuple[Path, dict[str, Any]]:
    profile_path = Path.home() / ".openmates" / "profiles" / profile / "session.json"
    if not profile_path.is_file():
        raise RuntimeError(
            f"OpenMates CLI profile {profile!r} is not logged in ({profile_path})"
        )
    session = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(session, dict):
        raise RuntimeError("OpenMates CLI session is invalid")
    return profile_path, session


def _cookie_header(cookies: dict[str, Any]) -> str:
    return "; ".join(
        f"{name}={value}"
        for name, value in cookies.items()
        if isinstance(name, str) and isinstance(value, str) and value
    )


def _persist_refreshed_session(
    profile_path: Path,
    session: dict[str, Any],
    ws_token: str,
    cookies: dict[str, str],
) -> None:
    """Keep the CLI profile usable when /auth/session rotates its cookie."""
    updated = dict(session)
    updated["wsToken"] = ws_token
    updated["cookies"] = cookies
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=profile_path.parent,
        prefix=".session-realtime-smoke-",
        delete=False,
    ) as temporary:
        temporary.write(json.dumps(updated, indent=2) + "\n")
        temporary.flush()
        os.fchmod(temporary.fileno(), 0o600)
        temporary_path = Path(temporary.name)
    temporary_path.replace(profile_path)


async def _fresh_ws_token(
    *, api_url: str, session: dict[str, Any], headers: dict[str, str]
) -> tuple[str, dict[str, str]]:
    cookies = session.get("cookies")
    if not isinstance(cookies, dict):
        raise RuntimeError("OpenMates CLI session has no cookies")
    request_headers = dict(headers)
    cookie_value = _cookie_header(cookies)
    if cookie_value:
        request_headers["Cookie"] = cookie_value

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.post(
            f"{api_url.rstrip('/')}/v1/auth/session",
            json={"session_id": session.get("sessionId")},
            headers=request_headers,
        ) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"Session refresh failed with HTTP {response.status}")
            data = payload.get("data", payload) if isinstance(payload, dict) else {}
            token = data.get("ws_token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                raise RuntimeError("Session refresh did not return a WebSocket token")
            merged = {
                str(name): str(value)
                for name, value in cookies.items()
                if isinstance(name, str) and isinstance(value, str)
            }
            for name, morsel in response.cookies.items():
                merged[name] = morsel.value
            return token, merged


def _read_pcm_16khz(fixture: Path) -> bytes:
    with wave.open(str(fixture), "rb") as recording:
        channels = recording.getnchannels()
        sample_width = recording.getsampwidth()
        sample_rate = recording.getframerate()
        frames = recording.readframes(recording.getnframes())
    if channels != 1 or sample_width != 2:
        raise RuntimeError("Speech fixture must be mono 16-bit PCM")
    if sample_rate == 16_000:
        return frames
    if sample_rate != 48_000:
        raise RuntimeError("Speech fixture must use a 16 kHz or 48 kHz sample rate")

    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    downsampled = array(
        "h",
        (
            int((samples[index] + samples[index + 1] + samples[index + 2]) / 3)
            for index in range(0, len(samples) - 2, 3)
        ),
    )
    if sys.byteorder != "little":
        downsampled.byteswap()
    return downsampled.tobytes()


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    profile_path, session = _load_profile(args.profile)
    api_url = (args.api_url or session.get("apiUrl") or "").rstrip("/")
    if not api_url.startswith("https://"):
        raise RuntimeError("The live smoke requires an HTTPS API URL")
    headers = _cli_headers(api_url)
    ws_token, cookies = await _fresh_ws_token(
        api_url=api_url, session=session, headers=headers
    )
    _persist_refreshed_session(profile_path, session, ws_token, cookies)

    pcm = _read_pcm_16khz(args.fixture)
    session_id = str(uuid.uuid4())
    ws_url = f"wss://{urlparse(api_url).netloc}/v1/apps/audio/realtime-transcription?{urlencode({'sessionId': session_id, 'token': ws_token})}"
    events: list[dict[str, Any]] = []
    completed = asyncio.Event()
    started_at = time.monotonic()

    async with websockets.connect(
        ws_url,
        origin=headers["Origin"],
        user_agent_header=headers["User-Agent"],
        additional_headers={"Cookie": _cookie_header(cookies)},
        open_timeout=20,
        close_timeout=10,
        max_size=2 * 1024 * 1024,
    ) as socket:
        ready = json.loads(await asyncio.wait_for(socket.recv(), timeout=30))
        if ready.get("type") != "session.ready":
            raise RuntimeError(f"Expected session.ready, received {ready.get('type')!r}")
        events.append(ready)

        async def receive_events() -> None:
            async for raw_message in socket:
                message = json.loads(raw_message)
                if isinstance(message, dict):
                    events.append(message)
                    if message.get("type") in {
                        "correction.done",
                        "correction.failed",
                        "session.error",
                    }:
                        completed.set()

        receiver = asyncio.create_task(receive_events())
        try:
            chunk_bytes = 3_200  # 100 ms of mono pcm_s16le at 16 kHz.
            for offset in range(0, len(pcm), chunk_bytes):
                chunk = pcm[offset : offset + chunk_bytes]
                await socket.send(
                    json.dumps(
                        {
                            "type": "input_audio.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        },
                        separators=(",", ":"),
                    )
                )
                await asyncio.sleep(len(chunk) / 32_000)
            await socket.send('{"type":"input_audio.end"}')
            await asyncio.wait_for(completed.wait(), timeout=args.timeout)
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)

    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_type.setdefault(str(event.get("type")), []).append(event)
    if by_type.get("session.error"):
        raise RuntimeError(
            f"Realtime service error: {by_type['session.error'][-1].get('message', 'unknown')}"
        )
    required = {
        "transcription.text.delta",
        "transcription.done",
        "correction.started",
        "correction.done",
    }
    missing = sorted(required.difference(by_type))
    if missing:
        raise RuntimeError(f"Realtime flow omitted required events: {', '.join(missing)}")

    raw_transcript = str(by_type["transcription.done"][-1].get("transcript") or "")
    corrected = str(by_type["correction.done"][-1].get("transcript") or "")
    if EXPECTED_FRAGMENT not in raw_transcript.casefold():
        raise RuntimeError("Raw transcript did not contain the expected speech")
    if EXPECTED_FRAGMENT not in corrected.casefold():
        raise RuntimeError("Corrected transcript did not contain the expected speech")
    return {
        "status": "passed",
        "api_url": api_url,
        "fixture": str(args.fixture.relative_to(REPO_ROOT)),
        "audio_seconds": round(len(pcm) / 32_000, 3),
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "event_types": [str(event.get("type")) for event in events],
        "delta_count": len(by_type["transcription.text.delta"]),
        "raw_transcript": raw_transcript,
        "corrected_transcript": corrected,
        "transcription_model": by_type["transcription.done"][-1].get("model"),
        "correction_model": by_type["correction.done"][-1].get("correction_model"),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="opencode-personal")
    parser.add_argument("--api-url")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    if os.environ.get(OPT_IN_ENV) != "1":
        print(
            f"Refusing paid live smoke without {OPT_IN_ENV}=1; "
            "the committed fixture is never regenerated.",
            file=sys.stderr,
        )
        return 2
    args = _parse_args()
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        print(f"Live realtime audio smoke failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            "Live realtime audio smoke passed: "
            f"{result['delta_count']} deltas, {result['elapsed_seconds']}s elapsed"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
