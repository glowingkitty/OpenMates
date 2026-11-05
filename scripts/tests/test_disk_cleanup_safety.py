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
import os
import json
import subprocess
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

    class EmptyRemoteClient:
        def list_objects_v2(self, **_kwargs: object) -> dict:
            return {"Contents": [], "IsTruncated": False}

    class SuccessfulUpload:
        client = EmptyRemoteClient()
        environment = "development"

        async def upload_file(self, _bucket: str, key: str, _body: bytes, _content_type: str) -> None:
            uploaded_keys.append(key)

        async def delete_file(self, _bucket: str, _key: str) -> None:
            raise AssertionError("no remote keys should be pruned")

    result = asyncio.run(run_tests._upload_recording_files(root, SuccessfulUpload()))

    assert result == (2, 1)
    assert sorted(uploaded_keys) == ["latest/chat-flow/video.webm", "latest/index.json"]
    assert not bundle.exists()
    assert (root / "index.json").is_file()


def test_recording_upload_prunes_remote_keys_outside_latest_snapshot(tmp_path: Path) -> None:
    run_tests = load_run_tests_module()
    root = tmp_path / "latest"
    bundle = root / "chat-flow"
    bundle.mkdir(parents=True)
    (bundle / "video.webm").write_bytes(b"video")
    (root / "index.json").write_text("{}", encoding="utf-8")
    deleted_keys: list[str] = []

    class RemoteClient:
        def list_objects_v2(self, **_kwargs: object) -> dict:
            return {
                "Contents": [
                    {"Key": "latest/chat-flow/video.webm"},
                    {"Key": "latest/old-flow/video.webm"},
                ],
                "IsTruncated": False,
            }

    class SuccessfulUpload:
        client = RemoteClient()
        environment = "development"

        async def upload_file(self, *_args: object) -> None:
            return None

        async def delete_file(self, _bucket: str, key: str) -> None:
            deleted_keys.append(key)

    result = asyncio.run(run_tests._upload_recording_files(root, SuccessfulUpload()))

    assert result == (2, 1)
    assert deleted_keys == ["latest/old-flow/video.webm"]


def test_docker_cleanup_is_bounded_and_never_prunes_data_containers_or_volumes() -> None:
    script = (ROOT / "scripts" / "docker-cleanup.sh").read_text(encoding="utf-8")

    assert "flock" in script
    assert "timeout" in script
    assert "--keep-storage" in script
    assert "docker volume prune" not in script
    assert "docker container prune" not in script
    assert "docker system prune" not in script


def test_pressure_cleanup_reclaims_aged_dangling_images_without_tagged_pruning(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "docker-cleanup.sh"
    script.write_text((ROOT / "scripts/docker-cleanup.sh").read_text())
    binaries = tmp_path / "bin"
    binaries.mkdir()
    calls = tmp_path / "docker-calls.jsonl"
    stubs = {
        "python3": "import sys\nraise SystemExit(3 if 'configured-check' in sys.argv else 0)\n",
        "docker": f"import sys,json\nwith open({str(calls)!r},'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n",
        "df": "print('Filesystem 1024-blocks Used Available Capacity Mounted on\\nfixture 100 90 10 90% /')\n",
    }
    for name, content in stubs.items():
        path = binaries / name
        path.write_text("#!/usr/bin/python3\n" + content)
        path.chmod(0o755)
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
        env={**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
             "OPENMATES_DOCKER_CLEANUP_LOCK": str(tmp_path / "cleanup.lock")})
    assert result.returncode == 0, result.stderr
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    image_prunes = [command for command in commands if command[:2] == ["image", "prune"]]
    assert image_prunes == [["image", "prune", "-f", "--filter", "until=1h"]]
    assert not any(command[0] in {"volume", "container", "network"} for command in commands)


def test_daily_test_artifacts_are_bounded_to_one_week() -> None:
    run_tests = load_run_tests_module()

    assert run_tests.DAILY_ARTIFACT_RETENTION_DAYS == 7


def test_proof_cleanup_expires_only_manifest_owned_media_without_discord() -> None:
    script = (ROOT / "scripts" / "cleanup-proof-videos.sh").read_text(encoding="utf-8")

    assert "sweep-expired" in script
    assert "DISCORD_WEBHOOK_DEV_SMOKE" not in script
    assert "sweep-publications" not in script
    assert "test-results/proof-videos" in script
    assert "rm " not in script
    assert "docker" not in script
