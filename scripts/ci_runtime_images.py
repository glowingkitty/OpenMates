#!/usr/bin/env python3
"""Reuse compatible published CI runtimes without trusting mutable image tags.

The dev tag is only a discovery pointer.  Every pulled image must carry the
expected input hash; the local job then records the immutable repository digest
and tags that exact image for the disposable compose stack.  A miss returns to
the workflow's source build path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

try:
    from scripts.ci_environment import (
        SCHEMA_BUNDLE_FORMAT,
        SCHEMA_RESTORE_SEMANTICS,
    )
except ModuleNotFoundError:  # Direct script execution puts scripts/ on sys.path.
    from ci_environment import SCHEMA_BUNDLE_FORMAT, SCHEMA_RESTORE_SEMANTICS


LABEL = "org.openmates.ci.runtime-key"
SCHEMA_FORMAT_LABEL = "org.openmates.ci.schema-bundle-format"
SCHEMA_RESTORE_LABEL = "org.openmates.ci.schema-restore-semantics"
MANIFEST_FORMAT_VERSION = 2
PINNED_BASE = re.compile(r"@sha256:[0-9a-f]{64}(?:\s|$)")
RUNTIME_INPUTS = {
    "api": (
        "backend/core/api/Dockerfile.selfhost",
        "backend/core/api/requirements.txt",
    ),
    "cms": (
        "backend/core/directus/Dockerfile",
        "backend/core/directus/extensions/**/*",
    ),
    "setup": (
        "backend/core/directus/Dockerfile.setup.selfhost",
    ),
    "schema": (
        "scripts/ci_runtime_images.py",
        "scripts/ci_schema_bundle.py",
        "scripts/ci_schema_image.Dockerfile",
        "scripts/ci_environment.py",
        "backend/core/directus/Dockerfile",
        "backend/core/directus/Dockerfile.setup.selfhost",
        "backend/core/directus/extensions/**/*",
        "backend/core/directus/schemas/**/*",
        "backend/core/directus/setup/**/*",
    ),
    "upload": (
        "backend/upload/Dockerfile",
        "backend/upload/requirements.txt",
    ),
}
BASE_DOCKERFILES = {
    "api": ("backend/core/api/Dockerfile.selfhost",),
    "cms": ("backend/core/directus/Dockerfile",),
    "setup": ("backend/core/directus/Dockerfile.setup.selfhost",),
    "schema": (
        "scripts/ci_schema_image.Dockerfile",
        "backend/core/directus/Dockerfile",
        "backend/core/directus/Dockerfile.setup.selfhost",
    ),
    "upload": ("backend/upload/Dockerfile",),
}
RUNTIME_KEY_FACTORS = {
    "schema": {
        "bundle_format": SCHEMA_BUNDLE_FORMAT,
        "restore_semantics": SCHEMA_RESTORE_SEMANTICS,
    }
}
EXECUTED_COMPATIBILITY_INPUTS = {
    "schema": (
        Path(__file__).resolve(),
        Path(__file__).with_name("ci_schema_bundle.py").resolve(),
        Path(__file__).with_name("ci_environment.py").resolve(),
    )
}
IMAGES = {
    "api": ("openmates-api", "openmates-ci-api:local"),
    "cms": ("openmates-directus", "openmates-ci-cms:local"),
    "setup": ("openmates-cms-setup", "openmates-ci-setup:local"),
    "schema": ("openmates-ci-schema", "openmates-ci-database:local"),
    "upload": ("openmates-uploads", "openmates-ci-upload:local"),
}


def input_paths(root: Path, kind: str) -> list[Path]:
    paths: set[Path] = set()
    for pattern in RUNTIME_INPUTS[kind]:
        paths.update(
            path
            for path in root.glob(pattern)
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def pinned_base_identities(root: Path, kind: str) -> tuple[str, ...]:
    identities = []
    for relative in BASE_DOCKERFILES[kind]:
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"Runtime image {kind} lacks Dockerfile {relative}")
        from_lines = [
            line.strip()
            for line in path.read_text().splitlines()
            # Dockerfile heredocs can contain indented SQL ``FROM`` clauses.
            # Base-stage instructions in these canonical files start at column 0.
            if line.upper().startswith("FROM ")
        ]
        if not from_lines or any(not PINNED_BASE.search(line) for line in from_lines):
            raise RuntimeError(
                f"Runtime image {kind} requires digest-pinned base images in {relative}"
            )
        identities.extend(from_lines)
    return tuple(identities)


def runtime_key(root: Path, kind: str) -> str:
    if kind not in RUNTIME_INPUTS:
        raise ValueError(f"Unknown runtime image kind: {kind}")
    digest = hashlib.sha256()
    paths = input_paths(root, kind)
    if not paths:
        raise RuntimeError(f"Runtime image {kind} has no declared inputs")
    pinned_base_identities(root, kind)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    for path in EXECUTED_COMPATIBILITY_INPUTS.get(kind, ()):
        if not path.is_file():
            raise RuntimeError(f"Runtime image {kind} lacks tooling input {path.name}")
        digest.update(f"executed-tooling:{path.name}".encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    for name, value in sorted(RUNTIME_KEY_FACTORS.get(kind, {}).items()):
        digest.update(f"factor:{name}\0{value}".encode() + b"\0")
    return digest.hexdigest()


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], text=True, capture_output=True, check=check, timeout=300
    )


def image_label(image: str, label: str) -> str:
    return docker(
        "image",
        "inspect",
        image,
        "--format",
        f'{{{{ index .Config.Labels "{label}" }}}}',
    ).stdout.strip()


def image_repo_digests(image: str) -> list[str]:
    raw = docker(
        "image", "inspect", image, "--format", "{{json .RepoDigests}}"
    ).stdout
    return json.loads(raw or "[]") or []


def schema_metadata(image: str) -> dict[str, str]:
    return {
        "bundle_format": image_label(image, SCHEMA_FORMAT_LABEL),
        "restore_semantics": image_label(image, SCHEMA_RESTORE_LABEL),
    }


def validate_schema_metadata(metadata: dict) -> None:
    if metadata.get("bundle_format") != SCHEMA_BUNDLE_FORMAT:
        raise RuntimeError("Schema image has an incompatible or missing bundle format")
    if metadata.get("restore_semantics") != SCHEMA_RESTORE_SEMANTICS:
        raise RuntimeError("Schema image has incompatible or missing restore semantics")


def verify_loaded_image(root: Path, kind: str, image: str, expected_key: str) -> dict:
    current_key = runtime_key(root, kind)
    if expected_key != current_key:
        raise RuntimeError(f"Prepared {kind} artifact does not match the candidate inputs")
    actual_key = image_label(image, LABEL)
    if actual_key != expected_key:
        raise RuntimeError(f"Prepared {kind} image runtime compatibility label mismatch")
    metadata = {}
    if kind == "schema":
        metadata = schema_metadata(image)
        validate_schema_metadata(metadata)
    return metadata


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore_manifest_entry(root: Path, entry: dict, manifest_path: Path) -> dict:
    kind = entry.get("kind")
    if kind not in IMAGES:
        raise RuntimeError(f"Prepared artifact has unknown runtime kind: {kind!r}")
    expected_key = entry.get("runtime_key", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_key):
        raise RuntimeError(f"Prepared {kind} artifact lacks a valid runtime key")
    if expected_key != runtime_key(root, kind):
        raise RuntimeError(f"Prepared {kind} artifact does not match the candidate inputs")
    repository_digest = entry.get("repository_digest")
    archive_relative = entry.get("archive_path")
    if bool(repository_digest) == bool(archive_relative):
        raise RuntimeError(
            f"Prepared {kind} artifact must have exactly one immutable source"
        )
    if repository_digest:
        if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", repository_digest):
            raise RuntimeError(f"Prepared {kind} repository digest is not immutable")
        docker("pull", repository_digest)
        image = repository_digest
        metadata = verify_loaded_image(root, kind, image, expected_key)
        if repository_digest not in image_repo_digests(image):
            raise RuntimeError(f"Pulled {kind} image does not expose its expected digest")
        source = "immutable-registry"
    else:
        archive = (manifest_path.parent / archive_relative).resolve()
        try:
            archive.relative_to(manifest_path.parent.resolve())
        except ValueError as exc:
            raise RuntimeError(f"Prepared {kind} archive escapes its artifact directory") from exc
        expected_archive_sha = entry.get("archive_sha256", "")
        if not archive.is_file() or not re.fullmatch(
            r"[0-9a-f]{64}", expected_archive_sha
        ):
            raise RuntimeError(f"Prepared {kind} archive is missing or unchecksummed")
        expected_size = entry.get("archive_size")
        if expected_size is not None and (
            not isinstance(expected_size, int)
            or expected_size <= 0
            or archive.stat().st_size != expected_size
        ):
            raise RuntimeError(f"Prepared {kind} archive size mismatch")
        if sha256_file(archive) != expected_archive_sha:
            raise RuntimeError(f"Prepared {kind} archive checksum mismatch")
        image = entry.get("image_ref", "")
        if image != IMAGES[kind][1]:
            raise RuntimeError(f"Prepared {kind} archive has a nonstandard image reference")
        docker("load", "--input", str(archive))
        metadata = verify_loaded_image(root, kind, image, expected_key)
        source = "verified-archive"
    local = IMAGES[kind][1]
    if image != local:
        docker("tag", image, local)
    return {
        "kind": kind,
        "reused": True,
        "runtime_key": expected_key,
        "repository_digest": repository_digest or "",
        "local_tag": local,
        "source": source,
        **metadata,
    }


def restore(root: Path, kind: str, registry: str) -> dict:
    repository, local = IMAGES[kind]
    remote = f"{registry.rstrip('/')}/{repository}:dev"
    expected = runtime_key(root, kind)
    pulled = docker("pull", remote, check=False)
    if pulled.returncode:
        return {"kind": kind, "reused": False, "reason": "published image unavailable"}
    actual = image_label(remote, LABEL)
    if actual != expected:
        return {
            "kind": kind,
            "reused": False,
            "reason": "runtime compatibility key mismatch",
            "expected_key": expected,
            "published_key": actual,
        }
    metadata = {}
    if kind == "schema":
        metadata = schema_metadata(remote)
        try:
            validate_schema_metadata(metadata)
        except RuntimeError as exc:
            return {"kind": kind, "reused": False, "reason": str(exc)}
    docker("tag", remote, local)
    repo_digests = image_repo_digests(remote)
    immutable = next((item for item in repo_digests if "@sha256:" in item), "")
    if not immutable:
        raise RuntimeError(f"Published {kind} image lacks an immutable repository digest")
    return {
        "kind": kind,
        "reused": True,
        "runtime_key": expected,
        "repository_digest": immutable,
        "local_tag": local,
        "source": "mutable-discovery-pointer",
        **metadata,
    }


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text())
    if isinstance(data.get("runtime_images"), dict):
        data = data["runtime_images"]
    if data.get("format_version") != MANIFEST_FORMAT_VERSION:
        raise RuntimeError("Prepared runtime manifest has an unsupported format")
    if not isinstance(data.get("images"), list):
        raise RuntimeError("Prepared runtime manifest lacks its image list")
    return data


def write_outputs(results: list[dict]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a") as handle:
            for result in results:
                handle.write(f"{result['kind']}={'true' if result['reused'] else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    key = sub.add_parser("key")
    key.add_argument("--kind", choices=sorted(RUNTIME_INPUTS), required=True)
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("--registry", default="ghcr.io/glowingkitty")
    restore_parser.add_argument("--include-upload", action="store_true")
    restore_parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    root = Path(
        os.environ.get(
            "OPENMATES_CI_SOURCE_ROOT", Path(__file__).resolve().parent.parent
        )
    ).resolve()
    if args.command == "key":
        print(runtime_key(root, args.kind))
        return 0
    kinds = ["api", "cms", "setup", "schema"] + (["upload"] if args.include_upload else [])
    if args.manifest:
        manifest_path = args.manifest.resolve()
        manifest = load_manifest(manifest_path)
        entries = {entry.get("kind"): entry for entry in manifest["images"]}
        if len(entries) != len(manifest["images"]):
            raise RuntimeError("Prepared runtime manifest contains duplicate image kinds")
        missing = [kind for kind in kinds if kind not in entries]
        if missing:
            raise RuntimeError(
                "Prepared runtime manifest is incomplete: " + ", ".join(missing)
            )
        results = [
            restore_manifest_entry(root, entries[kind], manifest_path) for kind in kinds
        ]
    else:
        results = [restore(root, kind, args.registry) for kind in kinds]
    write_outputs(results)
    evidence = root / "test-results/ci-runtime-images.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps({"format_version": MANIFEST_FORMAT_VERSION, "images": results}, indent=2)
    )
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
