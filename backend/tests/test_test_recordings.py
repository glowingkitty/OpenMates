# backend/tests/test_test_recordings.py
# Unit tests for the dev-only Playwright recording browser API.
#
# Tests cover production gating, latest index loading, detail manifest loading,
# and presigned URL attachment for private S3 recording assets.
#
# Run: python -m pytest backend/tests/test_test_recordings.py -v

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from backend.core.api.app.routes import test_recordings


class FakeS3Service:
    def generate_presigned_url(self, bucket_name: str, file_key: str, expiration: int = 3600) -> str:
        return f"https://signed.example/{bucket_name}/{file_key}?ttl={expiration}"


def _fake_request() -> Request:
    app = SimpleNamespace(state=SimpleNamespace(s3_service=FakeS3Service()))
    return Request({"type": "http", "method": "GET", "path": "/", "app": app})


def _write_recording_fixture(root, slug: str = "chat-flow") -> None:
    spec_dir = root / slug
    spec_dir.mkdir(parents=True)
    index = {
        "run_id": "run-1",
        "git_sha": "abc123",
        "git_branch": "dev",
        "tests": [
            {
                "spec": "chat-flow.spec.ts",
                "slug": slug,
                "title": "chat-flow",
                "status": "passed",
                "run_id": "run-1",
                "assets": {
                    "thumbnail_key": f"latest/{slug}/thumbnail.png",
                    "video_key": f"latest/{slug}/video.webm",
                },
            }
        ],
    }
    manifest = {
        "spec": "chat-flow.spec.ts",
        "slug": slug,
        "title": "chat-flow",
        "status": "passed",
        "run_id": "run-1",
        "assets": {
            "thumbnail_key": f"latest/{slug}/thumbnail.png",
            "video_key": f"latest/{slug}/video.webm",
            "report_key": f"latest/{slug}/report.md",
            "screenshot_keys": [f"latest/{slug}/screenshots/01-home.png"],
        },
        "steps": [
            {
                "index": 1,
                "type": "checkpoint",
                "title": "Opened home",
                "screenshot_key": f"latest/{slug}/screenshots/01-home.png",
            }
        ],
    }
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (spec_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_manifest_only_fixture(root, slug: str = "daily-inspiration-chat-flow") -> None:
    spec_dir = root / slug
    spec_dir.mkdir(parents=True)
    manifest = {
        "spec": f"{slug}.spec.ts",
        "slug": slug,
        "title": slug,
        "status": "passed",
        "run_id": "run-2",
        "duration_seconds": 12,
        "assets": {
            "thumbnail_key": f"latest/{slug}/thumbnail.png",
            "video_key": f"latest/{slug}/video.webm",
        },
        "steps": [],
    }
    (spec_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_artifact_meta_only_fixture(root, slug: str = "chat-flow") -> None:
    spec_dir = root / slug
    spec_dir.mkdir(parents=True)
    meta = {
        "spec": f"{slug}.spec.ts",
        "slug": slug,
        "video_files": ["video.webm"],
        "thumbnail_file": "thumbnail.png",
        "screenshot_files": ["screenshots/01-home.png", "screenshots/02-chat.png"],
    }
    (spec_dir / "artifact-meta.json").write_text(json.dumps(meta), encoding="utf-8")


@pytest.mark.asyncio
async def test_list_test_recordings_signs_latest_assets(tmp_path, monkeypatch):
    _write_recording_fixture(tmp_path)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setattr(test_recordings, "TEST_RECORDINGS_PATHS", [tmp_path])
    monkeypatch.setattr(test_recordings, "get_bucket_name", lambda _key, _env: "dev-test-bucket")

    response = await test_recordings.list_test_recordings(_fake_request())

    assert response["run_id"] == "run-1"
    assert response["tests"][0]["assets"]["thumbnail_url"].startswith(
        "https://signed.example/dev-test-bucket/latest/chat-flow/thumbnail.png"
    )
    assert response["tests"][0]["assets"]["video_url"].startswith(
        "https://signed.example/dev-test-bucket/latest/chat-flow/video.webm"
    )


@pytest.mark.asyncio
async def test_list_test_recordings_includes_manifest_dirs_not_in_latest_index(tmp_path, monkeypatch):
    _write_recording_fixture(tmp_path)
    _write_manifest_only_fixture(tmp_path)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setattr(test_recordings, "TEST_RECORDINGS_PATHS", [tmp_path])
    monkeypatch.setattr(test_recordings, "get_bucket_name", lambda _key, _env: "dev-test-bucket")

    response = await test_recordings.list_test_recordings(_fake_request())

    assert {test["slug"] for test in response["tests"]} == {
        "chat-flow",
        "daily-inspiration-chat-flow",
    }
    daily = next(test for test in response["tests"] if test["slug"] == "daily-inspiration-chat-flow")
    assert daily["assets"]["video_url"].startswith(
        "https://signed.example/dev-test-bucket/latest/daily-inspiration-chat-flow/video.webm"
    )


@pytest.mark.asyncio
async def test_list_and_detail_include_artifact_meta_only_recordings(tmp_path, monkeypatch):
    _write_recording_fixture(tmp_path)
    _write_artifact_meta_only_fixture(tmp_path, "legacy-video")
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setattr(test_recordings, "TEST_RECORDINGS_PATHS", [tmp_path])
    monkeypatch.setattr(test_recordings, "get_bucket_name", lambda _key, _env: "dev-test-bucket")

    response = await test_recordings.list_test_recordings(_fake_request())
    assert "legacy-video" in {test["slug"] for test in response["tests"]}

    detail = await test_recordings.get_test_recording("legacy-video", _fake_request())
    assert detail["assets"]["video_url"].startswith(
        "https://signed.example/dev-test-bucket/latest/legacy-video/video.webm"
    )
    assert len(detail["steps"]) == 2
    assert detail["steps"][0]["screenshot_url"].startswith(
        "https://signed.example/dev-test-bucket/latest/legacy-video/screenshots/01-home.png"
    )


@pytest.mark.asyncio
async def test_get_test_recording_signs_step_screenshots(tmp_path, monkeypatch):
    _write_recording_fixture(tmp_path)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setattr(test_recordings, "TEST_RECORDINGS_PATHS", [tmp_path])
    monkeypatch.setattr(test_recordings, "get_bucket_name", lambda _key, _env: "dev-test-bucket")

    response = await test_recordings.get_test_recording("chat-flow", _fake_request())

    assert response["assets"]["report_url"].startswith(
        "https://signed.example/dev-test-bucket/latest/chat-flow/report.md"
    )
    assert response["assets"]["screenshot_urls"][0].startswith(
        "https://signed.example/dev-test-bucket/latest/chat-flow/screenshots/01-home.png"
    )
    assert response["steps"][0]["screenshot_url"].startswith(
        "https://signed.example/dev-test-bucket/latest/chat-flow/screenshots/01-home.png"
    )


@pytest.mark.asyncio
async def test_test_recordings_are_hidden_in_production(tmp_path, monkeypatch):
    _write_recording_fixture(tmp_path)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    monkeypatch.setattr(test_recordings, "TEST_RECORDINGS_PATHS", [tmp_path])

    with pytest.raises(test_recordings.HTTPException) as exc:
        await test_recordings.list_test_recordings(_fake_request())

    assert exc.value.status_code == 404
