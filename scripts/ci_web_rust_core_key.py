#!/usr/bin/env python3
"""Content-addressed cache key for the web Rust core package.

Purpose: `build-rust-core-web.mjs` turns the `openmates-browser-bindings` crate
into `target/web-rust-core-pkg`. This prints a sha256 over every input of that
build so CI can restore the finished package instead of rebuilding it.
Inputs: file CONTENTS from the working tree (not the git index, so unstaged
candidate patches count) of the workspace Cargo.toml/Cargo.lock, rust-toolchain
files, the build script, the bindings crate and every path dependency crate
(resolved statically and recursively from Cargo.toml, `[patch]` paths included),
plus the pinned tool versions, target, profile and flags the script passes.
Usage: python3 scripts/ci_web_rust_core_key.py [repo-root]
"""
from __future__ import annotations

import hashlib
import sys
import tomllib
from pathlib import Path

ROOT_CRATE = "packages/openmates-browser-bindings"
BUILD_SCRIPT = "frontend/apps/web_app/scripts/build-rust-core-web.mjs"
LITERALS = (
    "rust=1.98.1",
    "wasm-bindgen=0.2.129",
    "target=wasm32-unknown-unknown",
    "profile=wasm-web",
    "rustflags=-C target-feature=+simd128",
    "cargo-flags=--locked -p openmates-browser-bindings",
    "wasm-bindgen-flags=--target web --out-name openmates_browser",
    "key-version=1",
)
SKIP_DIRS = {"target", ".git", "node_modules", "__pycache__"}


def _collect(node: object, found: set[str]) -> None:
    """Collect `path` values from dependency-spec tables (not [[bin]] paths)."""
    if isinstance(node, dict):
        if isinstance(node.get("path"), str):
            found.add(node["path"])
        for value in node.values():
            _collect(value, found)


def _path_deps(node: object, found: set[str]) -> None:
    """Collect path dependencies from a parsed Cargo.toml tree."""
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key.endswith("dependencies") or key == "patch":
            _collect(value, found)
        elif key in ("target", "workspace") or key.startswith("cfg("):
            _path_deps(value, found)


def crate_dirs(root: Path) -> list[Path]:
    """The bindings crate plus all path-dependency crates, recursively."""
    seen: dict[Path, None] = {}
    # Workspace-level [patch] / [workspace.dependencies] paths apply to every crate.
    queue: list[Path] = [root / ROOT_CRATE]
    workspace = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))
    top: set[str] = set()
    _path_deps(workspace, top)
    queue += [(root / p).resolve() for p in sorted(top)]
    while queue:
        crate = queue.pop().resolve()
        if crate in seen:
            continue
        manifest = crate / "Cargo.toml"
        if not manifest.is_file():
            raise SystemExit(f"ci_web_rust_core_key: missing crate manifest {manifest}")
        seen[crate] = None
        deps: set[str] = set()
        _path_deps(tomllib.loads(manifest.read_text(encoding="utf-8")), deps)
        queue += [crate / p for p in sorted(deps)]
    return sorted(seen)


def input_files(root: Path) -> list[Path]:
    """Sorted, de-duplicated list of every file that feeds the build."""
    root = root.resolve()
    files: set[Path] = {root / BUILD_SCRIPT, root / "Cargo.toml", root / "Cargo.lock"}
    for name in ("rust-toolchain", "rust-toolchain.toml"):
        if (root / name).is_file():
            files.add(root / name)
    for crate in crate_dirs(root):
        for path in crate.rglob("*"):
            relative = path.relative_to(crate)
            if path.is_file() and not SKIP_DIRS.intersection(relative.parts):
                files.add(path)
    for required in (root / BUILD_SCRIPT, root / "Cargo.lock"):
        if not required.is_file():
            raise SystemExit(f"ci_web_rust_core_key: missing input {required}")
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def compute_key(root: Path) -> str:
    """sha256 over literals, sorted relative paths and file contents."""
    root = root.resolve()
    digest = hashlib.sha256()
    for literal in LITERALS:
        digest.update(literal.encode() + b"\0")
    for path in input_files(root):
        content = path.read_bytes()
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(str(len(content)).encode() + b"\0" + content + b"\0")
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    print(compute_key(root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
