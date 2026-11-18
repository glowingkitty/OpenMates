#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Measurement-only voice-call latency probe on the real dev stack (TASK-9356 research).

Builds one fake-microphone WAV that speaks several short public questions separated by
long silences (ElevenLabs TTS inside the dev ``api`` container, Vault-backed), records
the exact voiced end of each question in the file, then runs
frontend/apps/web_app/tests/voice-call-latency-probe.spec.ts through the shared
real-test harness (account lease, E2B Playwright run, video, receipt).

  python3 scripts/voice_call_latency_probe.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/voice-latency-probe/run-1 --personal-dev-test-account --allow-paid-dev-inference

Never run in CI. Not deployed: research instrumentation only.
"""

from __future__ import annotations

import array
import base64
import io
import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path

from design_embroidery_web_real_test import ROOT, installed_chromium, main

SPEC = "tests/voice-call-latency-probe.spec.ts"
GENERATOR = ROOT / "backend/scripts/generate_voice_call_speaker_audio.py"
SLUG = "latency"
RATE = 16_000
LEAD_SECONDS = 2.0
GAP_SECONDS = float(os.environ.get("VOICE_LATENCY_GAP_SECONDS", "40"))
QUESTIONS = [
    q for q in os.environ.get("VOICE_LATENCY_QUESTION_LIST", "").split("|") if q
] or [
    "What is the capital of France?",
    "Why is the sky blue?",
    "How far away is the moon?",
    "Give me three quick tips for sleeping better.",
    "What is a good name for a grey cat?",
    "How do vaccines work, in simple words?",
]


def speech_pcm(text: str) -> bytes:
    with GENERATOR.open("rb") as script:
        run = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "api",
                "python",
                "-",
                "--text",
                text,
                "--lead-seconds",
                "0",
                "--tail-seconds",
                "0",
            ],
            stdin=script,
            capture_output=True,
            check=False,
            timeout=180,
        )
    if run.returncode:
        raise SystemExit(f"speaker audio generation failed (exit {run.returncode})")
    data = base64.b64decode(
        json.loads(run.stdout.decode().strip().splitlines()[-1])["wav_base64"]
    )
    with wave.open(io.BytesIO(data)) as handle:
        return handle.readframes(handle.getnframes())


def voiced_bounds(pcm: bytes) -> tuple[float, float]:
    """First and last 20 ms window whose peak exceeds 3% of full scale, in seconds."""
    samples = array.array("h", pcm)
    window = RATE // 50
    loud = [
        i
        for i in range(0, len(samples), window)
        if max(map(abs, samples[i : i + window]), default=0) > 1000
    ]
    return (
        (loud[0] / RATE, (loud[-1] + window) / RATE)
        if loud
        else (0.0, len(samples) / RATE)
    )


def build(directory: Path) -> dict:
    pcm, offsets, cursor = b"", [], LEAD_SECONDS
    pcm += b"\0\0" * int(RATE * LEAD_SECONDS)
    for text in QUESTIONS:
        piece = speech_pcm(text)
        start, end = voiced_bounds(piece)
        offsets.append(
            {
                "question": text,
                "voiced_start_s": round(cursor + start, 3),
                "voiced_end_s": round(cursor + end, 3),
            }
        )
        pcm += piece + b"\0\0" * int(RATE * GAP_SECONDS)
        cursor += len(piece) / (2 * RATE) + GAP_SECONDS
    pcm += b"\0\0" * int(
        RATE * 300
    )  # long tail: the file must not loop back to the first question
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm)
    (directory / f"{SLUG}.wav").write_bytes(buffer.getvalue())
    timeline = {"questions": offsets, "script_seconds": round(cursor, 1)}
    (directory / "timeline.json").write_text(json.dumps(timeline))
    return timeline


if __name__ == "__main__":
    if any(
        os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")
    ):
        raise SystemExit("real inference is dev-only and cannot run in CI")
    speech_dir = Path(tempfile.mkdtemp(prefix="voice-latency-speech-", dir="/tmp"))
    timeline = build(speech_dir)
    print(f"LATENCY_TIMELINE {json.dumps(timeline)} in {speech_dir}", flush=True)
    os.environ.update(
        VOICE_CALL_REAL_DEV="1",
        VOICE_LATENCY_PROBE="1",
        VOICE_CALL_REAL_SPEECH_DIR=str(speech_dir),
        VOICE_CALL_REAL_SCENARIO=SLUG,
        VOICE_LATENCY_QUESTIONS=str(len(QUESTIONS)),
        VOICE_LATENCY_CALL_SECONDS=str(int(timeline["script_seconds"]) + 5),
        OPENMATES_PROOF_CHROME=str(installed_chromium()),
        OPENMATES_HEAVY_REMOTE_ENV=(
            "VOICE_CALL_REAL_DEV,VOICE_LATENCY_PROBE,VOICE_CALL_REAL_SPEECH_DIR,"
            "VOICE_CALL_REAL_SCENARIO,VOICE_LATENCY_QUESTIONS,VOICE_LATENCY_CALL_SECONDS"
        ),
        OPENMATES_HEAVY_REMOTE_DIRS=str(speech_dir),
    )
    raise SystemExit(
        main(
            spec=SPEC,
            title="Voice call latency probe",
            doc=__doc__,
            patterns=(("latency_report", r"LATENCY_REPORT ([^\n]+)"),),
        )
    )
