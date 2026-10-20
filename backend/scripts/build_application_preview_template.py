#!/usr/bin/env python3
"""Prepare the secured E2B base image for low-latency app screenshots.

Runs inside the api container with Vault-backed credentials. Publishes a new
versioned template containing Playwright and Chromium at the provider's capture
directory; no OpenMates account data or secrets are placed in the image.
After building, select its ID with E2B_APPLICATION_PREVIEW_TEMPLATE in the target
runtime. The default provider still supports an unprepared E2B base sandbox.
Usage: python build_application_preview_template.py --execute --name <versioned-name>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import time

from e2b import Template

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_application_preview import APPLICATION_CAPTURE_DIRECTORY
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async


async def _api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--name", required=True, help="New versioned template alias")
    parser.add_argument("--capture-directory", default=APPLICATION_CAPTURE_DIRECTORY)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required to publish a provider template")
    directory = shlex.quote(args.capture_directory)
    template = (
        Template().from_base_image()
        .set_user("user")
        .set_envs({"PLAYWRIGHT_BROWSERS_PATH": f"{args.capture_directory}/browsers"})
        .run_cmd(f"mkdir -p {directory} && cd {directory} && npm init -y && "
                 "npm install --no-audit --no-fund playwright@1.60.0 && "
                 "npx playwright install --with-deps chromium")
        .set_workdir("/home/user")
        .run_cmd("npm init -y && npm install --ignore-scripts --no-audit --no-fund "
                 "svelte@5.55.7 vite@5.4.21 @sveltejs/vite-plugin-svelte@4.0.4 typescript@5.9.2")
    )
    started = time.monotonic()
    result = Template.build(template, name=args.name, api_key=asyncio.run(_api_key()))
    print(json.dumps({
        "template_id": result.template_id,
        "alias": args.name,
        "build_seconds": round(time.monotonic() - started, 3),
    }))


if __name__ == "__main__":
    main()
