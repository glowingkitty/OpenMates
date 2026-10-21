#!/usr/bin/env python3
"""Render controlled multilingual inspiration thumbnails without network access.

Loads the disclosed text-panel fixture and writes 560x420 JPEGs plus a manifest.
Checks actual installed font cmaps and requires RAQM for complex-script text.
Never truncates claims or substitutes missing glyphs; unsupported cases are flagged.
Refuses nonempty output directories, preserving existing manifests and recordings.
Run with the host Python environment providing Pillow and fontTools.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
import unicodedata

from fontTools.ttLib import TTFont
import PIL
from PIL import Image, ImageDraw, ImageFont, features

LOGGER = logging.getLogger(__name__)
WIDTH, HEIGHT = 560, 420
MIN_FONT_SIZE, MAX_FONT_SIZE = 20, 34
HORIZONTAL_MARGIN, VERTICAL_MARGIN, LINE_GAP = 32, 40, 25
JPEG_QUALITY = 95
COMPLEX_SCRIPTS = {"ar", "hi", "th"}
PREFERRED_FAMILIES = {
    "ar": "DejaVu Sans",
    "hi": "FreeSans",
    "th": "Loma",
    "ja": "IPAGothic",
    "ko": "sans-serif",
    "zh": "sans-serif",
}
DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures/daily_inspiration_thumbnail_v6.json"
READABILITY_LIMITATIONS = [
    "Controlled translated text panels, not independent real-world thumbnails.",
    "Cmap coverage confirms codepoint availability, not correct language, glyph shaping or native-speaker approval.",
    "RAQM capability and pixel bounds are checked; language-specific typography still needs visual review.",
    "Automatic bounds checks preserve all supplied text at 20–34 px; they are not human readability proof.",
    "Representative manual inspection, when performed separately, does not prove all 100 panels readable.",
]


def sha256(data: bytes) -> str:
    """Return the SHA-256 identity of exact bytes."""
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    """Serialize a case consistently for its identity in the manifest."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def inspect_font(path: Path, index: int) -> dict[str, Any]:
    """Read one font face's Unicode cmaps and exact font-file identity."""
    with TTFont(path, fontNumber=index, lazy=True) as font:
        codepoints = {
            codepoint
            for table in font["cmap"].tables
            if table.isUnicode()
            for codepoint, glyph in table.cmap.items()
            if glyph != ".notdef"
        }
    return {"codepoints": codepoints, "sha256": sha256(path.read_bytes())}


def font_candidates(language: str) -> list[dict[str, Any]]:
    """Ask installed fontconfig for locale-aware font candidates, without downloads."""
    if not shutil.which("fc-match"):
        raise RuntimeError("fc-match is unavailable; font selection cannot be verified")
    family = PREFERRED_FAMILIES.get(language, "DejaVu Sans")
    result = subprocess.run(
        ["fc-match", "-s", "-f", "%{file}\t%{index}\t%{family}\n", f"{family}:lang={language}"],
        check=True, text=True, capture_output=True,
    )
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        path = Path(parts[0])
        index = int(parts[1] or "0")
        identity = (str(path), index)
        if identity not in seen and path.suffix.lower() in {".ttf", ".ttc", ".otf"}:
            seen.add(identity)
            candidates.append({"path": path, "index": index, "family": parts[2]})
    return candidates


def required_codepoints(lines: list[str]) -> tuple[set[int], set[int]]:
    """Separate visible codepoints from format controls that need shaping, not glyphs."""
    characters = {ord(character) for line in lines for character in line}
    controls = {codepoint for codepoint in characters if unicodedata.category(chr(codepoint)) == "Cf"}
    return characters - controls, controls


def select_font(language: str, lines: list[str], cache: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    """Choose one installed face covering every visible codepoint in a case."""
    required, controls = required_codepoints(lines)
    best: dict[str, Any] | None = None
    errors: list[str] = []
    for candidate in font_candidates(language):
        key = (str(candidate["path"]), candidate["index"])
        try:
            if key not in cache:
                cache[key] = inspect_font(candidate["path"], candidate["index"])
            inspected = cache[key]
        except Exception as error:
            errors.append(f"{candidate['path']} face {candidate['index']}: {error}")
            continue
        missing = required - inspected["codepoints"]
        item = {
            "path": str(candidate["path"]), "face_index": candidate["index"],
            "family": candidate["family"], "file_sha256": inspected["sha256"],
            "selection": "fc-match -s, then exact Unicode cmap coverage",
            "glyph_coverage": {
                "complete": not missing, "required_codepoint_count": len(required),
                "covered_codepoint_count": len(required - missing),
                "missing_codepoints": [f"U+{codepoint:04X}" for codepoint in sorted(missing)],
                "format_controls_not_requiring_cmap": [f"U+{codepoint:04X}" for codepoint in sorted(controls)],
            },
        }
        if best is None or len(missing) < len(best["glyph_coverage"]["missing_codepoints"]):
            best = item
        if not missing:
            return item
    if best is None:
        raise RuntimeError("No usable installed font face found: " + "; ".join(errors))
    return best


def make_panel(case: dict[str, Any], font_info: dict[str, Any], raqm: bool) -> tuple[bytes, dict[str, Any]]:
    """Fit all three original lines without wrapping/truncation and encode a JPEG."""
    image = Image.new("RGB", (WIDTH, HEIGHT), "#122039")
    draw = ImageDraw.Draw(image)
    layout = ImageFont.Layout.RAQM if raqm else ImageFont.Layout.BASIC
    kwargs = {"direction": "rtl" if case["language"] == "ar" else "ltr", "language": case["language"]} if raqm else {}
    selected: tuple[Any, list[Any], int] | None = None
    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -1):
        font = ImageFont.truetype(font_info["path"], size, index=font_info["face_index"], layout_engine=layout)
        boxes = [draw.textbbox((0, 0), line, font=font, **kwargs) for line in case["lines"]]
        block_height = sum(box[3] - box[1] for box in boxes) + LINE_GAP * (len(boxes) - 1)
        if all(box[2] - box[0] <= WIDTH - 2 * HORIZONTAL_MARGIN for box in boxes) and block_height <= HEIGHT - 2 * VERTICAL_MARGIN:
            selected = font, boxes, block_height
            break
    if selected is None:
        raise ValueError("Complete text does not fit at the minimum 20 px font size")
    font, boxes, block_height = selected
    y = (HEIGHT - block_height) // 2
    bounds = []
    # Fixed neutral presentation is identical for all outcomes and locales.
    draw.rounded_rectangle((14, 14, WIDTH - 15, HEIGHT - 15), radius=18, outline="#65809e", width=2)
    for line, box in zip(case["lines"], boxes):
        x = (WIDTH - (box[2] - box[0])) / 2 - box[0]
        baseline_y = y - box[1]
        draw.text((x, baseline_y), line, font=font, fill="#ffffff", **kwargs)
        bounds.append([round(x + box[0], 2), y, round(x + box[2], 2), y + box[3] - box[1]])
        y += box[3] - box[1] + LINE_GAP
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True)
    encoded = stream.getvalue()
    with Image.open(BytesIO(encoded)) as decoded:
        decoded.load()
        if decoded.size != (WIDTH, HEIGHT) or decoded.format != "JPEG":
            raise ValueError("Encoded image failed JPEG dimensions verification")
    return encoded, {
        "font_size_px": font.size, "line_bounds_px": bounds,
        "text_preserved": True, "truncated": False, "wrapped": False,
        "within_canvas": all(0 <= b[0] < b[2] <= WIDTH and 0 <= b[1] < b[3] <= HEIGHT for b in bounds),
        "human_readability_verified": False,
    }


def run(args: argparse.Namespace) -> int:
    """Render supported cases, flag failures and atomically record the full manifest."""
    output = args.output_dir.absolute()
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ValueError("Output must be a new or empty nonsymlink directory; existing manifest/artifacts are never overwritten")
    fixture_path = args.fixture.resolve(strict=True)
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    cases = fixture["cases"]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Fixture must have nonempty cases with unique IDs")
    for case in cases:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", case["id"]):
            raise ValueError(f"Unsafe case ID: {case['id']!r}")
        if not 1 <= len(case["lines"]) <= 3 or any(not isinstance(line, str) or not line or "\n" in line for line in case["lines"]):
            raise ValueError(f"Case {case['id']} must contain one to three nonempty single lines")
    output.mkdir(parents=True, exist_ok=True)
    raqm = features.check_feature("raqm")
    manifest: dict[str, Any] = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixture_path": str(fixture_path), "fixture_sha256": sha256(fixture_bytes),
        "case_sha256_encoding": "UTF-8 JSON, sorted keys, no whitespace, ensure_ascii=false",
        "renderer_path": str(Path(__file__).resolve()), "renderer_sha256": sha256(Path(__file__).read_bytes()),
        "output_directory": str(output), "dimensions_px": [WIDTH, HEIGHT],
        "jpeg_quality": JPEG_QUALITY, "jpeg_chroma_subsampling": 0,
        "shaping_capability": {
            "pillow_version": PIL.__version__, "raqm_available": raqm,
            "raqm_version": features.version_feature("raqm") if raqm else None,
            "raqm_required_by_flag": args.require_raqm,
            "raqm_required_languages": sorted(COMPLEX_SCRIPTS),
            "policy": "Flag missing RAQM for Arabic, Hindi, Thai or when --require-raqm is passed; never silently render complex scripts with BASIC layout.",
        },
        "readability_limitations": READABILITY_LIMITATIONS,
        "manual_visual_review": "Not performed by the renderer; inspect a representative subset separately.",
        "cases": [],
    }
    cache: dict[tuple[str, int], dict[str, Any]] = {}
    for case in cases:
        item: dict[str, Any] = {
            "id": case["id"], "language": case["language"],
            "case_sha256": sha256(canonical_bytes(case)),
            "lines": case["lines"], "status": "flagged", "issues": [],
            "shaping": {"engine": "RAQM" if raqm else "BASIC", "direction": "rtl" if case["language"] == "ar" else "ltr", "language": case["language"]},
        }
        try:
            item["font"] = select_font(case["language"], case["lines"], cache)
            if not item["font"]["glyph_coverage"]["complete"]:
                raise ValueError("No installed single font face covers every supplied codepoint")
            if not raqm and (args.require_raqm or case["language"] in COMPLEX_SCRIPTS):
                raise ValueError("Required RAQM shaping is unavailable; panel was not rendered")
            encoded, readability = make_panel(case, item["font"], raqm)
            if not readability["within_canvas"]:
                raise ValueError("Measured text falls outside the canvas")
            filename = f"{case['id']}.jpg"
            # Exclusive creation also protects against unexpected concurrent output.
            with (output / filename).open("xb") as image_file:
                image_file.write(encoded)
            item.update({
                "status": "rendered", "image_file": filename,
                "image_sha256": sha256(encoded), "image_bytes": len(encoded),
                "readability": readability,
            })
        except Exception as error:
            LOGGER.error("Case %s flagged: %s", case["id"], error)
            item["issues"].append(str(error))
        manifest["cases"].append(item)
    counts = Counter(item["status"] for item in manifest["cases"])
    manifest["summary"] = {"case_count": len(cases), "rendered": counts["rendered"], "flagged": counts["flagged"], "locale_count": len({case["language"] for case in cases})}
    with (output / "manifest.json").open("x", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)
        manifest_file.write("\n")
    LOGGER.info("%s; manifest: %s", manifest["summary"], output / "manifest.json")
    return 1 if counts["flagged"] else 0


def main() -> int:
    """Parse explicit output and shaping requirements for the offline utility."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty directory; existing artifacts are never overwritten")
    parser.add_argument("--require-raqm", action="store_true", help="Require RAQM for every locale; Arabic, Hindi and Thai always require it")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        return run(args)
    except (OSError, ValueError, KeyError) as error:
        LOGGER.error("Rendering stopped: %s", error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
