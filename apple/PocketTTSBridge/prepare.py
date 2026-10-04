#!/usr/bin/env python3
"""Prepare only the verified public Pocket source; never fetch model weights.

The deterministic privacy patch shadows print macros in the Pocket crate before
its modules. Token IDs/audio samples/input are never formatted or logged. This
changes neither model math nor process-wide logging. Cached source is verified
on every build, including the exact post-patch hash of every extracted file.
"""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

REVISION = "ce0a41d118077bfed02361406f5fac747cd8e411"
URL = f"https://codeload.github.com/UnaMentis/pocket-tts-ios/tar.gz/{REVISION}"
SHA256 = "b497ad679aefcf9fb3063eaa1c14990b7eade140584c920bfca798c84429a5c2"
MAX_BYTES = 6 * 1024 * 1024
PATCH = """// OpenMates deterministic privacy patch: no input/token/audio debug output.
macro_rules! eprintln { ($($arg:tt)*) => {{}}; }
macro_rules! println { ($($arg:tt)*) => {{}}; }
macro_rules! eprint { ($($arg:tt)*) => {{}}; }
macro_rules! print { ($($arg:tt)*) => {{}}; }

"""


def prepared_files(data):
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("Pocket source checksum mismatch")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            parts = member.name.split("/")
            if parts[0] != f"pocket-tts-ios-{REVISION}" or any(p in (".", "..") for p in parts):
                raise ValueError("Invalid Pocket archive path")
            if member.issym() or member.islnk():
                raise ValueError("Pocket archive links are forbidden")
            path = "/".join(parts[1:])
            if not member.isfile() or not (path.startswith("src/") or path.startswith("cmake/") or path in ("Cargo.toml", "Cargo.lock", "build.rs", "LICENSE")):
                continue
            files[path] = archive.extractfile(member).read()
    source = files["src/lib.rs"].decode()
    anchor = "pub mod audio;"
    if source.count(anchor) != 1:
        raise ValueError("Pocket privacy patch anchor changed")
    files["src/lib.rs"] = source.replace(anchor, PATCH + anchor).encode()
    # Only use the default CPU backend. Build the dependency as an rlib.
    manifest = files["Cargo.toml"].decode()
    files["Cargo.toml"] = manifest.replace('crate-type = ["staticlib", "cdylib", "rlib"]', 'crate-type = ["rlib"]').encode()
    return files


def prepare(repo):
    cache = repo / ".runtime/pocket-tts"
    cache.mkdir(parents=True, exist_ok=True)
    if cache.is_symlink() or any(p.is_symlink() for p in cache.parents):
        raise ValueError("Pocket cache links are forbidden")
    archive = cache / f"source-{REVISION}.tar.gz"
    if archive.is_symlink():
        raise ValueError("Pocket archive links are forbidden")
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError("Pocket source download rejected")
        archive.write_bytes(data)
    if archive.stat().st_size > MAX_BYTES:
        raise ValueError("Pocket source archive is oversized")
    files = prepared_files(archive.read_bytes())
    root = cache / "runtime"
    root.mkdir(exist_ok=True)
    for name, data in files.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
            raise ValueError("Pocket source cache links are forbidden")
        if not destination.exists() or destination.read_bytes() != data:
            destination.write_bytes(data)
    receipt = {"revision": REVISION, "archive_sha256": SHA256, "privacy_patch": "crate-print-macros-v1",
               "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    (cache / "source-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return root


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parents[2])
