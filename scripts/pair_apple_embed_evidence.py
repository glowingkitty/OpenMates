#!/usr/bin/env python3
"""Pair browser-rendered embed captures with named XCUITest screenshots.

Export native attachments first with ``xcrun xcresulttool export attachments``.
XCUITest screenshot names must start with
``Embed parity|<registry key>|<preview|fullscreen>|<dimension id>``.
All paths in the output are relative to their respective evidence directories.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts.apple_ui_contracts import REQUIRED_EMBED_REGISTRY_DIMENSIONS, validate_contract
except ModuleNotFoundError:  # Direct invocation from scripts/.
    from apple_ui_contracts import REQUIRED_EMBED_REGISTRY_DIMENSIONS, validate_contract


NATIVE_NAME = re.compile(
    r"^Embed parity\|(?P<key>[^|]+)\|(?P<surface>preview|fullscreen)\|(?P<dimension>[^|_.]+(?:-[^|_.]+)*)(?:_|\.|$)"
)


def pair_evidence(
    web_contracts: list[tuple[Path, dict[str, Any]]],
    native_exports: list[tuple[Path, list[dict[str, Any]]]],
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    web: dict[tuple[str, str, str], str] = {}
    native: dict[tuple[str, str, str], str] = {}
    dimensions: set[str] = set()

    for contract_path, contract in web_contracts:
        dimension = contract.get("dimension", {}).get("id")
        if not isinstance(dimension, str) or not contract.get("registrySurfaces"):
            continue
        if dimension in dimensions:
            errors.append(f"duplicate web dimension: {dimension}")
        dimensions.add(dimension)
        for entry in contract.get("registrySurfaces", []):
            if not isinstance(entry, dict):
                continue
            identity = (dimension, entry.get("registryKey"), entry.get("surface"))
            relative_path = entry.get("screenshotPath")
            if not all(isinstance(value, str) for value in identity) or not isinstance(relative_path, str):
                continue
            if identity in web:
                errors.append(f"duplicate web screenshot: {identity}")
            if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
                errors.append(f"unsafe web screenshot path: {identity}")
                continue
            if not (contract_path.parent / relative_path).is_file():
                errors.append(f"web screenshot file missing: {identity}")
            web[identity] = relative_path

    missing_dimensions = REQUIRED_EMBED_REGISTRY_DIMENSIONS - dimensions
    if missing_dimensions:
        errors.append("missing web dimensions: " + ", ".join(sorted(missing_dimensions)))

    for export_path, export in native_exports:
        for test in export:
            for attachment in test.get("attachments", []):
                name = attachment.get("suggestedHumanReadableName", "")
                match = NATIVE_NAME.match(name)
                if not match:
                    continue
                identity = (match["dimension"], match["key"], match["surface"])
                filename = attachment.get("exportedFileName")
                if not isinstance(filename, str) or not filename.lower().endswith((".png", ".jpg", ".jpeg")):
                    errors.append(f"native screenshot has no image file: {identity}")
                    continue
                if Path(filename).name != filename or not (export_path.parent / filename).is_file():
                    errors.append(f"native screenshot file missing: {identity}")
                    continue
                if identity in native:
                    errors.append(f"duplicate native screenshot: {identity}")
                native[identity] = filename

    missing_native = sorted(web.keys() - native.keys())
    if missing_native:
        errors.append(f"missing {len(missing_native)} native screenshots")
    extra_native = sorted(native.keys() - web.keys())
    if extra_native:
        errors.append(f"unpaired {len(extra_native)} native screenshots")

    pairs = [
        {
            "dimension": dimension,
            "registryKey": key,
            "surface": surface,
            "webScreenshot": web[(dimension, key, surface)],
            "nativeScreenshot": native[(dimension, key, surface)],
            "reviewStatus": "unreviewed",
        }
        for dimension, key, surface in sorted(web.keys() & native.keys())
    ]
    return {"schemaVersion": 1, "surface": "apple-embed-evidence", "pairs": pairs}, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-contract", action="append", required=True, type=Path)
    parser.add_argument("--native-export", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    web_contracts = []
    for path in args.web_contract:
        errors = validate_contract(path, surface="embeds")
        if errors:
            parser.error(f"invalid web contract {path}: " + "; ".join(errors[:8]))
        web_contracts.append((path, json.loads(path.read_text(encoding="utf-8"))))
    native_exports = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in args.native_export]
    report, errors = pair_evidence(web_contracts, native_exports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Paired {len(report['pairs'])} embed screenshots; {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
