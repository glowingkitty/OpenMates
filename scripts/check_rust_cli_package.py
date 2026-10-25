#!/usr/bin/env python3
"""Inspect real Cargo package lists and portable inputs, without building/publishing.

This is a source/package-input guard, not a registry or installation proof.
The SDK registry dependency remains unverified while publication is disabled.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

from sync_rust_cli_assets import CRATE, ROOT, synchronize

SDK = Path("packages/openmates-rust")
INCLUDE = re.compile(r'include_(?:str|bytes)!\(\s*"([^"\\]+)"\s*\)')
INCLUDE_START = re.compile(r"include_(?:str|bytes)!\s*\(")


def audit_catalog_sources(root: Path = ROOT) -> None:
    catalog = json.loads((root / "config/cli-command-catalog.json").read_text())
    for entry in catalog["source_snapshots"]:
        source = (root / entry["path"]).resolve()
        if not source.is_relative_to(root.resolve()) or not source.is_file():
            raise ValueError("Invalid catalog source: " + entry["path"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Review CLI catalog after changing " + entry["path"])


def validate_metadata(cli: dict, sdk: dict) -> None:
    for manifest in (cli, sdk):
        package = manifest["package"]
        if package.get("publish") is not False:
            raise ValueError("Publication remains disabled during migration")
        if not package.get("include") or not package.get("rust-version"):
            raise ValueError("Explicit package inputs and tested Rust version required")
    if (
        cli["package"]["license"] != "AGPL-3.0-only"
        or sdk["package"]["license"] != "MIT"
    ):
        raise ValueError("Preserve native AGPL and separate SDK MIT licensing")
    bins = cli.get("bin", [])
    if (
        cli["package"].get("autobins") is not False
        or len(bins) != 1
        or bins[0] != {"name": "openmates", "path": "src/main.rs"}
    ):
        raise ValueError("Only the application may be an installable binary")
    dependency = cli["dependencies"]["openmates-sdk"]
    if (
        dependency.get("version") != "=" + sdk["package"]["version"]
        or dependency.get("path") != "../../../packages/openmates-rust"
    ):
        raise ValueError("Exact SDK version and development path must agree")


def validate_inputs(crate: Path, names: set[str]) -> None:
    for required in ("Cargo.toml", "Cargo.lock", "LICENSE", "NOTICE", "README.md"):
        if required not in names:
            raise ValueError("Missing package input: " + required)
    if any(
        name.startswith(("scripts/", "target/", "node_modules/"))
        or name.endswith((".py", ".mjs", ".node", ".so"))
        for name in names
    ):
        raise ValueError("Package contains build/proof tools or native artifacts")
    for name in names:
        path = (crate / name).resolve()
        if not path.is_relative_to(crate.resolve()):
            raise ValueError("Package input escapes crate: " + name)
        if not name.endswith(".rs"):
            continue
        source = path.read_text()
        matches = list(INCLUDE.finditer(source))
        if len(matches) != len(INCLUDE_START.findall(source)):
            raise ValueError("Review nonliteral compile-time input: " + name)
        for match in matches:
            target = (path.parent / match[1]).resolve()
            if (
                not target.is_relative_to(crate.resolve())
                or str(target.relative_to(crate.resolve())) not in names
                or not target.is_file()
            ):
                raise ValueError(f"Unpackaged compile-time input: {name}: {match[1]}")


def check(root: Path = ROOT) -> dict:
    synchronize(root, check=True)
    audit_catalog_sources(root)
    cli = tomllib.loads((root / CRATE / "Cargo.toml").read_text())
    sdk = tomllib.loads((root / SDK / "Cargo.toml").read_text())
    validate_metadata(cli, sdk)
    metadata = subprocess.run(
        [
            "cargo",
            "metadata",
            "--manifest-path",
            str(root / CRATE / "Cargo.toml"),
            "--no-deps",
            "--format-version",
            "1",
            "--locked",
            "--offline",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    application = next(
        package
        for package in json.loads(metadata.stdout)["packages"]
        if package["name"] == cli["package"]["name"]
    )
    binaries = sorted(
        target["name"] for target in application["targets"] if "bin" in target["kind"]
    )
    if binaries != ["openmates"]:
        raise ValueError("Cargo discovered unexpected installable binaries")
    packages = {}
    for relative in (SDK, CRATE):
        crate = root / relative
        result = subprocess.run(
            [
                "cargo",
                "package",
                "--manifest-path",
                str(crate / "Cargo.toml"),
                "--list",
                "--locked",
                "--offline",
                "--allow-dirty",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        names = set(result.stdout.splitlines())
        validate_inputs(crate, names)
        packages[str(relative)] = sorted(names)
    return {
        "status": "source-package-inputs-checked",
        "packages": packages,
        "installableBins": binaries,
        "registryDependency": "unverified: SDK publication remains disabled and parity-gated",
        "installationTested": False,
        "limits": "Cargo package --list only; no archive verification, registry resolution, compilation, installation or runtime test is claimed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = check()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"] + "; SDK registry/install proof remains blocked")


if __name__ == "__main__":
    main()
