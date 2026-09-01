# contract-test-file: tooling
"""Tests for the OpenCode response-media upload helper.

Purpose: agents need a deterministic way to upload temporary screenshots,
videos, and PDFs for responses without exposing files through public buckets.
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
    assert 'style="width: 100%; height: auto;"' in data["snippets"]["html"]


def test_dry_run_pdf_outputs_readable_document_link(tmp_path: Path, capsys) -> None:
    document = tmp_path / "contract approval.pdf"
    document.write_bytes(b"%PDF-1.4 fake")

    code = media.main([
        str(document),
        "--alt",
        "Read Contract PDF",
        "--dry-run",
        "--output",
        "json",
    ])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["content_type"] == "application/pdf"
    assert data["kind"] == "document"
    assert data["snippets"]["markdown"].startswith("[Read Contract PDF](https://example.invalid/")
    assert 'type="application/pdf"' in data["snippets"]["html"]


def test_dry_run_video_with_captions_outputs_toggleable_track(tmp_path: Path, capsys) -> None:
    video = tmp_path / "demo.mp4"
    captions = tmp_path / "captions.vtt"
    video.write_bytes(b"fake mp4 bytes")
    captions.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nVisible.\n", encoding="utf-8")

    code = media.main([
        str(video),
        "--captions",
        str(captions),
        "--alt",
        "Demo video",
        "--dry-run",
        "--output",
        "json",
    ])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["captions"]["content_type"] == "text/vtt"
    assert data["captions"]["expires_in"] == data["expires_in"]
    html = data["snippets"]["html"]
    assert 'crossorigin="anonymous"' in html
    assert '<track kind="captions"' in html
    assert 'srclang="und"' in html
    assert 'label="Captions"' in html
    assert " default>" in html


def test_latest_run_type_uses_content_addressed_immutable_keys(tmp_path: Path, capsys) -> None:
    video = tmp_path / "first-recording.webm"
    captions = tmp_path / "first-captions.vtt"
    video.write_bytes(b"fake webm bytes")
    captions.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nVisible.\n", encoding="utf-8")

    code = media.main([
        str(video),
        "--captions",
        str(captions),
        "--latest-run-type",
        "spec-ts-web-laptop",
        "--dry-run",
        "--output",
        "json",
    ])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["latest_run_type"] == "spec-ts-web-laptop"
    video_digest = media.hashlib.sha256(video.read_bytes()).hexdigest()
    captions_digest = media.hashlib.sha256(captions.read_bytes()).hexdigest()
    prefix = f"opencode-responses/runs/spec-ts-web-laptop/{video_digest}"
    assert data["key"] == f"{prefix}/video.webm"
    assert data["captions"]["key"] == f"{prefix}/captions-{captions_digest}.vtt"

    second_video = tmp_path / "second-recording.webm"
    second_video.write_bytes(b"different webm bytes")
    assert media.main([
        str(second_video),
        "--latest-run-type",
        "spec-ts-web-laptop",
        "--dry-run",
        "--output",
        "json",
    ]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["key"] != data["key"]
    assert "/latest/" not in second["key"]


def test_latest_run_type_rejects_unsafe_scope(tmp_path: Path, capsys) -> None:
    video = tmp_path / "demo.webm"
    video.write_bytes(b"fake webm bytes")

    code = media.main([str(video), "--latest-run-type", "../unsafe", "--dry-run"])

    assert code == 1
    assert "--latest-run-type" in capsys.readouterr().err


def test_rejects_malformed_or_overlapping_webvtt(tmp_path: Path, capsys) -> None:
    video = tmp_path / "demo.mp4"
    captions = tmp_path / "captions.vtt"
    video.write_bytes(b"fake mp4 bytes")
    captions.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nFirst.\n\n00:00:01.500 --> 00:00:03.000\nOverlap.\n",
        encoding="utf-8",
    )

    code = media.main([str(video), "--captions", str(captions), "--dry-run"])

    assert code == 1
    assert "ordered and non-overlapping" in capsys.readouterr().err


def test_accepts_crlf_webvtt_and_custom_language(tmp_path: Path, capsys) -> None:
    video = tmp_path / "demo.mp4"
    captions = tmp_path / "captions.vtt"
    video.write_bytes(b"fake mp4 bytes")
    captions.write_bytes(b"WEBVTT\r\n\r\n00:00:00.000 --> 00:00:01.000\r\nSichtbar.\r\n")

    code = media.main([
        str(video),
        "--captions",
        str(captions),
        "--captions-language",
        "de-DE",
        "--captions-label",
        "Deutsch",
        "--dry-run",
        "--output",
        "json",
    ])

    assert code == 0
    html = json.loads(capsys.readouterr().out)["snippets"]["html"]
    assert 'srclang="de-DE"' in html
    assert 'label="Deutsch"' in html


def test_invalid_captions_fail_before_any_upload(tmp_path: Path, monkeypatch, capsys) -> None:
    video = tmp_path / "demo.mp4"
    captions = tmp_path / "captions.vtt"
    video.write_bytes(b"fake mp4 bytes")
    captions.write_text("not webvtt", encoding="utf-8")
    uploads: list[object] = []
    monkeypatch.setattr(media, "upload_via_api_container", lambda **kwargs: uploads.append(kwargs))

    code = media.main([str(video), "--captions", str(captions)])

    assert code == 1
    assert uploads == []
    assert "WebVTT" in capsys.readouterr().err


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


def test_dry_run_video_with_poster_outputs_uploaded_poster(tmp_path: Path, capsys) -> None:
    video = tmp_path / "demo.mp4"
    poster = tmp_path / "poster.png"
    video.write_bytes(b"fake mp4 bytes")
    poster.write_bytes(b"fake png bytes")

    code = media.main([
        str(video),
        "--poster",
        str(poster),
        "--latest-run-type",
        "spec-ts-web-laptop",
        "--dry-run",
        "--output",
        "json",
    ])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    video_digest = media.hashlib.sha256(video.read_bytes()).hexdigest()
    poster_digest = media.hashlib.sha256(poster.read_bytes()).hexdigest()
    assert data["poster"]["key"] == (
        f"opencode-responses/runs/spec-ts-web-laptop/{video_digest}/poster-{poster_digest}.png"
    )
    assert f'poster="{data["poster"]["url"]}"' in data["snippets"]["html"]


def test_rejects_oversized_poster_before_any_upload(tmp_path: Path, monkeypatch, capsys) -> None:
    video = tmp_path / "demo.mp4"
    poster = tmp_path / "poster.png"
    video.write_bytes(b"v")
    poster.write_bytes(b"oversized")
    uploads = []
    monkeypatch.setattr(media, "MAX_MEDIA_BYTES", 4)
    monkeypatch.setattr(media, "upload_via_api_container", lambda **kwargs: uploads.append(kwargs))

    code = media.main([str(video), "--poster", str(poster)])

    assert code == 1
    assert uploads == []
    assert "Poster file exceeds" in capsys.readouterr().err
