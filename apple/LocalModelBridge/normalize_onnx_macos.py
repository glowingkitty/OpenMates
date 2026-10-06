#!/usr/bin/env python3
"""Isolate ORT's private static dependencies in the processed macOS framework.

Run after ProcessXCFramework and before linking/embedding. Only Xcode's copy in
BUILT_PRODUCTS_DIR is replaced; SwiftPM's source artifact is never modified.
Original inputs and commands remain in DERIVED_FILE_DIR for provenance/recovery.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

EXPORTS = frozenset({"_OrtGetApiBase", "_OrtSessionOptionsAppendExecutionProvider_CPU",
                     "_OrtSessionOptionsAppendExecutionProvider_CoreML"})
ARCHES = frozenset({"arm64", "x86_64"})
INSTALL_NAME = "@rpath/onnxruntime.framework/Versions/A/onnxruntime"
REPO_ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"ONNX packaging command failed: {command[0]}\n{result.stderr[-4000:]}")
    return result.stdout


def scoped_paths(environment: dict[str, str], repo_root: Path = REPO_ROOT) -> tuple[Path, Path]:
    repo_root = repo_root.resolve()
    products = Path(environment["BUILT_PRODUCTS_DIR"]).resolve()
    derived = Path(environment["DERIVED_FILE_DIR"]).resolve()
    for path in (products, derived):
        path.relative_to(repo_root)
        if path == repo_root or "SourcePackages" in path.parts:
            raise ValueError("ONNX packaging requires isolated repository build outputs")
    framework = products / "onnxruntime.framework"
    binary = framework / "Versions/A/onnxruntime"
    # Accept framework's normal Current symlinks, never an artifact/source symlink.
    if binary.resolve() != binary or not binary.is_file():
        raise ValueError("Processed ONNX framework binary is missing or redirects outside its owned output")
    return binary, derived / "onnx-macos-normalization"


def verify_dynamic(binary: Path) -> None:
    if set(run(["xcrun", "lipo", "-archs", str(binary)]).split()) != ARCHES:
        raise ValueError("ONNX runtime must contain arm64 and x86_64")
    for arch in sorted(ARCHES):
        header = run(["xcrun", "otool", "-arch", arch, "-hv", str(binary)])
        if "DYLIB" not in header:
            raise ValueError("ONNX runtime is not a dynamic library")
        names = run(["xcrun", "otool", "-arch", arch, "-D", str(binary)]).splitlines()
        if names[-1].strip() != INSTALL_NAME:
            raise ValueError("ONNX runtime install name does not match framework embedding")
        exported = set(run(["xcrun", "nm", "-arch", arch, "-gjU", str(binary)]).split())
        if exported != EXPORTS:
            raise ValueError("ONNX runtime exposes missing or private dependency symbols")


def normalize(binary: Path, state: Path) -> dict[str, object]:
    state.mkdir(parents=True, exist_ok=True)
    with (state / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt_path = state / "receipt.json"
        initial_sha = sha256(binary)
        normalizer_sha = sha256(Path(__file__))
        if "ar archive" not in run(["file", "-b", str(binary)]):
            verify_dynamic(binary)
            if not receipt_path.is_file():
                raise ValueError("Dynamic ONNX runtime has no normalization provenance")
            receipt = json.loads(receipt_path.read_text())
            if (receipt.get("runtime_sha256") != initial_sha
                    or receipt.get("normalizer_sha256") != normalizer_sha):
                raise ValueError("Dynamic ONNX runtime does not match normalization receipt")
            return receipt
        if set(run(["xcrun", "lipo", "-archs", str(binary)]).split()) != ARCHES:
            raise ValueError("Static ONNX input must contain arm64 and x86_64")
        # Preserve every attempt and the original input. No package/cache deletion.
        attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=state))
        original = attempt / "onnxruntime-original-static.a"
        shutil.copy2(binary, original)
        exports = attempt / "exports.txt"
        exports.write_text("\n".join(sorted(EXPORTS)) + "\n")
        sdk = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).strip()
        commands = []
        slices = []
        for arch in sorted(ARCHES):
            output = attempt / f"onnxruntime-{arch}.dylib"
            command = ["xcrun", "clang", "-target", f"{arch}-apple-macos14.0", "-isysroot", sdk,
                       "-dynamiclib", "-Xlinker", "-force_load", "-Xlinker", str(original),
                       "-Xlinker", "-exported_symbols_list", "-Xlinker", str(exports),
                       "-install_name", INSTALL_NAME, "-compatibility_version", "1.0.0",
                       "-current_version", "1.20.0", "-framework", "Accelerate",
                       "-framework", "CoreML", "-framework", "Foundation",
                       "-framework", "CoreFoundation", "-framework", "Metal", "-lc++",
                       "-o", str(output)]
            commands.append(command)
            run(command)
            slices.append(str(output))
        output = attempt / "onnxruntime-universal.dylib"
        commands.append(["xcrun", "lipo", "-create", *slices, "-output", str(output)])
        run(commands[-1])
        verify_dynamic(output)
        if sha256(binary) != initial_sha or sha256(original) != initial_sha:
            raise ValueError("Processed ONNX input changed during normalization")
        receipt = {"schema": 1, "source_static_sha256": initial_sha,
                   "runtime_sha256": sha256(output), "normalizer_sha256": normalizer_sha,
                   "original": str(original), "processed": str(binary), "commands": commands,
                   "exports": sorted(EXPORTS), "architectures": sorted(ARCHES),
                   "install_name": INSTALL_NAME, "minimum_macos": "14.0"}
        # Replace the owned binary atomically and preserve candidate bytes too.
        replacement = binary.with_name("onnxruntime.normalized")
        shutil.copy2(output, replacement)
        replacement.chmod(0o755)
        os.replace(replacement, binary)
        (attempt / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        temporary = state / "receipt.tmp"
        temporary.write_text(json.dumps(receipt, indent=2) + "\n")
        temporary.replace(receipt_path)
        return receipt


def main() -> None:
    if os.environ.get("PLATFORM_NAME") != "macosx":
        return
    binary, state = scoped_paths(dict(os.environ))
    normalize(binary, state)
    print("ONNX macOS processed framework: universal dynamic runtime, three public exports verified")


if __name__ == "__main__":
    main()
