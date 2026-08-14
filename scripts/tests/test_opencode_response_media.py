# contract-test-file: tooling
"""Tests for the OpenCode response-media upload helper.

Purpose: agents need a deterministic way to upload temporary screenshots and
videos for Markdown responses without exposing files through public buckets.
Security: tests use dry-run URLs only; no Docker, Vault, or S3 calls run here.
Run: python3 -m pytest scripts/tests/test_opencode_response_media.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import opencode_response_media as media


def test_dry_run_image_outputs_markdown_and_html(tmp_path: Path, capsys) -> None:
    image = tmp_path / "demo image.png"
    image.write_bytes(b"fake png bytes")

    code = media.main([
        str(image),
        "--alt",
        "Demo image",
        "--dry-run",
        "--output",
        "json",
    ])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["bucket"] == media.DEV_BUCKET_NAME
    assert data["content_type"] == "image/png"
    assert data["expires_in"] == media.DEFAULT_EXPIRES_SECONDS
    assert data["kind"] == "image"
    assert data["snippets"]["markdown"].startswith("![Demo image](https://example.invalid/")
    assert data["snippets"]["html"].startswith('<img src="https://example.invalid/')


def test_dry_run_video_outputs_html_video(tmp_path: Path, capsys) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"fake mp4 bytes")

    code = media.main([
        str(video),
        "--alt",
        "Demo video",
        "--dry-run",
        "--output",
        "json",
    ])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["content_type"] == "video/mp4"
    assert data["kind"] == "video"
    assert data["snippets"]["markdown"].startswith("[Demo video](https://example.invalid/")
    assert "<video controls" in data["snippets"]["html"]
    assert 'type="video/mp4"' in data["snippets"]["html"]


def test_rejects_unsupported_media_type(tmp_path: Path, capsys) -> None:
    text = tmp_path / "not-media.txt"
    text.write_text("not media", encoding="utf-8")

    code = media.main([str(text), "--dry-run"])

    assert code == 1
    assert "Unsupported media type" in capsys.readouterr().err


def test_rejects_presigned_url_ttl_above_bucket_retention(tmp_path: Path, capsys) -> None:
    image = tmp_path / "demo.png"
    image.write_bytes(b"fake png bytes")

    code = media.main([
        str(image),
        "--dry-run",
        "--expires-in",
        str(media.MAX_EXPIRES_SECONDS + 1),
    ])

    assert code == 1
    assert "--expires-in must be at most" in capsys.readouterr().err
