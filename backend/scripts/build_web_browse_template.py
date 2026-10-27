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
from pathlib import Path
import time

from e2b import Template, wait_for_port

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
    parser.add_argument(
        "--base-template", help="Existing public dependency-only template to reuse"
    )
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required to publish a provider template")
    context = Path(__file__).resolve().parent.parent / "shared" / "providers"
    base = Template(file_context_path=context)
    base = (
        base.from_template(args.base_template)
        if args.base_template
        else base.from_base_image()
    )
    template = (
        base.set_user("root")
        .set_envs({"PLAYWRIGHT_BROWSERS_PATH": "/opt/openmates-browser/browsers"})
        .run_cmd(
            "python3 -m venv /opt/openmates-browser/venv && "
            "/opt/openmates-browser/venv/bin/pip install --no-cache-dir playwright==1.64.1 protego==0.5.0"
        )
        .run_cmd(
            "/opt/openmates-browser/venv/bin/playwright install --with-deps chromium && "
            "chmod -R a+rX /opt/openmates-browser"
        )
        .set_user("user")
        .set_workdir("/home/user")
        .run_cmd(
            "mkdir -p /home/user/.openmates-browse && chmod 700 /home/user/.openmates-browse && rm -f /home/user/.openmates-browse/config.json"
        )
        .copy(
            "web_browse_runtime.py",
            "/home/user/.openmates-browse/",
            user="user",
            mode=0o600,
        )
        .run_cmd("test -f /home/user/.openmates-browse/web_browse_runtime.py")
        .set_start_cmd(
            "env PLAYWRIGHT_BROWSERS_PATH=/opt/openmates-browser/browsers /opt/openmates-browser/venv/bin/python /home/user/.openmates-browse/web_browse_runtime.py",
            wait_for_port(8765),
        )
    )
    started = time.monotonic()
    result = Template.build(
        template,
        name=args.name,
        api_key=asyncio.run(api_key()),
        cpu_count=2,
        memory_mb=4096,
        on_build_logs=lambda entry: print(
            json.dumps({"build_log": entry.message}), flush=True
        ),
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
                "prebooted": True,
                "runtime_protocol": "preboot-v1",
            }
        )
    )


if __name__ == "__main__":
    main()
