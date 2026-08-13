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
        async def upload_file(self, _bucket: str, key: str, _body: bytes, _content_type: str) -> None:
            uploaded_keys.append(key)

    result = asyncio.run(run_tests._upload_recording_files(root, SuccessfulUpload()))

    assert result == (2, 1)
    assert sorted(uploaded_keys) == ["latest/chat-flow/video.webm", "latest/index.json"]
    assert not bundle.exists()
    assert (root / "index.json").is_file()


def test_docker_cleanup_is_bounded_and_never_prunes_data_containers_or_volumes() -> None:
    script = (ROOT / "scripts" / "docker-cleanup.sh").read_text(encoding="utf-8")

    assert "flock" in script
    assert "timeout" in script
    assert "--keep-storage" in script
    assert "docker volume prune" not in script
    assert "docker container prune" not in script
    assert "docker system prune" not in script
