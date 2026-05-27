# backend/tests/test_rest_api_music.py
#
# REST API integration coverage for the music app. The generate skill is
# asynchronous: POST returns a Celery task ID immediately, then /v1/tasks/{id}
# exposes the completed encrypted audio metadata after Google Lyria finishes.
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_music.py

import os

import pytest

from backend.apps.music.tasks.generate_task import _embed_generation_metadata
from tests.conftest import poll_task_until_complete


def test_music_metadata_embedded_in_mp3_bytes():
    """Generated MP3 bytes include OpenMates AI generation metadata tags."""
    result = _embed_generation_metadata(
        b"\xff\xfbmp3-audio",
        "audio/mpeg",
        prompt="Upbeat synth jingle",
        model="lyria-3-pro-preview",
        provider="Google Vertex AI",
        generated_at="2026-05-22T12:00:00+00:00",
        duration_seconds=30,
        mode="jingle",
        style="warm synth",
        negative_prompt="distortion",
        seed=123,
        watermarking="SynthID",
    )

    assert result.startswith(b"ID3")
    assert b"OpenMates Prompt" in result
    assert b"Upbeat synth jingle" in result
    assert b"lyria-3-pro-preview" in result
    assert result.endswith(b"\xff\xfbmp3-audio")


def test_music_metadata_embedded_in_wav_info_chunk():
    """Generated WAV bytes include a LIST/INFO metadata chunk."""
    wav = (
        b"RIFF" + b"\x28\x00\x00\x00" + b"WAVEfmt " + b"\x10\x00\x00\x00"
        + (b"\x00" * 16) + b"data" + b"\x04\x00\x00\x00" + b"abcd"
    )
    result = _embed_generation_metadata(
        wav,
        "audio/wav",
        prompt="Ambient loop",
        model="lyria-002",
        provider="Google Vertex AI",
        generated_at="2026-05-22T12:00:00+00:00",
        duration_seconds=12,
        mode="loop",
        style=None,
        negative_prompt=None,
        seed=None,
        watermarking="SynthID",
    )

    assert result.startswith(b"RIFF")
    assert b"LIST" in result
    assert b"INFO" in result
    assert b"Ambient loop" in result
    assert b"lyria-002" in result


@pytest.mark.integration
def test_music_generate_metadata_exposed(api_client):
    """GET /v1/apps/music/skills/generate returns public skill metadata."""
    response = api_client.get("/v1/apps/music/skills/generate")
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["id"] == "generate"
    assert data["app_id"] == "music"
    assert data["api_config"]["expose_post"] is True


@pytest.mark.integration
def test_music_generate_rest_task_completes(api_client):
    """POST /v1/apps/music/skills/generate dispatches Lyria and returns audio metadata."""
    if os.getenv("OPENMATES_RUN_MUSIC_GENERATION_TESTS") != "true":
        pytest.skip("Set OPENMATES_RUN_MUSIC_GENERATION_TESTS=true to run Lyria generation.")

    prompt = "A 30 second upbeat electronic test jingle with warm synth pads"
    payload = {
        "requests": [
            {
                "prompt": prompt,
                "mode": "jingle",
                "duration_seconds": 30,
                "model": "lyria-3-clip-preview",
            }
        ]
    }

    response = api_client.post("/v1/apps/music/skills/generate", json=payload, timeout=60.0)
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["success"] is True, data
    assert data["credits_charged"] and data["credits_charged"] > 0

    task_id = data["data"]["task_id"]
    assert task_id

    task_result = poll_task_until_complete(
        api_client,
        task_id,
        max_retries=150,
        poll_interval=2.0,
        log_prefix="[MUSIC REST]",
    )
    result = task_result.get("result") or {}

    assert result["status"] == "finished"
    assert result["type"] == "music"
    assert result["prompt"] == prompt
    assert result["model"] == "lyria-3-clip-preview"
    assert result["s3_base_url"].startswith("https://")
    assert result["aes_key"]
    assert result["aes_nonce"]
    assert result["vault_wrapped_aes_key"]

    original = result["files"]["original"]
    assert original["s3_key"]
    assert original["size_bytes"] > 1000
    assert original["format"] in {"mp3", "wav", "m4a", "ogg"}
    assert original["mime_type"].startswith("audio/")
