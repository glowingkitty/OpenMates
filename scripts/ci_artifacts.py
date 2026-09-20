#!/usr/bin/env python3
"""Prepare and restore immutable build artifacts for isolated GitHub CI.

The coordinator owns scheduling and gives every consumer an exact producer run.
This module only owns artifact identity, deterministic packaging, integrity
checks, and explicit cold-fallback receipts. It never searches for a "latest"
artifact and never shares mutable runtime state between jobs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any, Mapping


FORMAT_VERSION = 1
BUNDLE_FORMAT = "openmates-ci-preparation-v1"
PRODUCER_CONTRACT = "exact-source-web-cli-runtime-images-v1"
MANIFEST_NAME = "manifest.json"
RECEIPT_NAME = "ci-artifacts.json"
DEFAULT_MAX_IMAGE_BYTES = 4 * 1024**3
DEFAULT_MAX_TOTAL_IMAGE_BYTES = 8 * 1024**3
DEFAULT_MAX_BUNDLE_BYTES = 9 * 1024**3
SCHEMA_BUNDLE_LABEL = "org.openmates.ci.schema-bundle-format"
SCHEMA_RESTORE_LABEL = "org.openmates.ci.schema-restore-semantics"

DEFAULT_BUILD_ENVIRONMENT = {
    "OPENMATES_CI_PRECOMPRESS": "0",
    "VITE_API_URL": "http://localhost:8000",
    "VITE_ENV": "self_hosted",
    "VITE_UPLOAD_URL": "http://localhost:5173",
}
DEFAULT_TOOLCHAIN = {"node": "24.x", "pnpm": "10.23.0"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def declared_build_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if environment is None else environment
    return {
        name: str(source.get(name, default))
        for name, default in DEFAULT_BUILD_ENVIRONMENT.items()
    }


def preparation_key(
    source: str,
    *,
    include_cli: bool = True,
    include_upload: bool = False,
    build_environment: Mapping[str, str] | None = None,
    toolchain: Mapping[str, str] | None = None,
) -> str:
    """Return a pure same-candidate preparation identity.

    The exact source commit is the complete build input in the conservative
    first rollout. No coordinator working-tree files are read here because the
    candidate can live in a different checkout or be reconstructed remotely.
    """

    if len(source) != 40 or any(character not in "0123456789abcdef" for character in source):
        raise ValueError("Preparation source must be a full lowercase commit SHA")
    payload = {
        "format_version": FORMAT_VERSION,
        "bundle_format": BUNDLE_FORMAT,
        "producer_contract": PRODUCER_CONTRACT,
        "source_commit": source,
        "capabilities": {
            "cli": bool(include_cli),
            "upload_runtime": bool(include_upload),
            "web": True,
        },
        "build_environment": dict(
            sorted((build_environment or DEFAULT_BUILD_ENVIRONMENT).items())
        ),
        "toolchain": dict(sorted((toolchain or DEFAULT_TOOLCHAIN).items())),
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _archive_directory(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_dir():
        raise RuntimeError(f"Prepared output is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                root_info = tarfile.TarInfo(source.name)
                root_info.type = tarfile.DIRTYPE
                root_info.mode = 0o755
                root_info.mtime = 0
                archive.addfile(root_info)
                for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
                    relative = PurePosixPath(source.name) / path.relative_to(source).as_posix()
                    info = tarfile.TarInfo(relative.as_posix())
                    info.mtime = 0
                    if path.is_symlink():
                        raise RuntimeError(f"Prepared outputs may not contain symlinks: {path}")
                    if path.is_dir():
                        info.type = tarfile.DIRTYPE
                        info.mode = 0o755
                        archive.addfile(info)
                    elif path.is_file():
                        info.size = path.stat().st_size
                        info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
                    else:
                        raise RuntimeError(f"Unsupported prepared output type: {path}")
    return {
        "path": destination.name,
        "sha256": sha256_file(destination),
        "size": destination.stat().st_size,
    }


def _load_runtime_receipt(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"format_version": 2, "images": []}
    value = json.loads(path.read_text())
    if (
        not isinstance(value, dict)
        or value.get("format_version") != 2
        or not isinstance(value.get("images"), list)
    ):
        raise RuntimeError("Runtime image receipt is malformed")
    return value


def create_bundle(
    root: Path,
    output_dir: Path,
    source: str,
    *,
    candidate_tree: str,
    harness_commit: str,
    include_cli: bool,
    include_upload: bool,
    runtime_receipt: Path | None = None,
    build_environment: Mapping[str, str] | None = None,
    toolchain: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    environment = declared_build_environment(build_environment)
    selected_toolchain = dict(toolchain or DEFAULT_TOOLCHAIN)
    key = preparation_key(
        source,
        include_cli=include_cli,
        include_upload=include_upload,
        build_environment=environment,
        toolchain=selected_toolchain,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "web": {
            **_archive_directory(
                root / "frontend/apps/web_app/build", output_dir / "web.tar.gz"
            ),
            "destination": "frontend/apps/web_app/build",
        },
        "translations": {
            **_archive_directory(
                root / "frontend/packages/ui/src/i18n/locales",
                output_dir / "translations.tar.gz",
            ),
            "destination": "frontend/packages/ui/src/i18n/locales",
        },
    }
    if include_cli:
        artifacts["cli"] = {
            **_archive_directory(
                root / "frontend/packages/openmates-cli/dist",
                output_dir / "cli.tar.gz",
            ),
            "destination": "frontend/packages/openmates-cli/dist",
        }
    runtime_images = _load_runtime_receipt(runtime_receipt)
    bundle_bytes = sum(
        path.stat().st_size for path in output_dir.rglob("*") if path.is_file()
    )
    if bundle_bytes > DEFAULT_MAX_BUNDLE_BYTES:
        raise RuntimeError("Preparation bundle exceeds the private artifact size limit")
    manifest = {
        "format_version": FORMAT_VERSION,
        "bundle_format": BUNDLE_FORMAT,
        "producer_contract": PRODUCER_CONTRACT,
        "preparation_key": key,
        "source_commit": source,
        "candidate_tree": candidate_tree,
        "harness_commit": harness_commit,
        "capabilities": {
            "cli": include_cli,
            "upload_runtime": include_upload,
            "web": True,
        },
        "build_environment": environment,
        "toolchain": selected_toolchain,
        "artifacts": artifacts,
        "runtime_images": runtime_images,
    }
    temporary = output_dir / f".{MANIFEST_NAME}.tmp"
    temporary.write_bytes(canonical_json(manifest) + b"\n")
    temporary.replace(output_dir / MANIFEST_NAME)
    return manifest


def _write_outputs(values: Mapping[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with Path(path).open("a") as handle:
        for name, value in values.items():
            handle.write(f"{name}={value}\n")


def _write_receipt(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    path = root / "test-results" / RECEIPT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    _write_outputs(
        {
            "prepared": "true" if receipt.get("reused") else "false",
            "web": "true" if receipt.get("reused") else "false",
            "cli": "true"
            if receipt.get("reused") and receipt.get("capabilities", {}).get("cli")
            else "false",
            "manifest": str(receipt.get("manifest_path", "")),
            "fallback_reason": str(receipt.get("reason", "")),
        }
    )
    return receipt


def write_producer_results(
    root: Path, manifest: Mapping[str, Any], manifest_path: Path
) -> None:
    results = root / "test-results"
    results.mkdir(parents=True, exist_ok=True)
    receipt = {
        "format_version": FORMAT_VERSION,
        "reused": False,
        "produced": True,
        "source_commit": manifest["source_commit"],
        "candidate_tree": manifest["candidate_tree"],
        "preparation_key": manifest["preparation_key"],
        "manifest_path": str(manifest_path.resolve()),
        "capabilities": manifest["capabilities"],
        "cold_fallback": False,
    }
    (results / RECEIPT_NAME).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    report = {
        "success": True,
        "source_commit": manifest["source_commit"],
        "harness_commit": manifest["harness_commit"],
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "runtime_profile": "prepare",
        "proof_profile": "",
        "results": [
            {
                "suite": "preparation",
                "exit_code": 0,
                "preparation_key": manifest["preparation_key"],
                "capabilities": manifest["capabilities"],
            }
        ],
    }
    (results / "ci-results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )


def record_runtime_fallback(root: Path, reason: str) -> dict[str, Any]:
    path = root / "test-results" / RECEIPT_NAME
    if not path.is_file():
        raise RuntimeError("Cannot record runtime fallback without artifact receipt")
    receipt = json.loads(path.read_text())
    receipt.update(
        runtime_reused=False,
        runtime_cold_fallback=True,
        runtime_fallback_reason=reason,
    )
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def _fallback(
    root: Path,
    source: str,
    expected_key: str,
    reason: str,
    *,
    manifest_key: str = "",
) -> dict[str, Any]:
    return _write_receipt(
        root,
        {
            "format_version": FORMAT_VERSION,
            "reused": False,
            "source_commit": source,
            "expected_preparation_key": expected_key,
            "manifest_preparation_key": manifest_key,
            "cold_fallback": True,
            "reason": reason,
        },
    )


def _validated_members(archive_path: Path, expected_root: str) -> list[tarfile.TarInfo]:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
    if not members:
        raise RuntimeError("artifact_archive_empty")
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != expected_root
            or not (member.isdir() or member.isfile())
        ):
            raise RuntimeError("artifact_archive_unsafe")
    return members


def _bundle_path(input_dir: Path, relative: object) -> Path:
    value = PurePosixPath(str(relative or ""))
    if not value.parts or value.is_absolute() or ".." in value.parts:
        raise RuntimeError("artifact_path_unsafe")
    resolved = input_dir.joinpath(*value.parts).resolve()
    if not resolved.is_relative_to(input_dir.resolve()):
        raise RuntimeError("artifact_path_unsafe")
    return resolved


def _extract_archive(archive_path: Path, destination: Path, expected_root: str) -> None:
    destination_parent = destination.parent.resolve()
    if destination.is_symlink() or not destination.resolve().is_relative_to(destination_parent):
        raise RuntimeError("artifact_destination_unsafe")
    destination_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination_parent))
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                target = temporary.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(0o755)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise RuntimeError("artifact_archive_unreadable")
                    with target.open("wb") as handle:
                        shutil.copyfileobj(extracted, handle)
                    target.chmod(member.mode & 0o777)
        restored = temporary / expected_root
        if destination.exists():
            shutil.rmtree(destination)
        restored.replace(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def restore_bundle(
    root: Path,
    input_dir: Path,
    source: str,
    *,
    candidate_tree: str,
    include_cli: bool,
    include_upload: bool,
    expected_key: str = "",
    harness_commit: str = "",
    build_environment: Mapping[str, str] | None = None,
    toolchain: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    environment = declared_build_environment(build_environment)
    selected_toolchain = dict(toolchain or DEFAULT_TOOLCHAIN)
    calculated_key = preparation_key(
        source,
        include_cli=include_cli,
        include_upload=include_upload,
        build_environment=environment,
        toolchain=selected_toolchain,
    )
    if expected_key and expected_key != calculated_key:
        return _fallback(root, source, calculated_key, "requested_key_mismatch")
    manifest_path = input_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return _fallback(root, source, calculated_key, "artifact_missing")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return _fallback(root, source, calculated_key, "manifest_unreadable")
    manifest_key = str(manifest.get("preparation_key", ""))
    expected_harness = harness_commit or os.environ.get("CI_HARNESS_COMMIT", "")
    checks = {
        "manifest_format_mismatch": manifest.get("format_version") != FORMAT_VERSION
        or manifest.get("bundle_format") != BUNDLE_FORMAT,
        "producer_contract_mismatch": manifest.get("producer_contract")
        != PRODUCER_CONTRACT,
        "source_mismatch": manifest.get("source_commit") != source,
        "candidate_tree_mismatch": bool(candidate_tree)
        and manifest.get("candidate_tree") != candidate_tree,
        "harness_commit_mismatch": bool(expected_harness)
        and manifest.get("harness_commit") != expected_harness,
        "preparation_key_mismatch": manifest_key != calculated_key,
        "build_environment_mismatch": manifest.get("build_environment") != environment,
        "toolchain_mismatch": manifest.get("toolchain") != selected_toolchain,
        "cli_capability_missing": include_cli
        and not manifest.get("capabilities", {}).get("cli"),
        "upload_capability_missing": include_upload
        and not manifest.get("capabilities", {}).get("upload_runtime"),
    }
    reason = next((name for name, failed in checks.items() if failed), "")
    if reason:
        return _fallback(
            root, source, calculated_key, reason, manifest_key=manifest_key
        )
    required = ["web", "translations"] + (["cli"] if include_cli else [])
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return _fallback(root, source, calculated_key, "artifact_manifest_malformed")
    validated: list[tuple[Path, Path, str]] = []
    try:
        for name in required:
            item = artifacts.get(name)
            if not isinstance(item, dict):
                raise RuntimeError(f"{name}_artifact_missing")
            archive_path = _bundle_path(input_dir, item.get("path"))
            if not archive_path.is_file():
                raise RuntimeError(f"{name}_artifact_missing")
            if archive_path.stat().st_size != item.get("size"):
                raise RuntimeError(f"{name}_artifact_size_mismatch")
            if sha256_file(archive_path) != item.get("sha256"):
                raise RuntimeError(f"{name}_artifact_digest_mismatch")
            destination = (root / str(item.get("destination", ""))).resolve()
            if not destination.is_relative_to(root.resolve()):
                raise RuntimeError("artifact_destination_unsafe")
            expected_root = destination.name
            _validated_members(archive_path, expected_root)
            validated.append((archive_path, destination, expected_root))
        runtime_images = manifest.get("runtime_images", {})
        for image in runtime_images.get("images", []) if isinstance(runtime_images, dict) else []:
            archive_name = image.get("archive_path")
            if not archive_name:
                continue
            archive_path = _bundle_path(input_dir, archive_name)
            if (
                not archive_path.is_file()
                or archive_path.stat().st_size != image.get("archive_size")
                or sha256_file(archive_path) != image.get("archive_sha256")
            ):
                raise RuntimeError(f"{image.get('kind', 'runtime')}_image_archive_mismatch")
    except (OSError, tarfile.TarError, RuntimeError) as exc:
        return _fallback(root, source, calculated_key, str(exc), manifest_key=manifest_key)
    for archive_path, destination, expected_root in validated:
        _extract_archive(archive_path, destination, expected_root)
    return _write_receipt(
        root,
        {
            "format_version": FORMAT_VERSION,
            "reused": True,
            "source_commit": source,
            "candidate_tree": candidate_tree,
            "preparation_key": calculated_key,
            "manifest_path": str(manifest_path.resolve()),
            "capabilities": manifest["capabilities"],
            "cold_fallback": False,
            "artifacts": required,
        },
    )


def _docker_inspect(image_ref: str) -> dict[str, Any]:
    output = subprocess.check_output(
        ["docker", "image", "inspect", image_ref], text=True, timeout=120
    )
    values = json.loads(output)
    if len(values) != 1:
        raise RuntimeError(f"Expected one local image for {image_ref}")
    return values[0]


def export_runtime_images(
    root: Path,
    receipt_path: Path,
    output_dir: Path,
    *,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_IMAGE_BYTES,
) -> dict[str, Any]:
    try:
        from scripts import ci_runtime_images as runtime
    except ModuleNotFoundError:
        import ci_runtime_images as runtime  # type: ignore

    receipt = _load_runtime_receipt(receipt_path)
    kinds = [str(item.get("kind", "")) for item in receipt["images"]]
    if len(kinds) != len(set(kinds)) or not {"api", "cms", "setup", "schema"}.issubset(kinds):
        raise RuntimeError("Runtime image receipt is incomplete or contains duplicates")
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    exported: list[dict[str, Any]] = []
    for original in receipt["images"]:
        entry = dict(original)
        kind = str(entry.get("kind", ""))
        if kind not in runtime.IMAGES:
            raise RuntimeError(f"Unknown runtime image kind in receipt: {kind}")
        expected_key = runtime.runtime_key(root, kind)
        if entry.get("reused"):
            if entry.get("runtime_key") != expected_key or not entry.get(
                "repository_digest"
            ):
                raise RuntimeError(f"Warm {kind} image receipt is incomplete")
            if not re.fullmatch(
                r"[^\s@]+@sha256:[0-9a-f]{64}", str(entry["repository_digest"])
            ):
                raise RuntimeError(f"Warm {kind} image digest is not immutable")
            if kind == "schema" and (
                not entry.get("bundle_format") or not entry.get("restore_semantics")
            ):
                raise RuntimeError("Warm schema image lacks restore contract metadata")
            exported.append(entry)
            continue
        local_tag = runtime.IMAGES[kind][1]
        inspection = _docker_inspect(local_tag)
        labels = inspection.get("Config", {}).get("Labels") or {}
        if labels.get(runtime.LABEL) != expected_key:
            raise RuntimeError(f"Cold {kind} image has the wrong compatibility label")
        estimated = int(inspection.get("Size") or 0)
        if estimated > max_image_bytes:
            raise RuntimeError(f"Cold {kind} image exceeds the per-image size limit")
        free = shutil.disk_usage(images_dir).free
        if free < estimated + 1024**3:
            raise RuntimeError(f"Insufficient disk space to export cold {kind} image")
        destination = images_dir / f"{kind}.tar"
        temporary = images_dir / f".{kind}.tar.tmp"
        subprocess.run(
            ["docker", "save", "--output", str(temporary), local_tag],
            check=True,
            timeout=900,
        )
        size = temporary.stat().st_size
        if size > max_image_bytes or total + size > max_total_bytes:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("Cold runtime image archives exceed the preparation limit")
        temporary.replace(destination)
        total += size
        entry = {
            "kind": kind,
            "reused": False,
            "runtime_key": expected_key,
            "archive_path": destination.relative_to(output_dir).as_posix(),
            "archive_sha256": sha256_file(destination),
            "archive_size": size,
            "image_ref": local_tag,
        }
        if kind == "schema":
            entry.update(
                bundle_format=labels.get(SCHEMA_BUNDLE_LABEL, ""),
                restore_semantics=labels.get(SCHEMA_RESTORE_LABEL, ""),
            )
            if not entry["bundle_format"] or not entry["restore_semantics"]:
                raise RuntimeError("Cold schema image lacks restore contract labels")
        exported.append(entry)
    updated = {**receipt, "format_version": 2, "images": exported}
    receipt_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n")
    return updated


def boolean(value: str) -> bool:
    lowered = value.lower()
    if lowered not in {"true", "false"}:
        raise argparse.ArgumentTypeError("Expected true or false")
    return lowered == "true"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("OPENMATES_CI_SOURCE_ROOT", Path(__file__).parent.parent)),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    key_parser = sub.add_parser("key")
    key_parser.add_argument("--source", required=True)
    key_parser.add_argument("--include-cli", type=boolean, default=True)
    key_parser.add_argument("--include-upload", type=boolean, default=False)
    create = sub.add_parser("create")
    create.add_argument("--source", required=True)
    create.add_argument("--candidate-tree", required=True)
    create.add_argument("--harness-commit", required=True)
    create.add_argument("--include-cli", type=boolean, required=True)
    create.add_argument("--include-upload", type=boolean, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    create.add_argument("--runtime-receipt", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("--source", required=True)
    restore.add_argument("--candidate-tree", default="")
    restore.add_argument("--include-cli", type=boolean, required=True)
    restore.add_argument("--include-upload", type=boolean, required=True)
    restore.add_argument("--expected-key", default="")
    restore.add_argument("--harness-commit", default="")
    restore.add_argument("--input-dir", type=Path, required=True)
    export = sub.add_parser("export-images")
    export.add_argument("--receipt", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--max-image-bytes", type=int, default=DEFAULT_MAX_IMAGE_BYTES)
    export.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_IMAGE_BYTES)
    runtime_fallback = sub.add_parser("runtime-fallback")
    runtime_fallback.add_argument("--reason", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "key":
        print(
            preparation_key(
                args.source,
                include_cli=args.include_cli,
                include_upload=args.include_upload,
            )
        )
    elif args.command == "create":
        manifest = create_bundle(
            root,
            args.output_dir.resolve(),
            args.source,
            candidate_tree=args.candidate_tree,
            harness_commit=args.harness_commit,
            include_cli=args.include_cli,
            include_upload=args.include_upload,
            runtime_receipt=args.runtime_receipt,
        )
        write_producer_results(
            root, manifest, args.output_dir.resolve() / MANIFEST_NAME
        )
        print(manifest["preparation_key"])
    elif args.command == "restore":
        receipt = restore_bundle(
            root,
            args.input_dir.resolve(),
            args.source,
            candidate_tree=args.candidate_tree,
            include_cli=args.include_cli,
            include_upload=args.include_upload,
            expected_key=args.expected_key,
            harness_commit=args.harness_commit,
        )
        print(json.dumps(receipt, sort_keys=True))
    elif args.command == "export-images":
        result = export_runtime_images(
            root,
            args.receipt.resolve(),
            args.output_dir.resolve(),
            max_image_bytes=args.max_image_bytes,
            max_total_bytes=args.max_total_bytes,
        )
        print(json.dumps(result, sort_keys=True))
    else:
        print(json.dumps(record_runtime_fallback(root, args.reason), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
