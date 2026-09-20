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
import subprocess


LABEL = "org.openmates.ci.runtime-key"
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
        "scripts/ci_schema_image.Dockerfile",
        "backend/core/directus/Dockerfile",
        "backend/core/directus/extensions/**/*",
        "backend/core/directus/schemas/**/*",
        "backend/core/directus/setup/**/*",
    ),
    "upload": (
        "backend/upload/Dockerfile",
        "backend/upload/requirements.txt",
    ),
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
        paths.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def runtime_key(root: Path, kind: str) -> str:
    if kind not in RUNTIME_INPUTS:
        raise ValueError(f"Unknown runtime image kind: {kind}")
    digest = hashlib.sha256()
    paths = input_paths(root, kind)
    if not paths:
        raise RuntimeError(f"Runtime image {kind} has no declared inputs")
    for path in paths:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], text=True, capture_output=True, check=check, timeout=300
    )


def restore(root: Path, kind: str, registry: str) -> dict:
    repository, local = IMAGES[kind]
    remote = f"{registry.rstrip('/')}/{repository}:dev"
    expected = runtime_key(root, kind)
    pulled = docker("pull", remote, check=False)
    if pulled.returncode:
        return {"kind": kind, "reused": False, "reason": "published image unavailable"}
    actual = docker(
        "image",
        "inspect",
        remote,
        "--format",
        f"{{{{ index .Config.Labels \"{LABEL}\" }}}}",
    ).stdout.strip()
    if actual != expected:
        return {
            "kind": kind,
            "reused": False,
            "reason": "runtime compatibility key mismatch",
            "expected_key": expected,
            "published_key": actual,
        }
    docker("tag", remote, local)
    repo_digests = json.loads(
        docker("image", "inspect", remote, "--format", "{{json .RepoDigests}}").stdout
    )
    immutable = next((item for item in repo_digests if "@sha256:" in item), "")
    if not immutable:
        raise RuntimeError(f"Published {kind} image lacks an immutable repository digest")
    return {
        "kind": kind,
        "reused": True,
        "runtime_key": expected,
        "repository_digest": immutable,
        "local_tag": local,
    }


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
    results = [restore(root, kind, args.registry) for kind in kinds]
    write_outputs(results)
    evidence = root / "test-results/ci-runtime-images.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"images": results}, indent=2))
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
