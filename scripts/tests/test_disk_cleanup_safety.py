"""Regression coverage for local recording and Docker cache cleanup.

The cleanup contract is intentionally conservative: local Playwright bundles
are disposable only after every S3 object upload succeeds, and Docker cleanup
must never prune volumes or containers.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import asyncio
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_run_tests_module():
    path = ROOT / "scripts" / "run_tests.py"
    spec = importlib.util.spec_from_file_location("run_tests_disk_cleanup", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_confirmed_recording_upload_cleanup_preserves_index(tmp_path: Path) -> None:
    run_tests = load_run_tests_module()
    root = tmp_path / "latest"
    bundle = root / "chat-flow"
    bundle.mkdir(parents=True)
    (bundle / "video.webm").write_bytes(b"video")
    (root / "index.json").write_text("{}", encoding="utf-8")

    deleted = run_tests._delete_uploaded_recording_bundles(root)

    assert deleted == 1
    assert not bundle.exists()
    assert (root / "index.json").is_file()


def test_recording_upload_failure_preserves_local_snapshot(tmp_path: Path) -> None:
    run_tests = load_run_tests_module()
    root = tmp_path / "latest"
    bundle = root / "chat-flow"
    bundle.mkdir(parents=True)
    (bundle / "video.webm").write_bytes(b"video")

    class FailedUpload:
        async def upload_file(self, *_args: object) -> None:
            raise RuntimeError("synthetic upload failure")

    try:
        asyncio.run(run_tests._upload_recording_files(root, FailedUpload()))
    except RuntimeError as exc:
        assert "synthetic upload failure" in str(exc)
    else:
        raise AssertionError("upload failure should propagate")

    assert (bundle / "video.webm").is_file()


def test_complete_recording_upload_deletes_only_bundle_directories(tmp_path: Path) -> None:
    run_tests = load_run_tests_module()
    root = tmp_path / "latest"
    bundle = root / "chat-flow"
    bundle.mkdir(parents=True)
    (bundle / "video.webm").write_bytes(b"video")
    (root / "index.json").write_text("{}", encoding="utf-8")
    uploaded_keys: list[str] = []

    class SuccessfulUpload:
        client = object()

        async def upload_file(self, _bucket: str, key: str, _body: bytes, _content_type: str) -> None:
            uploaded_keys.append(key)

        async def delete_file(self, *_args: object) -> None:
            raise AssertionError("complete snapshot should not prune freshly uploaded keys")

    async def no_stale_files(_s3_service: object, desired_keys: set[str]) -> int:
        assert desired_keys == {"latest/chat-flow/video.webm", "latest/index.json"}
        return 0

    run_tests._prune_stale_recording_files = no_stale_files

    result = asyncio.run(run_tests._upload_recording_files(root, SuccessfulUpload()))

    assert result == (2, 1)
    assert sorted(uploaded_keys) == ["latest/chat-flow/video.webm", "latest/index.json"]
    assert not bundle.exists()
    assert (root / "index.json").is_file()


def test_recording_upload_prunes_stale_remote_snapshot_files(monkeypatch) -> None:
    run_tests = load_run_tests_module()
    deleted_keys: list[str] = []
    requests: list[dict[str, str]] = []

    config_module = types.ModuleType("backend.core.api.app.services.s3.config")
    config_module.get_bucket_name = lambda _bucket_key, environment: f"bucket-{environment}"
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.s3.config", config_module)

    class Client:
        def list_objects_v2(self, **request: str) -> dict[str, object]:
            requests.append(request)
            return {
                "Contents": [
                    {"Key": "latest/chat-flow/video.webm"},
                    {"Key": "latest/removed-flow/video.webm"},
                ],
                "IsTruncated": False,
            }

    class S3Service:
        client = Client()
        environment = "development"

        async def delete_file(self, _bucket_key: str, key: str) -> None:
            deleted_keys.append(key)

    pruned = asyncio.run(
        run_tests._prune_stale_recording_files(
            S3Service(),
            {"latest/chat-flow/video.webm"},
        )
    )

    assert pruned == 1
    assert deleted_keys == ["latest/removed-flow/video.webm"]
    assert requests == [{"Bucket": "bucket-development", "Prefix": "latest/"}]


def test_docker_cleanup_is_bounded_and_never_prunes_data_containers_or_volumes() -> None:
    script = (ROOT / "scripts" / "docker-cleanup.sh").read_text(encoding="utf-8")

    assert "flock" in script
    assert "timeout" in script
    assert "--keep-storage" in script
    assert "docker volume prune" not in script
    assert "docker container prune" not in script
    assert "docker system prune" not in script


def test_daily_test_artifacts_are_bounded_to_one_week() -> None:
    run_tests = load_run_tests_module()

    assert run_tests.DAILY_ARTIFACT_RETENTION_DAYS == 7


def test_opencode_cleanup_includes_archived_sessions_and_bounds_todo_retention() -> None:
    script = (ROOT / "scripts" / "cleanup-opencode-sessions.sh").read_text(encoding="utf-8")

    assert "time_archived IS NULL" not in script
    assert "OPENMATES_OPENCODE_TODO_RETENTION_DAYS:-90" in script
    assert "opencode session delete" in script


def test_proof_cleanup_expires_only_manifest_owned_media_without_discord() -> None:
    script = (ROOT / "scripts" / "cleanup-proof-videos.sh").read_text(encoding="utf-8")

    assert "sweep-expired" in script
    assert "DISCORD_WEBHOOK_DEV_SMOKE" not in script
    assert "sweep-publications" not in script
    assert "test-results/proof-videos" in script
    assert "rm " not in script
    assert "docker" not in script
