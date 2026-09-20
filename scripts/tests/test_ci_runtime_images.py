# contract-test-file: tooling
from pathlib import Path

from scripts import ci_runtime_images as runtime


def write(root: Path, relative: str, value: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def test_runtime_keys_change_only_for_declared_compatibility_inputs(tmp_path):
    write(tmp_path, "backend/core/api/Dockerfile.selfhost", "FROM python:3.13")
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==1")
    write(tmp_path, "backend/core/api/main.py", "candidate source is mounted")
    first = runtime.runtime_key(tmp_path, "api")
    write(tmp_path, "backend/core/api/main.py", "changed source")
    assert runtime.runtime_key(tmp_path, "api") == first
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==2")
    assert runtime.runtime_key(tmp_path, "api") != first


def test_cms_runtime_key_includes_every_extension(tmp_path):
    write(tmp_path, "backend/core/directus/Dockerfile", "FROM directus/directus:11.5")
    write(tmp_path, "backend/core/directus/extensions/example/src/index.js", "first")
    first = runtime.runtime_key(tmp_path, "cms")
    write(tmp_path, "backend/core/directus/extensions/example/src/index.js", "second")
    assert runtime.runtime_key(tmp_path, "cms") != first


def test_restore_rejects_mutable_tag_without_matching_label(tmp_path, monkeypatch):
    write(tmp_path, "backend/core/api/Dockerfile.selfhost", "FROM python:3.13")
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==1")
    calls = []

    class Result:
        def __init__(self, code=0, output=""):
            self.returncode = code
            self.stdout = output

    def docker(*args, check=True):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return Result(output="wrong-key\n")
        return Result()

    monkeypatch.setattr(runtime, "docker", docker)
    result = runtime.restore(tmp_path, "api", "ghcr.io/example")
    assert result["reused"] is False
    assert "mismatch" in result["reason"]
    assert not any(call[0] == "tag" for call in calls)
