#!/usr/bin/env python3
"""Fail when a flag-off web build (VITE_OPENMATES_RUST_CORE unset) carries Rust core code.

Usage: ci_web_flag_off_guard.py <web_build_dir> [--repo <repo_root>] [--report-only]

`--report-only` prints GitHub warning annotations and exits 0 (use while a known
leak is being fixed; drop the flag to enforce).

Rust-migration lanes rely on dead-code elimination of
`import.meta.env.VITE_OPENMATES_RUST_CORE === '1'` branches. This check proves it
on the built output: no `.wasm` files, no output file named after a rustCore
module or the shared worker entry, and none of the marker strings derived from
the rustCore sources (the full shared-worker namespace set appearing together,
refusal codes, the `openmates:rust:` performance-mark prefix, the generated
binding name). A `.wasm` counts only when it is wasm-bindgen output or names
openmates; third-party wasm (onnxruntime, etc.) is legitimate in both builds.
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


def derive_namespaces(repo: Path) -> set[str]:
    """camelCase shared-worker namespaces; alone they are ordinary identifiers, together they are the protocol."""
    source = (repo / PROTOCOL).read_text()
    namespaces = {n for n in _const_array(source, "SHARED_NAMESPACES") if re.search(r"[a-z][A-Z]", n)}
    if len(namespaces) < 2:
        raise ValueError("no distinctive namespaces derived from the shared worker protocol")
    return namespaces


def derive_markers(repo: Path) -> set[str]:
    """Strings that only exist in Rust core code, read from its sources (snake_case refusal codes)."""
    source = (repo / PROTOCOL).read_text()
    codes = {c for c in _const_array(source, "SHARED_REFUSAL_CODES") if "_" in c}
    if not codes:
        raise ValueError("no refusal codes derived from the shared worker protocol")
    return {*codes, *FIXED_MARKERS}


def derive_name_stems(repo: Path) -> set[str]:
    """File stems of rustCore modules whose names would surface in emitted chunk names."""
    stems = {"worker.entry"}
    for directory in RUST_CORE_DIRS:
        for path in (repo / directory).rglob("*"):
            if path.suffix in SOURCE_SUFFIXES and "__tests__" not in path.parts and path.stem.endswith((".entry", ".worker")):
                stems.add(path.stem)
    return stems


def _is_rust_wasm(path: Path) -> bool:
    head = path.read_bytes()
    return b"__wbindgen" in head or b"openmates" in head or "openmates" in path.name


def scan(build: Path, markers: set[str], stems: set[str], namespaces: frozenset[str] = frozenset()) -> list[str]:
    """Return human-readable violations found in a built output directory."""
    violations: list[str] = []
    for path in sorted(p for p in build.rglob("*") if p.is_file()):
        rel = path.relative_to(build).as_posix()
        if path.suffix == ".wasm" and _is_rust_wasm(path):
            violations.append(f"{rel}: wasm file")
        if "rustCore" in rel or any(rel.split("/")[-1].startswith(stem) for stem in stems):
            violations.append(f"{rel}: rust core chunk/module name")
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(errors="ignore")
            found = {m: re.search(rf"(?<![A-Za-z0-9_]){re.escape(m)}(?![A-Za-z0-9_])", text) for m in markers}
            found = {m: hit for m, hit in found.items() if hit}
            hits = sorted(found)
            if namespaces and all(n in text for n in namespaces):
                hits.append(f"all shared-worker namespaces {sorted(namespaces)}")
                found.setdefault(sorted(namespaces)[0], re.search(re.escape(sorted(namespaces)[0]), text))
            if "rustCore/" in text:
                hits.append("rustCore/ source path")
            if hits:
                at = min(hit.start() for hit in found.values())
                context = " context=" + repr(text[max(0, at - 150) : at + 250])
                violations.append(f"{rel}: markers {hits}{context}")
    return violations


def main(argv: list[str]) -> int:
    report_only = "--report-only" in argv
    args = [a for a in argv if a != "--report-only"]
    repo = Path(__file__).resolve().parents[1]
    if "--repo" in args:
        position = args.index("--repo")
        repo = Path(args[position + 1])
        del args[position : position + 2]
    if len(args) != 1 or not Path(args[0]).is_dir():
        print("usage: ci_web_flag_off_guard.py <web_build_dir> [--repo <repo_root>]", file=sys.stderr)
        return 2
    markers, stems = derive_markers(repo), derive_name_stems(repo)
    violations = scan(Path(args[0]), markers, stems, frozenset(derive_namespaces(repo)))
    if violations:
        print("Flag-off web build contains Rust core artifacts:", file=sys.stderr)
        for line in violations:
            print(f"  {line}", file=sys.stderr)
            if report_only:
                print(f"::warning title=Rust core in flag-off web build::{line}")
        return 0 if report_only else 1
    print(f"flag-off web build is free of Rust core artifacts ({len(markers)} markers checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
