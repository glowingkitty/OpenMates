#!/usr/bin/env python3
"""Vendor the pinned Tiptap browser runtime for the Apple composer.

The Apple app loads the composer from a local WKWebView resource so the editor
must not fetch remote JavaScript at runtime. This script downloads ESM bundles
for the already-pinned Tiptap packages, follows their absolute esm.sh imports,
and writes the modules under apple/OpenMates/Resources/TiptapComposer/vendor/.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = REPO_ROOT / "apple/OpenMates/Resources/TiptapComposer"
VENDOR_ROOT = RESOURCE_ROOT / "vendor"
ESM_BASE_URL = "https://esm.sh"
TIPTAP_VERSION = "3.26.0"
ENTRY_SPECS = {
    "tiptap-core.mjs": f"/@tiptap/core@{TIPTAP_VERSION}?bundle&target=es2022",
    "tiptap-starter-kit.mjs": f"/@tiptap/starter-kit@{TIPTAP_VERSION}?bundle&target=es2022",
    "tiptap-placeholder.mjs": f"/@tiptap/extension-placeholder@{TIPTAP_VERSION}?bundle&target=es2022",
}
IMPORT_PATTERN = re.compile(r"(?:import|export)\s*(?:[^'\"]*?\s+from\s*)?['\"]([^'\"]+)['\"]")
JSX_RUNTIME_IMPORT = f"/@tiptap/core@{TIPTAP_VERSION}/es2022/dist/jsx-runtime/jsx-runtime.mjs"
JSX_RUNTIME_STUB = """/* Local OpenMates stub for Tiptap JSX runtime namespace imports. */
export const Fragment = Symbol.for('openmates.tiptap.fragment');
export function jsx(type, props, key) { return { type, props, key }; }
export const jsxs = jsx;
export const jsxDEV = jsx;
"""


def fetch_module(spec: str) -> str:
    request = Request(
        urljoin(ESM_BASE_URL, spec),
        headers={"User-Agent": "OpenMates Apple composer vendoring"},
    )
    with urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def normalize_module_text(text: str) -> str:
    return text.replace(
        "/@tiptap/core@^3.26.0/dist/jsx-runtime/jsx-runtime?target=es2022",
        JSX_RUNTIME_IMPORT,
    )


def local_path_for(spec: str) -> Path:
    parsed = urlparse(spec)
    return VENDOR_ROOT / parsed.path.lstrip("/")


def write_module(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_entry_module(filename: str, text: str) -> str:
    text = normalize_module_text(text)
    if filename == "tiptap-starter-kit.mjs":
        return "\n".join(
            line for line in text.splitlines() if "dist/jsx-runtime/jsx-runtime" not in line
        ) + "\n"
    return text


def crawl_module(spec: str, seen: set[str]) -> None:
    if not spec.startswith("/") or spec in seen:
        return
    seen.add(spec)
    if urlparse(spec).path == urlparse(JSX_RUNTIME_IMPORT).path:
        write_module(local_path_for(spec), JSX_RUNTIME_STUB)
        return
    text = normalize_module_text(fetch_module(spec))
    write_module(local_path_for(spec), text)
    for dependency in IMPORT_PATTERN.findall(text):
        if dependency.startswith("/"):
            crawl_module(dependency, seen)


def vendor() -> int:
    if VENDOR_ROOT.exists():
        shutil.rmtree(VENDOR_ROOT)
    VENDOR_ROOT.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    for filename, spec in ENTRY_SPECS.items():
        text = normalize_entry_module(filename, fetch_module(spec))
        write_module(VENDOR_ROOT / filename, text)
        for dependency in IMPORT_PATTERN.findall(text):
            if dependency.startswith("/"):
                crawl_module(dependency, seen)

    print(f"Vendored {len(seen)} Tiptap dependency modules into {VENDOR_ROOT.relative_to(REPO_ROOT)}")
    return 0


def check() -> int:
    required = [
        VENDOR_ROOT / "tiptap-core.mjs",
        VENDOR_ROOT / "tiptap-starter-kit.mjs",
        VENDOR_ROOT / "tiptap-placeholder.mjs",
        VENDOR_ROOT / f"@tiptap/core@{TIPTAP_VERSION}/es2022/core.bundle.mjs",
        VENDOR_ROOT / f"@tiptap/starter-kit@{TIPTAP_VERSION}/es2022/starter-kit.bundle.mjs",
        VENDOR_ROOT / f"@tiptap/extension-placeholder@{TIPTAP_VERSION}/es2022/extension-placeholder.bundle.mjs",
    ]
    missing = [path for path in required if not path.exists()]
    missing.extend(find_missing_imports())
    if missing:
        for path in missing:
            print(f"Missing vendored module: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    print("Apple Tiptap composer vendor check passed")
    return 0


def import_target(source: Path, spec: str) -> Path | None:
    parsed = urlparse(spec)
    if spec.startswith("/"):
        return VENDOR_ROOT / parsed.path.lstrip("/")
    if spec.startswith("./") or spec.startswith("../"):
        return (source.parent / parsed.path).resolve()
    return None


def find_missing_imports() -> list[Path]:
    missing: list[Path] = []
    sources = [RESOURCE_ROOT / "composer.js", *VENDOR_ROOT.rglob("*.mjs")]
    for source in sources:
        if not source.exists():
            continue
        text = source.read_text(encoding="utf-8")
        for spec in IMPORT_PATTERN.findall(text):
            target = import_target(source, spec)
            if target is not None and not target.exists():
                missing.append(target)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify required vendored modules without downloading")
    args = parser.parse_args()
    return check() if args.check else vendor()


if __name__ == "__main__":
    raise SystemExit(main())
