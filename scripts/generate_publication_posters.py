"""Render title cards for publications without editorial artwork (requires Pillow).

Run from any directory. Outputs small 1200x630 JPEGs for Vercel static delivery;
uses public titles and the same bundled Lexend typeface as the app.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/apps/web_app/static/publications/previews"
FONT = ROOT / "backend/core/api/app/services/fonts/LexendDeca-Bold.ttf"


def render(slug: str, locale: str, title: str, category: str) -> None:
    image = Image.new("RGB", (1200, 630))
    draw = ImageDraw.Draw(image)
    for y in range(630):
        ratio = y / 629
        color = tuple(round(a + (b - a) * ratio) for a, b in zip((80, 105, 211), (105, 141, 236)))
        draw.line((0, y, 1200, y), fill=color)
    brand = ImageFont.truetype(str(FONT), 32)
    label = ImageFont.truetype(str(FONT), 24)
    draw.text((72, 52), "OpenMates", font=brand, fill="white")
    draw.text((72, 148), category, font=label, fill=(215, 226, 255))
    for size in range(62, 35, -2):
        font = ImageFont.truetype(str(FONT), size)
        lines = [""]
        for word in title.split():
            candidate = f"{lines[-1]} {word}".strip()
            if draw.textlength(candidate, font=font) > 1040 and lines[-1]:
                lines.append(word)
            else:
                lines[-1] = candidate
        if len(lines) * (size + 16) <= 290:
            break
    draw.multiline_text((72, 212), "\n".join(lines), font=font, fill="white", spacing=16)
    draw.text((72, 551), "openmates.org", font=label, fill=(215, 226, 255))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{slug}-{locale}.jpg"
    image.save(path, quality=88, optimize=True)
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    manifest = json.loads((ROOT / "frontend/apps/web_app/src/lib/publications/publicationManifest.v1.json").read_text())
    for post in manifest["publications"]:
        if post["kind"] == "blog" and not post.get("media"):
            for locale, copy in post["locales"].items():
                render(post["slug"], locale, copy["title"], "Blog")
    for locale in ("en", "de"):
        messages = json.loads((ROOT / f"frontend/packages/ui/src/i18n/locales/{locale}.json").read_text())
        title = messages["demo_chats"]["announcements_introducing_openmates_v011"]["title"]["text"]
        render("introducing-openmates-v011", locale, title, "Release")
