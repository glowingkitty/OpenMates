#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real proof: a voice call starts a spawned chat and speaks its report, no mocks.

Generates two utterances with text-to-speech (dev ``api`` container, script
backend/scripts/generate_voice_call_speaker_audio.py) and joins them into one WAV:
request for a separate chat that reports a poem, ~8 s of silence, a capital-of-France
question, then a long silence. Runs frontend/apps/web_app/tests/voice-call-orchestration-real.spec.ts
against https://app.dev.openmates.org with the personal dev test account; Chromium plays
the WAV as its microphone. Same harness as scripts/voice_call_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/voice_call_orchestration_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/voice-call-orchestration-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from design_embroidery_web_real_test import ROOT, installed_chromium, main

SPEC = "tests/voice-call-orchestration-real.spec.ts"
GENERATOR = ROOT / "backend/scripts/generate_voice_call_speaker_audio.py"
API_CONTAINER = "api"
SLUG = "chat-report-spoken"  # keep in sync with SLUG in the spec
UTTERANCE_A = "Please start a separate new chat that writes a short two line poem about the sea and reports the poem back to me."
UTTERANCE_B = "Meanwhile, what is the capital of France?"
GAP_SECONDS = 8.0
TAIL_SECONDS = 240.0
PATTERNS = (("heard", r"heard: ([^\n]+)"),
            ("events", r"event notices: ([^\n]+)"),
            ("played_audio", r"played audio: ([^\n]+)"),
            ("interpretation", r"interpretation: ([^\n]+)"))


def synthesize(text: str, *, lead: float, tail: float) -> bytes:
    with GENERATOR.open("rb") as script:
        run = subprocess.run(["docker", "exec", "-i", API_CONTAINER, "python", "-", "--text", text,
                              "--lead-seconds", str(lead), "--tail-seconds", str(tail)],
                             stdin=script, capture_output=True, check=False, timeout=180)
    if run.returncode:
        raise SystemExit(f"speaker audio generation failed (exit {run.returncode})")
    return base64.b64decode(json.loads(run.stdout.decode().strip().splitlines()[-1])["wav_base64"])


def read_pcm(data: bytes) -> tuple[tuple[int, int, int], bytes]:
    with wave.open(io.BytesIO(data), "rb") as handle:
        return (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()), handle.readframes(handle.getnframes())


def generate_speech(directory: Path) -> dict[str, float]:
    """Write chat-report-spoken.wav = A + silence gap + B + long tail; returns the section seconds."""
    (channels, width, rate), first = read_pcm(synthesize(UTTERANCE_A, lead=1.5, tail=GAP_SECONDS))
    params_b, second = read_pcm(synthesize(UTTERANCE_B, lead=0.0, tail=0.0))
    if params_b != (channels, width, rate):
        raise SystemExit(f"sample format mismatch between utterances: {params_b} vs {(channels, width, rate)}")
    silence = b"\x00" * (int(TAIL_SECONDS * rate) * channels * width)
    with wave.open(str(directory / f"{SLUG}.wav"), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(first + second + silence)
    frame = channels * width * rate
    return {"first": len(first) / frame, "second": len(second) / frame, "tail": TAIL_SECONDS}


if __name__ == "__main__":
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        raise SystemExit("real inference is dev-only and cannot run in CI")
    if "--allow-paid-dev-inference" not in sys.argv:
        raise SystemExit("explicit paid-dev opt-in required (--allow-paid-dev-inference)")
    speech_dir = Path(tempfile.mkdtemp(prefix="voice-call-orchestration-speech-", dir="/tmp"))
    print(f"speaker audio: {json.dumps(generate_speech(speech_dir))} in {speech_dir}", flush=True)
    os.environ.update(VOICE_CALL_REAL_DEV="1", VOICE_CALL_REAL_SPEECH_DIR=str(speech_dir),
                      OPENMATES_PROOF_CHROME=str(installed_chromium()))
    raise SystemExit(main(spec=SPEC, title="Voice call orchestration", doc=__doc__, grep_option=False, patterns=PATTERNS))
