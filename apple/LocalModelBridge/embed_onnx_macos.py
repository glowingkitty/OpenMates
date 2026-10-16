#!/usr/bin/env python3
"""Embed the processed ORT framework that SwiftPM still describes as static.

Use in the macOS app's postbuild phase. ditto preserves the versioned framework
symlinks; normal Xcode signing signs only the copied framework, never its input.
Unsigned archive builds leave signing to the release helper.
"""
from __future__ import annotations

import os
from pathlib import Path

from normalize_onnx_macos import REPO_ROOT, run, sha256, verify_dynamic


def scoped_paths(environment: dict[str, str], repo_root: Path = REPO_ROOT) -> tuple[Path, Path]:
    root = repo_root.resolve()
    products = Path(environment["BUILT_PRODUCTS_DIR"]).resolve()
    target = Path(environment["TARGET_BUILD_DIR"]).resolve()
    for path in (products, target):
        path.relative_to(root)
        if path == root or "SourcePackages" in path.parts:
            raise ValueError("ONNX embedding requires isolated repository build outputs")
    relative = Path(environment["FRAMEWORKS_FOLDER_PATH"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Framework destination must be inside the target app")
    source = products / "onnxruntime.framework"
    destination = target / relative / "onnxruntime.framework"
    destination.resolve().relative_to(target)
    if "SourcePackages" in destination.resolve().parts:
        raise ValueError("ONNX embedding cannot mutate package artifacts")
    if source.resolve() != source or destination.resolve() != destination or source == destination:
        raise ValueError("ONNX framework source and destination must be distinct owned directories")
    # ditto may merge into an existing framework. Reject redirected descendants
    # before it writes, while retaining ordinary internal framework symlinks.
    for framework in (source, destination):
        if framework.exists():
            for child in framework.rglob("*"):
                if child.is_symlink():
                    child.resolve().relative_to(framework)
    binary = source / "Versions/A/onnxruntime"
    if binary.resolve() != binary or not binary.is_file():
        raise ValueError("Processed ONNX framework binary is missing or redirected")
    return source, destination


def embed(environment: dict[str, str], repo_root: Path = REPO_ROOT) -> dict[str, object] | None:
    if environment.get("PLATFORM_NAME") != "macosx":
        return None
    source, destination = scoped_paths(environment, repo_root)
    binary_relative = Path("Versions/A/onnxruntime")
    original = source / binary_relative
    verify_dynamic(original)
    original_sha = sha256(original)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(["ditto", str(source), str(destination)])
    copied = destination / binary_relative
    if copied.resolve() != copied or sha256(copied) != original_sha:
        raise ValueError("Embedded ONNX framework binary does not match its verified input")
    verify_dynamic(copied)
    signed = environment.get("CODE_SIGNING_ALLOWED") == "YES"
    if signed:
        identity = environment.get("EXPANDED_CODE_SIGN_IDENTITY", "").strip() or "-"
        run(["codesign", "--force", "--sign", identity, "--timestamp=none", str(destination)])
        run(["codesign", "--verify", "--strict", str(destination)])
        # codesign can change LC_CODE_SIGNATURE, so verify the runtime contract
        # again rather than expecting the signed file's hash to remain identical.
        verify_dynamic(copied)
    if sha256(original) != original_sha:
        raise ValueError("ONNX source framework changed while embedding")
    return {"source_binary_sha256": original_sha, "embedded_binary_sha256": sha256(copied),
            "signed": signed}


if __name__ == "__main__":
    result = embed(dict(os.environ))
    if result:
        print(f"ONNX macOS framework embedded and verified; signed={result['signed']}")
