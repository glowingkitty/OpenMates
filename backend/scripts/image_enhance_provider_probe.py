"""One live call to the image Enhance model (feature.embed-user-edits, Plan A2).

Self-contained so it runs inside the deployed ``api`` container against the
current worktree code without mounting it:

    docker exec -i api python - < backend/scripts/image_enhance_provider_probe.py

Sends one small synthetic picture (about 0.05 USD) to Google's official Gemini
API with the same model id, prompt, 2K size and nearest aspect ratio as
``backend/shared/providers/google/gemini_image_enhance.py`` and prints only the
model, the output size and the seconds taken. The API key comes from the
environment or, inside the containers, from Vault; it is never printed.
"""

from __future__ import annotations

import asyncio
import io
import math
import time

from google import genai
from google.genai import types
from PIL import Image, ImageDraw

MODEL_ID = "gemini-nano-banana-2.1"
IMAGE_SIZE = "2K"
RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
PROMPT = (
    "Re-render this exact image at higher quality. Keep the composition, subjects, poses, colours, "
    "lighting, layout and any text exactly as they are. Improve only fine detail: faces, hands, "
    "textures, edges and the legibility of text. Do not add, remove or move anything."
)


def nearest_ratio(width: int, height: int) -> str:
    target = math.log(width / height)
    return min(RATIOS, key=lambda r: abs(math.log(int(r.split(":")[0]) / int(r.split(":")[1])) - target))


async def api_key() -> str:
    # Same priority as the provider: real env value, else Vault ("IMPORTED_TO_VAULT" is a sentinel).
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.providers.google.gemini_image import _get_google_ai_studio_api_key

    secrets = SecretsManager()
    await secrets.initialize()
    key = await _get_google_ai_studio_api_key(secrets)
    if not key:
        raise SystemExit("No Google AI Studio key available")
    return key


def source_png() -> bytes:
    image = Image.new("RGB", (640, 360), "#2a6f97")
    draw = ImageDraw.Draw(image)
    draw.ellipse((220, 80, 420, 280), fill="#f4d35e")
    draw.rectangle((40, 300, 600, 330), fill="#ee964b")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def main() -> None:
    client = genai.Client(api_key=await api_key())
    ratio = nearest_ratio(640, 360)
    started = time.monotonic()
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL_ID,
        contents=[types.Part.from_bytes(data=source_png(), mime_type="image/png"), PROMPT],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=ratio, image_size=IMAGE_SIZE),
        ),
    )
    seconds = time.monotonic() - started
    parts = [part for candidate in (response.candidates or []) for part in (candidate.content.parts or [])
             if part.inline_data and part.inline_data.data]
    if not parts:
        raise SystemExit(f"model={MODEL_ID} returned no image after {seconds:.1f}s")
    with Image.open(io.BytesIO(parts[0].inline_data.data)) as image:
        size = image.size
    print(f"model={MODEL_ID} ratio={ratio} output={size[0]}x{size[1]} mime={parts[0].inline_data.mime_type} "
          f"seconds={seconds:.1f}")


asyncio.run(main())
