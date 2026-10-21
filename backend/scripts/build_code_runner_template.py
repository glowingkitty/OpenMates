#!/usr/bin/env python3
"""Build generic Code Run toolchains; never snapshot user code or credentials.

Run inside the API container with Vault-backed E2B credentials. Publishing and
provider smoke tests require cost consent. Select the resulting immutable ID
with E2B_CODE_RUN_TEMPLATE only after the language smoke checks pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from e2b import Template

from backend.core.api.app.utils.secrets_manager import SecretsManager
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
    parser.add_argument("--name", required=True)
    parser.add_argument("--cpu-count", type=int, default=2)
    parser.add_argument("--memory-mb", type=int, default=512)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute and prior cost consent are required")
    template = (
        Template().from_base_image()
        .set_user("root")
        .run_cmd("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
                 "--no-install-recommends build-essential rustc cargo golang-go && "
                 "rm -rf /var/lib/apt/lists/*")
        .run_cmd("npm install --global --no-audit --no-fund tsx@4.20.6")
        .set_user("user")
        .set_workdir("/home/user")
        .run_cmd("python --version && node --version && tsx --version && bash --version && "
                 "gcc --version && g++ --version && rustc --version && cargo --version && go version")
    )
    started = time.monotonic()
    result = Template.build(template, name=args.name, api_key=asyncio.run(_api_key()),
                            cpu_count=args.cpu_count, memory_mb=args.memory_mb)
    print(json.dumps({"template_id": result.template_id, "alias": args.name,
                      "build_seconds": round(time.monotonic() - started, 3),
                      "cpu_count": args.cpu_count, "memory_mb": args.memory_mb}))


if __name__ == "__main__":
    main()
