#!/usr/bin/env python3
"""Generate bundled OpenMates web event data from the shared registry.

The public sidebar, event SEO pages, sitemap, and event embed deep links consume
frontend TypeScript, while the newsletter consumes shared YAML. This script keeps
those surfaces deterministic by compiling the YAML registry into one static TS
module and optimized web images under the SvelteKit static directory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.shared.python_utils.openmates_event_registry import load_openmates_events  # noqa: E402

OUTPUT_TS = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "data" / "openmatesEvents.ts"
STATIC_ASSET_DIR = REPO_ROOT / "frontend" / "apps" / "web_app" / "static" / "event-assets" / "openmates"
STATIC_URL_PREFIX = "/event-assets/openmates"
WEB_IMAGE_MAX_WIDTH = 1200
WEB_IMAGE_QUALITY = 82


def _event_type(event_type: str) -> str:
    normalized = event_type.lower()
    if "meetup" in normalized or "in_person" in normalized:
        return "PHYSICAL"
    return "ONLINE"


def _venue(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("venue"):
        parts = [part.strip() for part in str(raw["venue"]).split(",") if part.strip()]
        name = parts[0] if parts else "OpenMates event"
        address = ", ".join(parts[1:]) if len(parts) > 1 else ""
        city = "Berlin" if "Berlin" in str(raw["venue"]) else ""
        return {
            "name": name,
            "address": address,
            "city": city,
            "country": "Germany" if city == "Berlin" else "",
        }

    return {
        "name": "OpenMates online event",
        "address": str(raw.get("online_url") or "https://meet.openmates.org"),
        "city": "Online",
        "country": "",
    }


def _keywords(event: dict[str, Any], title: str) -> list[str]:
    event_type = str(event.get("event_type") or "").replace("_", " ")
    return [
        "OpenMates",
        "OpenMates Events",
        title,
        event_type.title(),
    ]


def _safe_output_name(slug: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", slug.lower()).strip("-") + ".jpg"


def _write_web_image(event: dict[str, Any]) -> str:
    asset_path = REPO_ROOT / event["assets"]["card"]["en"]["path"]
    if not asset_path.exists():
        raise FileNotFoundError(f"Event card image missing: {asset_path}")

    STATIC_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    output_name = _safe_output_name(str(event["slug"]))
    output_path = STATIC_ASSET_DIR / output_name

    with Image.open(asset_path) as image:
        converted = image.convert("RGB")
        if converted.width > WEB_IMAGE_MAX_WIDTH:
            ratio = WEB_IMAGE_MAX_WIDTH / converted.width
            converted = converted.resize((WEB_IMAGE_MAX_WIDTH, round(converted.height * ratio)), Image.Resampling.LANCZOS)
        converted.save(output_path, format="JPEG", quality=WEB_IMAGE_QUALITY, optimize=True, progressive=True)

    return f"{STATIC_URL_PREFIX}/{output_name}"


def _event_record(event: dict[str, Any]) -> dict[str, Any]:
    content = event["localized_content"]["en"]
    title = str(content["title"])
    return {
        "embed_id": str(event["slug"]),
        "id": str(event["id"]),
        "slug": str(event["slug"]),
        "provider": "luma",
        "title": title,
        "description": str(content["description"]),
        "url": str(event["luma_url"]),
        "date_start": str(event["starts_at"]),
        "date_end": str(event["ends_at"]),
        "timezone": str(event["timezone"]),
        "event_type": _event_type(str(event["event_type"])),
        "venue": _venue(event),
        "organizer": {
            "name": "OpenMates Events",
            "slug": "openmates",
        },
        "is_paid": False,
        "image_url": _write_web_image(event),
        "keywords": _keywords(event, title),
        "summary": str(content["summary"]),
        "online_url": str(event.get("online_url") or "") or None,
    }


def _ts_string(records: list[dict[str, Any]]) -> str:
    json_text = json.dumps(records, ensure_ascii=False, indent=2)
    return f'''/**
 * frontend/packages/ui/src/data/openmatesEvents.ts
 *
 * Generated from shared/events/openmates_events.yml by scripts/generate_openmates_events.py.
 * Used by the chat sidebar, event SEO pages, sitemap generation, and
 * hash-based event embed deep links. Do not edit records manually.
 */

export interface OpenMatesEvent {{
  embed_id: string;
  id: string;
  slug: string;
  provider: string;
  title: string;
  description: string;
  url: string;
  date_start: string;
  date_end: string;
  timezone: string;
  event_type: "ONLINE" | "PHYSICAL";
  venue: {{
    name: string;
    address: string;
    city: string;
    country: string;
    lat?: number;
    lon?: number;
  }};
  organizer: {{
    name: string;
    slug: string;
  }};
  is_paid: boolean;
  image_url: string;
  keywords: string[];
  summary: string;
  online_url?: string | null;
}}

export const OPENMATES_EVENTS: OpenMatesEvent[] = {json_text};

export function getAllOpenMatesEvents(): OpenMatesEvent[] {{
  return OPENMATES_EVENTS;
}}

export function getOpenMatesEventBySlug(slug: string): OpenMatesEvent | undefined {{
  return OPENMATES_EVENTS.find((event) => event.slug === slug || event.embed_id === slug);
}}
'''


def generate() -> list[Path]:
    registry = load_openmates_events()
    events = [event for event in registry["events"] if event.get("status") == "published"]
    records = [_event_record(event) for event in sorted(events, key=lambda item: (item["starts_at"], item["id"]))]
    OUTPUT_TS.write_text(_ts_string(records), encoding="utf-8")
    return [OUTPUT_TS, *sorted(STATIC_ASSET_DIR.glob("*.jpg"))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OpenMates web event data from the shared registry")
    parser.parse_args()
    for path in generate():
        print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
