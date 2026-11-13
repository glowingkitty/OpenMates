#!/usr/bin/env python3
"""Build the E2B template for images.modify; never snapshot user pictures or credentials.

The template holds the pinned image libraries a model-written editing program
may import (Pillow, NumPy, OpenCV headless, CairoSVG with the Cairo system
library) and a few common open fonts for simple text. The fixed runner and the
program are uploaded per request by ``backend/shared/providers/e2b_image_edit.py``,
so runner changes need no rebuild. The Code Run template cannot be used: it has
no image libraries and the sandbox has no internet to install them.

Run inside the API container with Vault-backed E2B credentials. Publishing
requires cost consent (``--execute``); without it the template definition is
printed as a dry run. The default template name is the one the provider starts
(``openmates-image-edit``); E2B_IMAGE_EDIT_TEMPLATE only overrides it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from e2b import Template

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.providers.e2b_image_edit import IMAGE_EDIT_TEMPLATE_NAME

# libcairo2 is CairoSVG's renderer; fontconfig lets Pillow and Cairo find the fonts.
APT_PACKAGES = (
    "libcairo2 libpango-1.0-0 libpangocairo-1.0-0 fontconfig "
    "fonts-dejavu-core fonts-liberation fonts-noto-core"
)
PIP_PACKAGES = (
    "Pillow==11.3.0", "numpy==2.2.6", "opencv-python-headless==4.12.0.88",
    "cairosvg==2.8.2", "cairocffi==1.7.1", "cssselect2==0.8.0", "tinycss2==1.4.0",
    "defusedxml==0.7.1",
)
# Imports every allowed library once, so the build fails early when one is broken.
CHECK_CMD = (
    "python -c \"import PIL, numpy, cv2, cairosvg; from PIL import ImageFont; "
    "ImageFont.truetype('DejaVuSans.ttf', 12); "
    "cairosvg.svg2png(bytestring=b'<svg xmlns=\\\"http://www.w3.org/2000/svg\\\" width=\\\"4\\\" "
    "height=\\\"4\\\"><rect width=\\\"4\\\" height=\\\"4\\\"/></svg>'); "
    "print(PIL.__version__, numpy.__version__, cv2.__version__, cairosvg.__version__)\" && fc-list | wc -l"
)


async def _api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def build_template() -> object:
    """Return the template definition; separated so tests can inspect it without building."""
    return (
        Template().from_base_image()
        .set_user("root")
        .run_cmd("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
                 f"--no-install-recommends {APT_PACKAGES} && rm -rf /var/lib/apt/lists/* && fc-cache -f")
        .run_cmd("python -m pip install --no-cache-dir " + " ".join(PIP_PACKAGES))
        .set_user("user")
        .set_workdir("/home/user")
        .run_cmd(CHECK_CMD)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="build and publish (costs E2B build time)")
    parser.add_argument("--name", default=IMAGE_EDIT_TEMPLATE_NAME)
    parser.add_argument("--cpu-count", type=int, default=2)
    parser.add_argument("--memory-mb", type=int, default=2048)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"dry_run": True, "alias": args.name, "apt": APT_PACKAGES, "pip": PIP_PACKAGES,
                          "cpu_count": args.cpu_count, "memory_mb": args.memory_mb}))
        return
    started = time.monotonic()
    result = Template.build(build_template(), name=args.name, api_key=asyncio.run(_api_key()),
                            cpu_count=args.cpu_count, memory_mb=args.memory_mb,
                            on_build_logs=lambda entry: print(str(entry)[:300], flush=True))
    print(json.dumps({"template_id": result.template_id, "alias": args.name, "pip": PIP_PACKAGES,
                      "build_seconds": round(time.monotonic() - started, 3),
                      "cpu_count": args.cpu_count, "memory_mb": args.memory_mb}))


if __name__ == "__main__":
    main()
