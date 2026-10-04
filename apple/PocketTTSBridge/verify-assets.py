#!/usr/bin/env python3
"""Explicit root-invoked smoke asset preparation using the app's exact catalog.
No authentication, personal files or model downloads unless --download is given.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    catalog = Path(__file__).resolve().parents[1] / "OpenMates/Resources/LocalModels/catalog.json"
    model = next(m for m in json.loads(catalog.read_text())["models"] if m["id"] == "pocketTTS")
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for entry in model["files"]:
        path = root / entry["path"]
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError("Asset path rejected")
        path.parent.mkdir(parents=True, exist_ok=True)
        if args.download and not path.exists():
            partial = path.with_name(path.name + ".smoke-partial")
            if partial.exists() or partial.is_symlink(): raise ValueError("Existing smoke partial requires review")
            digest, size = hashlib.sha256(), 0
            try:
                with urllib.request.urlopen(entry["url"], timeout=60) as response, partial.open("xb") as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > entry["sizeBytes"]: raise ValueError("Asset size rejected")
                        digest.update(chunk); output.write(chunk)
                if size != entry["sizeBytes"] or digest.hexdigest() != entry["sha256"]:
                    raise ValueError("Asset checksum rejected")
                partial.rename(path)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024): digest.update(chunk)
        if path.stat().st_size != entry["sizeBytes"] or digest.hexdigest() != entry["sha256"]:
            raise ValueError("Asset verification failed")
    print(f"verified_files={len(model['files'])} verified_bytes={model['estimatedSizeBytes']}")


if __name__ == "__main__": main()
