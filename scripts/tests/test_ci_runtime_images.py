# contract-test-file: tooling
import hashlib
import json
from pathlib import Path

from scripts import ci_runtime_images as runtime


PIN = "sha256:" + "a" * 64


def pinned(image: str) -> str:
    return f"FROM {image}@{PIN}"


def write(root: Path, relative: str, value: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def test_runtime_keys_change_only_for_declared_compatibility_inputs(tmp_path):
    write(tmp_path, "backend/core/api/Dockerfile.selfhost", pinned("python:3.13"))
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==1")
    write(tmp_path, "backend/core/api/main.py", "candidate source is mounted")
    first = runtime.runtime_key(tmp_path, "api")
    write(tmp_path, "backend/core/api/main.py", "changed source")
    assert runtime.runtime_key(tmp_path, "api") == first
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==2")
    assert runtime.runtime_key(tmp_path, "api") != first


def test_cms_runtime_key_includes_every_extension(tmp_path):
    write(tmp_path, "backend/core/directus/Dockerfile", pinned("directus/directus:11.5"))
    write(tmp_path, "backend/core/directus/extensions/example/src/index.js", "first")
    first = runtime.runtime_key(tmp_path, "cms")
    write(tmp_path, "backend/core/directus/extensions/example/src/index.js", "second")
    assert runtime.runtime_key(tmp_path, "cms") != first


def test_schema_runtime_key_includes_schema_setup_and_directus_runtime(tmp_path):
    write(tmp_path, "scripts/ci_schema_image.Dockerfile", pinned("postgres:13-alpine"))
    write(tmp_path, "scripts/ci_runtime_images.py", "runtime key implementation")
    write(tmp_path, "scripts/ci_schema_bundle.py", "sanitizer = 1")
    write(tmp_path, "scripts/ci_environment.py", "restore = 1")
    write(tmp_path, "backend/core/directus/Dockerfile", pinned("directus/directus:11.5"))
    write(tmp_path, "backend/core/directus/Dockerfile.setup.selfhost", pinned("python:3.13"))
    write(tmp_path, "backend/core/directus/extensions/example/src/index.js", "extension")
    write(tmp_path, "backend/core/directus/schemas/chats.yml", "collection: chats")
    write(tmp_path, "backend/core/directus/setup/setup_schemas.py", "setup = 1")
    first = runtime.runtime_key(tmp_path, "schema")
    write(tmp_path, "backend/core/directus/schemas/chats.yml", "collection: chats-v2")
    assert runtime.runtime_key(tmp_path, "schema") != first
    write(tmp_path, "backend/core/directus/schemas/chats.yml", "collection: chats")
    write(tmp_path, "backend/core/directus/setup/setup_schemas.py", "setup = 2")
    assert runtime.runtime_key(tmp_path, "schema") != first


def test_schema_runtime_key_includes_producer_sanitizer_and_restore_code(tmp_path):
    write(tmp_path, "scripts/ci_schema_image.Dockerfile", pinned("postgres:13-alpine"))
    write(tmp_path, "scripts/ci_runtime_images.py", "runtime key implementation")
    write(tmp_path, "scripts/ci_schema_bundle.py", "sanitizer = 1")
    write(tmp_path, "scripts/ci_environment.py", "restore = 1")
    write(tmp_path, "backend/core/directus/Dockerfile", pinned("directus/directus:11.5"))
    write(tmp_path, "backend/core/directus/Dockerfile.setup.selfhost", pinned("python:3.13"))
    write(tmp_path, "backend/core/directus/setup/setup_schemas.py", "activation = 1")
    first = runtime.runtime_key(tmp_path, "schema")
    write(tmp_path, "scripts/ci_schema_bundle.py", "sanitizer = 2")
    assert runtime.runtime_key(tmp_path, "schema") != first
    write(tmp_path, "scripts/ci_schema_bundle.py", "sanitizer = 1")
    write(tmp_path, "scripts/ci_environment.py", "restore = 2")
    assert runtime.runtime_key(tmp_path, "schema") != first


def test_runtime_key_ignores_untracked_python_cache(tmp_path):
    write(tmp_path, "scripts/ci_schema_image.Dockerfile", pinned("postgres:13-alpine"))
    write(tmp_path, "scripts/ci_runtime_images.py", "runtime key implementation")
    write(tmp_path, "scripts/ci_schema_bundle.py", "sanitizer = 1")
    write(tmp_path, "scripts/ci_environment.py", "restore = 1")
    write(tmp_path, "backend/core/directus/Dockerfile", pinned("directus/directus:11.5"))
    write(tmp_path, "backend/core/directus/Dockerfile.setup.selfhost", pinned("python:3.13"))
    write(tmp_path, "backend/core/directus/setup/setup_schemas.py", "activation = 1")
    first = runtime.runtime_key(tmp_path, "schema")
    write(tmp_path, "backend/core/directus/setup/__pycache__/setup_schemas.pyc", "changing cache")
    assert runtime.runtime_key(tmp_path, "schema") == first


def test_runtime_key_rejects_mutable_vendor_base(tmp_path):
    write(tmp_path, "backend/core/api/Dockerfile.selfhost", "FROM python:3.13-slim")
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==1")
    try:
        runtime.runtime_key(tmp_path, "api")
    except RuntimeError as exc:
        assert "digest-pinned" in str(exc)
    else:
        raise AssertionError("mutable base image unexpectedly accepted")


def test_restore_rejects_mutable_tag_without_matching_label(tmp_path, monkeypatch):
    write(tmp_path, "backend/core/api/Dockerfile.selfhost", pinned("python:3.13"))
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


def test_manifest_archive_restore_checks_hash_key_and_standard_tag(tmp_path, monkeypatch):
    write(tmp_path, "backend/core/api/Dockerfile.selfhost", pinned("python:3.13"))
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==1")
    archive = tmp_path / "bundle/images/api.tar"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"docker archive")
    key = runtime.runtime_key(tmp_path, "api")
    calls = []

    class Result:
        returncode = 0

        def __init__(self, output=""):
            self.stdout = output

    def docker(*args, check=True):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return Result(key + "\n")
        return Result()

    monkeypatch.setattr(runtime, "docker", docker)
    result = runtime.restore_manifest_entry(
        tmp_path,
        {
            "kind": "api",
            "runtime_key": key,
            "archive_path": "images/api.tar",
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "image_ref": "openmates-ci-api:local",
        },
        tmp_path / "bundle/manifest.json",
    )
    assert result["reused"] is True
    assert result["source"] == "verified-archive"
    assert ("load", "--input", str(archive)) in calls


def test_manifest_archive_restore_rejects_corruption_before_docker(tmp_path, monkeypatch):
    write(tmp_path, "backend/core/api/Dockerfile.selfhost", pinned("python:3.13"))
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==1")
    archive = tmp_path / "bundle/images/api.tar"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"corrupt")
    calls = []
    monkeypatch.setattr(runtime, "docker", lambda *args, **kwargs: calls.append(args))
    entry = {
        "kind": "api",
        "runtime_key": runtime.runtime_key(tmp_path, "api"),
        "archive_path": "images/api.tar",
        "archive_sha256": "0" * 64,
        "image_ref": "openmates-ci-api:local",
    }
    try:
        runtime.restore_manifest_entry(
            tmp_path, entry, tmp_path / "bundle/manifest.json"
        )
    except RuntimeError as exc:
        assert "checksum mismatch" in str(exc)
    else:
        raise AssertionError("corrupt archive unexpectedly accepted")
    assert calls == []


def test_manifest_registry_restore_pulls_exact_digest_and_rechecks_identity(
    tmp_path, monkeypatch
):
    write(tmp_path, "backend/core/api/Dockerfile.selfhost", pinned("python:3.13"))
    write(tmp_path, "backend/core/api/requirements.txt", "fastapi==1")
    key = runtime.runtime_key(tmp_path, "api")
    digest = "ghcr.io/example/openmates-api@sha256:" + "b" * 64
    calls = []

    class Result:
        returncode = 0

        def __init__(self, output=""):
            self.stdout = output

    def docker(*args, check=True):
        calls.append(args)
        if args[:2] == ("image", "inspect") and args[-1] == "{{json .RepoDigests}}":
            return Result(json.dumps([digest]))
        if args[:2] == ("image", "inspect"):
            return Result(key)
        return Result()

    monkeypatch.setattr(runtime, "docker", docker)
    result = runtime.restore_manifest_entry(
        tmp_path,
        {"kind": "api", "runtime_key": key, "repository_digest": digest},
        tmp_path / "manifest.json",
    )
    assert result["source"] == "immutable-registry"
    assert calls[0] == ("pull", digest)
    assert ("tag", digest, "openmates-ci-api:local") in calls


def test_load_manifest_requires_versioned_atomic_image_list(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"format_version": 2, "images": []}))
    assert runtime.load_manifest(path)["images"] == []
    path.write_text(json.dumps({"format_version": 1, "images": []}))
    try:
        runtime.load_manifest(path)
    except RuntimeError as exc:
        assert "unsupported format" in str(exc)
    else:
        raise AssertionError("stale manifest unexpectedly accepted")
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "runtime_images": {"format_version": 2, "images": []},
            }
        )
    )
    assert runtime.load_manifest(path)["images"] == []
