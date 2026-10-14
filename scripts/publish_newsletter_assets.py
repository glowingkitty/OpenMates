#!/usr/bin/env python3
"""Publish reviewed newsletter images as compressed public website assets.

Run before deploying/sending. --manifest also accepts temporary admin campaign
YAML/JSON files. Remote references require an explicit URL=local-file override;
this tool never downloads URLs. Outputs deduplicate by final compressed bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.shared.python_utils.newsletter_assets import (  # noqa: E402
    ASSET_MAP_PATH, NEWSLETTER_IMAGE_MAX_BYTES, newsletter_asset_key,
)

STATIC_DIR = Path("frontend/apps/website/static/newsletter-assets")


def manifest_sources(manifest: dict[str, Any]) -> list[str]:
    sources = []
    for name in ("hero_image", "header_icon"):
        asset = manifest.get(name) or {}
        source = asset.get("path") or asset.get("url")
        if source:
            sources.append(str(source))
    assets = manifest.get("campaign_assets") or manifest.get("assets") or {}
    for asset in (assets.get("header") or {}).values():
        for field in ("path", "mobile_path"):
            if asset.get(field):
                sources.append(str(asset[field]))
    if (manifest.get("video") or {}).get("intro_fullscreen"):
        sources.extend(f"frontend/apps/web_app/static/newsletter-assets/intro-thumbnail-{lang}.jpg" for lang in ("EN", "DE"))
    return sources


def publish_sources(sources: list[str], *, repo_root: Path = REPO_ROOT,
                    remote_sources: dict[str, Path] | None = None) -> dict[str, Any]:
    map_path = repo_root / ASSET_MAP_PATH
    payload = json.loads(map_path.read_text()) if map_path.exists() else {"schema_version": 1, "assets": {}}
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported newsletter asset index version")
    output_dir = repo_root / STATIC_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(set(sources)):
        key = newsletter_asset_key(source)
        if key.startswith("https://"):
            path = (remote_sources or {}).get(key)
            if path is None:
                if key in payload["assets"]:
                    continue
                raise ValueError("Remote newsletter image needs --remote-source URL=reviewed-local-file")
        else:
            path = (repo_root / key).resolve()
            if not path.is_relative_to(repo_root.resolve()):
                raise ValueError("Newsletter source escapes repository")
        if path.suffix.lower() == ".svg":
            data = path.read_bytes()
            # Preserve the existing campaign-icon color treatment.
            data = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', 'fill="#4867CD"', data.decode("utf-8")).encode("utf-8")
            extension = "svg"
            dimensions = {}
        else:
            with Image.open(path) as source_image:
                image = ImageOps.exif_transpose(source_image).convert("RGBA")
                width = 640 if "newsletter-card" in key else 1200
                if image.width > width:
                    image = image.resize((width, max(1, round(image.height * width / image.width))), Image.Resampling.LANCZOS)
                flattened = Image.new("RGB", image.size, "white")
                flattened.paste(image, mask=image.getchannel("A"))
                output = io.BytesIO()
                flattened.save(output, format="JPEG", quality=78, optimize=True, progressive=True)
                data = output.getvalue()
                dimensions = {"width": image.width, "height": image.height}
                extension = "jpg"
        if not 0 < len(data) <= NEWSLETTER_IMAGE_MAX_BYTES:
            raise ValueError(f"Compressed newsletter image exceeds {NEWSLETTER_IMAGE_MAX_BYTES} bytes")
        filename = hashlib.sha256(data).hexdigest() + "." + extension
        (output_dir / filename).write_bytes(data)
        payload["assets"][key] = {"filename": filename, "size_bytes": len(data), **dimensions}
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--remote-source", action="append", default=[], metavar="URL=LOCAL_FILE")
    args = parser.parse_args()
    registry = yaml.safe_load((REPO_ROOT / "shared/events/openmates_events.yml").read_text())
    sources = manifest_sources(registry.get("campaign") or {})
    for event in registry["events"]:
        sources.extend(str(asset["path"]) for asset in event["assets"]["card"].values())
    for path in [*sorted((REPO_ROOT / "backend/newsletters/issues").glob("*.yml")), *args.manifest]:
        sources.extend(manifest_sources(yaml.safe_load(path.read_text()) or {}))
    remote_sources = {}
    for entry in args.remote_source:
        source, separator, filename = entry.rpartition("=")
        if not separator:
            parser.error("--remote-source requires URL=LOCAL_FILE")
        remote_sources[newsletter_asset_key(source)] = Path(filename).resolve()
    payload = publish_sources(sources, remote_sources=remote_sources)
    print(f"Published {len(payload['assets'])} newsletter image references; deploy website assets and bundled index before sending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
