#!/usr/bin/env python3
"""Build the E2B template for design.embroidery; never snapshot user designs or credentials.

The template holds the pinned Ink/Stitch 3.3.0 release (sha256-verified), the GUI
libraries its bundle imports even headless, Inkscape for Ink/Stitch's realistic
stitch render, and the pinned Python packages of the uploaded preparation
pipeline (``backend/apps/design/embroidery_sandbox``). The pipeline itself is
uploaded per run, so pipeline changes need no rebuild.

The start command runs one tiny conversion with every export the pipeline uses,
so the snapshot holds Ink/Stitch's caches and the build fails early if a launch
breaks. Measured: a fresh sandbox's first launch still costs about 6 s extra, so
the provider also starts a background warm-up while it uploads the pipeline.

Run inside the API container with Vault-backed E2B credentials. Publishing
requires cost consent (``--execute``). The default template name is the one the
provider starts (``openmates-embroidery``); E2B_EMBROIDERY_TEMPLATE only overrides it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from e2b import Template

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.providers.e2b_embroidery import EMBROIDERY_TEMPLATE_NAME

INKSTITCH_VERSION = "3.3.0"
INKSTITCH_URL = (
    "https://github.com/inkstitch/inkstitch/releases/download/"
    f"v{INKSTITCH_VERSION}/inkstitch-{INKSTITCH_VERSION}-linux-x86_64.tar.xz"
)
INKSTITCH_SHA256 = "162bc16bfb80f18e2343050ab03ddb1c3b39c654fbc868a4a742a28d42ff1c79"
APT_PACKAGES = (
    "xz-utils curl ca-certificates unzip libgtk-3-0 libwayland-cursor0 libwayland-egl1 "
    "libnotify4 libsdl2-2.0-0 libxtst6 libsm6 libpcre2-32-0 libxkbcommon0 inkscape"
)
PIP_PACKAGES = ("shapely==2.1.1", "svgelements==1.9.6", "Pillow==11.3.0")
WARM_DIR = "/opt/openmates-warm"
# A 10 mm square: enough for Ink/Stitch to load every module the pipeline uses.
WARM_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10">'
    '<path d="M1 1H9V9H1Z" fill="#336699"/><path d="M1 5H9" fill="none" stroke="#aa0000" '
    'stroke-width="0.2"/></svg>'
)
WARM_CMD = (
    f"cd {WARM_DIR} && /opt/inkstitch/bin/inkstitch --extension=zip --format-dst=True "
    "--format-pes=True --format-exp=True --format-jef=True --format-vp3=True "
    "--format-threadlist=True --format-png-realistic=True "
    "--dpi-realistic=72 warm.svg > warm.zip 2> warm.log; touch warm.done; sleep infinity"
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
                 f"--no-install-recommends {APT_PACKAGES} && rm -rf /var/lib/apt/lists/*")
        .run_cmd(f"curl -fsSL -o /tmp/inkstitch.tar.xz {INKSTITCH_URL} && "
                 f"echo '{INKSTITCH_SHA256}  /tmp/inkstitch.tar.xz' | sha256sum -c - && "
                 "tar -xJf /tmp/inkstitch.tar.xz -C /opt && rm /tmp/inkstitch.tar.xz && "
                 "test -x /opt/inkstitch/bin/inkstitch")
        .run_cmd("python -m pip install --no-cache-dir " + " ".join(PIP_PACKAGES))
        .run_cmd(f"mkdir -p {WARM_DIR} && printf '%s' '{WARM_SVG}' > {WARM_DIR}/warm.svg && "
                 f"chown -R user:user {WARM_DIR}")
        .set_user("user")
        .set_workdir("/home/user")
        .run_cmd("python -c 'import shapely, svgelements, PIL' && inkscape --version")
        .set_start_cmd(f"bash -c '{WARM_CMD}'", f"test -f {WARM_DIR}/warm.done")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--name", default=EMBROIDERY_TEMPLATE_NAME)
    parser.add_argument("--cpu-count", type=int, default=2)
    parser.add_argument("--memory-mb", type=int, default=2048)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute and prior cost consent are required")
    started = time.monotonic()
    result = Template.build(build_template(), name=args.name, api_key=asyncio.run(_api_key()),
                            cpu_count=args.cpu_count, memory_mb=args.memory_mb,
                            on_build_logs=lambda entry: print(str(entry)[:300], flush=True))
    print(json.dumps({"template_id": result.template_id, "alias": args.name,
                      "inkstitch_version": INKSTITCH_VERSION,
                      "build_seconds": round(time.monotonic() - started, 3),
                      "cpu_count": args.cpu_count, "memory_mb": args.memory_mb}))


if __name__ == "__main__":
    main()
