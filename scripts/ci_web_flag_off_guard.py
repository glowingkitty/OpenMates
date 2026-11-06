#!/usr/bin/env python3
"""Fail when a flag-off web build (VITE_OPENMATES_RUST_CORE unset) carries Rust core code.

Usage: ci_web_flag_off_guard.py <web_build_dir> [--repo <repo_root>]

Rust-migration lanes rely on dead-code elimination of
`import.meta.env.VITE_OPENMATES_RUST_CORE === '1'` branches. This check proves it
on the built output: no `.wasm` files, no output file named after a rustCore
module or the shared worker entry, and none of the marker strings derived from
the rustCore sources (shared-worker namespaces and refusal codes, the
`openmates:rust:` performance-mark prefix, the generated binding name).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RUST_CORE_DIRS = (
    "frontend/packages/ui/src/services/rustCore",
    "frontend/apps/web_app/src/lib/rustCore",
)
PROTOCOL = "frontend/packages/ui/src/services/rustCore/host/sharedWorkerProtocol.ts"
SOURCE_SUFFIXES = (".ts", ".js", ".mjs", ".svelte")
TEXT_SUFFIXES = (".js", ".mjs", ".css", ".html", ".json", ".map", ".webmanifest", ".txt")
FIXED_MARKERS = ("openmates:rust:", "openmates_browser", "rust_core_assets_disabled")


def _const_array(source: str, name: str) -> list[str]:
    match = re.search(rf"export const {name}\s*=\s*\[(.*?)\]\s*as const", source, re.S)
    if not match:
        raise ValueError(f"{name} not found in {PROTOCOL}")
    return re.findall(r"'([^']+)'", match.group(1))


def derive_markers(repo: Path) -> set[str]:
    """Distinctive strings that only exist in Rust core code, read from its sources.

    Namespaces and refusal codes are kept only when they cannot collide with
    ordinary identifiers: camelCase namespaces and snake_case refusal codes.
    """
    source = (repo / PROTOCOL).read_text()
    namespaces = [n for n in _const_array(source, "SHARED_NAMESPACES") if re.search(r"[a-z][A-Z]", n)]
    codes = [c for c in _const_array(source, "SHARED_REFUSAL_CODES") if "_" in c]
    if not namespaces or not codes:
        raise ValueError("no distinctive markers derived from the shared worker protocol")
    return {*namespaces, *codes, *FIXED_MARKERS}


def derive_name_stems(repo: Path) -> set[str]:
    """File stems of rustCore modules whose names would surface in emitted chunk names."""
    stems = {"worker.entry"}
    for directory in RUST_CORE_DIRS:
        for path in (repo / directory).rglob("*"):
            if path.suffix in SOURCE_SUFFIXES and "__tests__" not in path.parts and path.stem.endswith((".entry", ".worker")):
                stems.add(path.stem)
    return stems


def scan(build: Path, markers: set[str], stems: set[str]) -> list[str]:
    """Return human-readable violations found in a built output directory."""
    violations: list[str] = []
    for path in sorted(p for p in build.rglob("*") if p.is_file()):
        rel = path.relative_to(build).as_posix()
        if path.suffix == ".wasm" or rel.endswith(".wasm.br") or rel.endswith(".wasm.gz"):
            violations.append(f"{rel}: wasm file")
        if "rustCore" in rel or any(rel.split("/")[-1].startswith(stem) for stem in stems):
            violations.append(f"{rel}: rust core chunk/module name")
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(errors="ignore")
            hits = sorted(m for m in markers if m in text)
            if "rustCore/" in text:
                hits.append("rustCore/ source path")
            if hits:
                violations.append(f"{rel}: markers {hits}")
    return violations


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--repo"]
    repo = Path(argv[argv.index("--repo") + 1]) if "--repo" in argv else Path(__file__).resolve().parents[1]
    if "--repo" in argv:
        args.remove(argv[argv.index("--repo") + 1])
    if len(args) != 1 or not Path(args[0]).is_dir():
        print("usage: ci_web_flag_off_guard.py <web_build_dir> [--repo <repo_root>]", file=sys.stderr)
        return 2
    markers, stems = derive_markers(repo), derive_name_stems(repo)
    violations = scan(Path(args[0]), markers, stems)
    if violations:
        print("Flag-off web build contains Rust core artifacts:", file=sys.stderr)
        for line in violations:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"flag-off web build is free of Rust core artifacts ({len(markers)} markers checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
