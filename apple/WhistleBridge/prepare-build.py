#!/usr/bin/env python3
"""Prepare pinned, verified bundle/link inputs before Xcode graph validation.

The app never runs this helper or downloads speech assets. Normal preparation is
offline; --fetch explicitly reconstructs an absent build cache from official pins.
Cache and package products must stay inside this repository's .runtime directory.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PLATFORMS = ("iphoneos", "iphonesimulator", "watchos")
spec = importlib.util.spec_from_file_location("whistle_prepare", HERE / "prepare.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def scoped_path(path: Path, *, label: str) -> Path:
    """Reject symlinks before resolution can erase their provenance."""
    if ".." in path.parts:
        raise ValueError(f"unsafe_{label}_path")
    absolute = Path(os.path.abspath(path))
    runtime = REPO.resolve() / ".runtime"
    if absolute == runtime or not absolute.is_relative_to(runtime):
        raise ValueError(f"{label}_outside_repo_runtime")
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise ValueError(f"symlink_{label}_path")
        if candidate == runtime.parent:
            break
    return absolute


def package_plan(lock: dict, platform: str) -> list[dict]:
    """Canonical destination identity for the current prepare.py receipt schema."""
    folder = module.SUPPORTED[platform]
    records = []
    for entry in lock["files"]:
        if entry["repository"] == "Cactus-Compute/whistle":
            relative = "bundle/Whistle/" + ("MODEL-LICENSE.txt" if entry["path"] == "LICENSE" else entry["path"])
        elif entry["path"] == "LICENSE":
            relative = "bundle/Whistle/RUNTIME-LICENSE.txt"
        elif entry["path"] in (folder + "/libneedle.a", "ios-arm64/needle.h"):
            relative = "link/" + Path(entry["path"]).name
        else:
            continue
        records.append({"path": relative, "sizeBytes": entry["sizeBytes"], "sha256": entry["sha256"]})
    if len({entry["path"] for entry in records}) != len(records):
        raise ValueError("duplicate_package_destination")
    return records


def expected_receipt(lock: dict, platform: str) -> dict:
    records = package_plan(lock, platform)
    folder = module.SUPPORTED[platform]
    return {
        "schemaVersion": 1, "platform": platform, "runtimeFolder": folder,
        "minimumOS": lock["runtime"]["platforms"][folder]["minimumOS"],
        "modelBytes": lock["model"]["sizeBytes"],
        "bundleBytes": sum(entry["sizeBytes"] for entry in records if entry["path"].startswith("bundle/")),
        "documentsBytes": 0, "containsNeedleLLMWeights": False,
        "nativeActivationAllowed": True, "modelResidency": "process_lifetime",
        "reclaimsModelOnSessionEnd": False, "runtimeScratchErasureVerified": False,
        "files": records,
    }


def verify_package(target: Path, expected: dict) -> dict:
    scoped_path(target, label="package")
    if not target.is_dir():
        raise ValueError("existing_package_not_directory")
    allowed = {entry["path"] for entry in expected["files"]} | {"receipt.json"}
    present = set()
    # Do not follow directory symlinks, including otherwise-in-scope aliases.
    for directory, folders, files in os.walk(target, followlinks=False):
        root = Path(directory)
        for name in folders + files:
            if (root / name).is_symlink():
                raise ValueError("symlink_existing_package")
        present.update((root / name).relative_to(target).as_posix() for name in files)
    if present != allowed:
        raise ValueError("existing_package_file_set_mismatch")
    try:
        receipt = json.loads((target / "receipt.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("existing_package_receipt_invalid") from error
    if json.dumps(receipt, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError("existing_package_receipt_mismatch")
    for entry in expected["files"]:
        module.verify(target / entry["path"], entry)
    return receipt


def verify_cache_paths(cache: Path, lock: dict) -> None:
    # prepare.py verifies bytes and refuses leaf symlinks. Guard all ancestors
    # here as well, before its optional explicit fetch can create directories.
    for entry in lock["files"]:
        path = cache / entry["repository"].split("/")[1] / entry["revision"] / entry["path"]
        scoped_path(path, label="cache_asset")


def prepare_inputs(cache: Path, output: Path, fetch: bool = False) -> dict:
    cache = scoped_path(cache, label="cache")
    output = scoped_path(output, label="output")
    if cache.is_relative_to(output) or output.is_relative_to(cache):
        raise ValueError("overlapping_cache_and_output")
    if cache.exists() and not cache.is_dir():
        raise ValueError("cache_not_directory")
    if output.exists() and not output.is_dir():
        raise ValueError("output_not_directory")
    lock = module.pinned_files()
    verify_cache_paths(cache, lock)
    if fetch:
        # Explicit preparation can rebuild the source cache even when existing
        # products are already valid. Normal release invocation never enters it.
        for entry in lock["files"]:
            module.obtain(cache, entry, fetch=True)
    receipts = {}
    for platform in PLATFORMS:
        target = output / platform
        expected = expected_receipt(lock, platform)
        if target.exists() or target.is_symlink():
            receipts[platform] = verify_package(target, expected)
            continue
        output.mkdir(parents=True, exist_ok=True)
        # Only this invocation's fresh staging directory is cleaned. Never
        # replace, repair or delete existing package products or cached assets.
        with tempfile.TemporaryDirectory(prefix="prepare-", dir=output) as temporary:
            staging = Path(temporary) / "package"
            module.prepare(cache, staging, platform, fetch=fetch)
            verify_package(staging, expected)
            staging.rename(target)
        receipts[platform] = expected
    return receipts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=REPO / ".runtime/whistle-assets")
    parser.add_argument("--output", type=Path, default=REPO / ".runtime/whistle-inputs")
    parser.add_argument("--fetch", action="store_true", help="Explicit preparation-only download of immutable official pins.")
    args = parser.parse_args(argv)
    try:
        receipts = prepare_inputs(args.cache, args.output, args.fetch)
    except (OSError, ValueError) as error:
        # Pin/path error codes contain no credentials or asset content. Full
        # tracebacks with arbitrary filesystem state are unnecessary here.
        code = str(error) if isinstance(error, ValueError) else f"filesystem_error:{error.errno}"
        parser.exit(2, f"whistle_preparation_failed={code}\n")
    print(json.dumps({"platforms": list(receipts), "modelBytes": receipts["iphoneos"]["modelBytes"],
                      "verified": True, "offline": not args.fetch, "receipts": receipts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
