#!/usr/bin/env python3
"""Prepare a lean E2B Chromium image, containing public dependencies only.

Run in the api container with Vault-backed credentials. --execute publishes a
new versioned template using E2B credits already authorized for this feature.
Select its immutable ID through E2B_BROWSE_TEMPLATE after the smoke probe passes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from e2b import Template

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async


async def api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--name", required=True, help="New versioned E2B template alias"
    )
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required to publish a provider template")
    template = (
        Template()
        .from_base_image()
        .set_user("root")
        .set_envs({"PLAYWRIGHT_BROWSERS_PATH": "/opt/openmates-browser/browsers"})
        .run_cmd(
            "python3 -m venv /opt/openmates-browser/venv && "
            "/opt/openmates-browser/venv/bin/pip install --no-cache-dir playwright==1.56.0 protego==0.5.0"
        )
        .run_cmd(
            "/opt/openmates-browser/venv/bin/playwright install --with-deps chromium && "
            "chmod -R a+rX /opt/openmates-browser"
        )
        .set_user("user")
        .set_workdir("/home/user")
    )
    started = time.monotonic()
    result = Template.build(
        template,
        name=args.name,
        api_key=asyncio.run(api_key()),
        cpu_count=2,
        memory_mb=4096,
    )
    print(
        json.dumps(
            {
                "template_id": result.template_id,
                "alias": args.name,
                "build_seconds": round(time.monotonic() - started, 3),
                "cpu_count": 2,
                "memory_mb": 4096,
                "contains_user_state": False,
            }
        )
    )


if __name__ == "__main__":
    main()
