#!/usr/bin/env python3
"""Build the Rust core artifacts used by the npm and Python SDKs.

Developer/CI tool only; the SDKs never import or invoke it. Both SDKs load the
artifact explicitly and raise a typed error when it is missing; there is no
TypeScript/Python fallback for session operations and no CLI process.

    python3 scripts/build_sdk_native.py --language npm      # -> openmates-cli/native/<os>-<arch>.node
    python3 scripts/build_sdk_native.py --language python   # -> openmates-python/openmates/_native.abi3.so
    python3 scripts/build_sdk_native.py --language wasm     # -> openmates-cli/wasm/openmates_sdk{.js,_bg.wasm}

The wasm build is the portable npm artifact (Node, Deno, Bun, edge, browsers);
it needs the wasm32-unknown-unknown target and wasm-bindgen-cli matching the
locked wasm-bindgen crate version.

The napi and pyo3 builds produce the same cdylib file name, so each build is
copied to its destination immediately after cargo finishes.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CRATE = "openmates-session-bindings"
FEATURES = {"npm": "napi-bindings", "python": "python-bindings", "wasm": "wasm-bindings"}
WASM_OUT = ROOT / "frontend/packages/openmates-cli/wasm"
CDYLIB = {"linux": "lib_native.so", "darwin": "lib_native.dylib", "win32": "_native.dll"}
PYTHON_SUFFIX = {"linux": "_native.abi3.so", "darwin": "_native.abi3.so", "win32": "_native.pyd"}


def host_target() -> tuple[str, str]:
    target_os = {"linux": "linux", "darwin": "darwin", "win32": "win32"}.get(sys.platform)
    architecture = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(
        platform.machine().lower()
    )
    if not target_os or not architecture:
        raise SystemExit("No native SDK build mapping exists for this host.")
    return target_os, architecture


def destination(language: str, target_os: str, architecture: str) -> Path:
    if language == "npm":
        return ROOT / "frontend/packages/openmates-cli/native" / f"{target_os}-{architecture}.node"
    return ROOT / "packages/openmates-python/openmates" / PYTHON_SUFFIX[target_os]


def build_wasm(*, debug: bool, jobs: str | None) -> Path:
    command = ["cargo", "build", "--locked", "-p", CRATE, "--lib", "--no-default-features",
               "--features", FEATURES["wasm"], "--target", "wasm32-unknown-unknown"]
    if not debug:
        command.append("--release")
    if jobs:
        command += ["-j", jobs]
    subprocess.run(command, check=True, cwd=ROOT)
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target"))
    if not target_dir.is_absolute():
        target_dir = ROOT / target_dir
    artifact = target_dir / "wasm32-unknown-unknown" / ("debug" if debug else "release") / "_native.wasm"
    WASM_OUT.mkdir(parents=True, exist_ok=True)
    # `web` glue is portable ESM; the SDK instantiates it with initSync(bytes).
    subprocess.run(["wasm-bindgen", "--target", "web", "--out-dir", str(WASM_OUT),
                    "--out-name", "openmates_sdk", "--no-typescript", str(artifact)], check=True, cwd=ROOT)
    # Unreferenced inline snippets of the core's browser adapters are not shipped.
    shutil.rmtree(WASM_OUT / "snippets", ignore_errors=True)
    output = WASM_OUT / "openmates_sdk_bg.wasm"
    print(f"Built WASM SDK artifact: {output.relative_to(ROOT)}")
    return output


def build(language: str, *, debug: bool, jobs: str | None) -> Path:
    if language == "wasm":
        return build_wasm(debug=debug, jobs=jobs)
    target_os, architecture = host_target()
    command = ["cargo", "build", "--locked", "-p", CRATE, "--no-default-features", "--features", FEATURES[language]]
    if not debug:
        command.append("--release")
    if jobs:
        command += ["-j", jobs]
    subprocess.run(command, check=True, cwd=ROOT)
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target"))
    if not target_dir.is_absolute():
        target_dir = ROOT / target_dir
    artifact = target_dir / ("debug" if debug else "release") / CDYLIB[target_os]
    output = destination(language, target_os, architecture)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    shutil.copyfile(artifact, temporary)
    os.replace(temporary, output)
    print(f"Built native SDK artifact: {output.relative_to(ROOT)}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--language", choices=("npm", "python", "wasm", "all"), required=True)
    parser.add_argument("--debug", action="store_true", help="Build the dev profile (faster, larger).")
    parser.add_argument("-j", "--jobs", help="Forwarded to cargo build -j.")
    args = parser.parse_args()
    languages = ("npm", "python", "wasm") if args.language == "all" else (args.language,)
    for language in languages:
        build(language, debug=args.debug, jobs=args.jobs)


if __name__ == "__main__":
    main()
