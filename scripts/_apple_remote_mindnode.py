#!/usr/bin/env python3
"""Bounded MindNode capability discovery for the Apple Remote transport.

Reads installed app metadata only; never launches an app or reads user maps.
The guarded Apple Remote entrypoint owns Mac transport and deletion policy.
Dictionary availability is evidence of an interface, not verified automation.
Native writes stay disabled until an isolated actual-app round trip is proven.
See docs/contributing/guides/apple-remote-mindnode.md for scope and evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import xml.etree.ElementTree as ET


MAX_METADATA_BYTES = 1024 * 1024
MAX_APP_BUNDLES = 8
MAX_REQUEST_BYTES = 4096


class MindNodeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def public_bundle_file(path: Path) -> bytes:
    """Read one bounded regular file without following a bundle symlink."""
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise MindNodeError("unsafe_bundle_path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise MindNodeError("unsafe_bundle_path")
        if info.st_size > MAX_METADATA_BYTES:
            raise MindNodeError("metadata_too_large")
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            raise MindNodeError("metadata_too_large")
        return data
    finally:
        os.close(fd)


def scripting_dictionary(app: Path, info: dict) -> dict:
    name = info.get("NSScriptingDefinition")
    if not name:
        return {"status": "not_declared"}
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".sdef"):
        raise MindNodeError("unsafe_bundle_path")
    raw = public_bundle_file(app / "Contents/Resources" / name)
    if b"<!ENTITY" in raw.upper():
        raise MindNodeError("unsupported_dictionary")
    try:
        root = ET.fromstring(raw)
        xml = raw.decode("utf-8")
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise MindNodeError("unsupported_dictionary") from exc
    if root.tag != "dictionary":
        raise MindNodeError("unsupported_dictionary")
    return {"status": "dictionary_present", "sha256": hashlib.sha256(raw).hexdigest(), "xml": xml}


def discover_capabilities(application_roots: list[Path] | None = None) -> dict:
    """Inspect fixed Applications locations, never document collections."""
    roots = application_roots if application_roots is not None else [
        Path("/Applications"), Path.home() / "Applications",
    ]
    result = {"ok": False, "apps": [], "write_enabled": False, "native_round_trip_verified": False}
    try:
        for directory in roots:
            if any(part.is_symlink() for part in (directory, *directory.parents)):
                raise MindNodeError("unsafe_bundle_path")
            if not directory.exists():
                continue
            for app in sorted(directory.glob("MindNode*.app")):
                if len(result["apps"]) >= MAX_APP_BUNDLES:
                    raise MindNodeError("too_many_app_bundles")
                info = plistlib.loads(public_bundle_file(app / "Contents/Info.plist"))
                if not isinstance(info, dict):
                    raise MindNodeError("invalid_app_metadata")
                result["apps"].append({
                    "bundle_path": str(app),
                    "bundle_id": info.get("CFBundleIdentifier"),
                    "version": info.get("CFBundleShortVersionString"),
                    "build": info.get("CFBundleVersion"),
                    "document_types": info.get("CFBundleDocumentTypes", []),
                    "exported_types": info.get("UTExportedTypeDeclarations", []),
                    "scripting": scripting_dictionary(app, info),
                })
        if not result["apps"]:
            raise MindNodeError("mindnode_not_found")
        result["ok"] = True
    except MindNodeError as exc:
        result["error"] = {"code": exc.code}
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        result["error"] = {"code": "capability_read_failed", "type": type(exc).__name__}
    return result


def execute(request: dict) -> dict:
    if request != {"action": "capabilities"}:
        return {"ok": False, "error": {"code": "unsupported_request"}}
    return discover_capabilities()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise MindNodeError("request_too_large")
        request = json.loads(raw)
        result = execute(request)
    except (ValueError, UnicodeDecodeError) as exc:
        result = {"ok": False, "error": {"code": getattr(exc, "code", "invalid_request")}}
    print(json.dumps(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
