#!/usr/bin/env python3
"""Build the hosted Project sandbox template (daemon + toolchains, no sudo for `user`).

Run inside the API container with Vault-backed E2B credentials and cost consent.
The daemon (`openmates-sandbox-host`, built from packages/openmates-rust with
`--features sandbox-host`) is copied to /usr/local/bin owned by root. The
backend starts it as root; model commands run as `user`, who must not be able
to become root, so every sudo grant of `user` is removed. Prints the template
id; select it with E2B_PROJECT_SANDBOX_TEMPLATE after the smoke checks pass.

Usage:
  python backend/scripts/build_project_sandbox_template.py --execute \
      --name project-sandbox-1 --binary target/release/openmates-sandbox-host \
      [--base-template <code-run template id>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from e2b import Template

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async

BINARY_TARGET = "/usr/local/bin/openmates-sandbox-host"

# Drop every sudo path of `user`: sudoers entries and the sudo group.
REMOVE_SUDO = (
    "for f in /etc/sudoers.d/*; do [ -e \"$f\" ] && sed -i '/^user[[:space:]]/d' \"$f\"; done; "
    "sed -i '/^user[[:space:]]/d;/^%sudo/d;/^%admin/d' /etc/sudoers 2>/dev/null; "
    "(deluser user sudo || gpasswd -d user sudo || true) 2>/dev/null; "
    "! (sudo -n -l -U user 2>/dev/null | grep -q 'may run')"
)


async def _api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--name", required=True)
    parser.add_argument("--binary", required=True, help="Linux x86_64 openmates-sandbox-host build")
    parser.add_argument("--base-template", help="existing Code Run template id (keeps its toolchains)")
    parser.add_argument("--cpu-count", type=int, default=2)
    parser.add_argument("--memory-mb", type=int, default=1024)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute and prior cost consent are required")
    binary = Path(args.binary).resolve()
    if not binary.is_file():
        parser.error(f"binary not found: {binary}")
    template = Template(file_context_path=str(binary.parent))
    if args.base_template:
        builder = template.from_template(args.base_template)
    else:
        builder = (
            template.from_base_image()
            .set_user("root")
            .run_cmd("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
                     "--no-install-recommends build-essential rustc cargo golang-go && "
                     "rm -rf /var/lib/apt/lists/*")
            .run_cmd("npm install --global --no-audit --no-fund tsx@4.20.6")
        )
    builder = (
        builder.set_user("root")
        .run_cmd("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
                 "--no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*")
        .copy(binary.name, BINARY_TARGET, user="root", mode=0o755)
        .run_cmd(f"chown root:root {BINARY_TARGET} && chmod 0755 {BINARY_TARGET}")
        .run_cmd("mkdir -p /home/user/project && chown user:user /home/user/project")
        .run_cmd(REMOVE_SUDO)
        .run_cmd("git --version && openmates-sandbox-host serve </dev/null 2>&1 | head -1; true")
        .set_user("user")
        .set_workdir("/home/user")
    )
    started = time.monotonic()
    result = Template.build(builder, name=args.name, api_key=asyncio.run(_api_key()),
                            cpu_count=args.cpu_count, memory_mb=args.memory_mb)
    print(json.dumps({"template_id": result.template_id, "alias": args.name,
                      "build_seconds": round(time.monotonic() - started, 3),
                      "cpu_count": args.cpu_count, "memory_mb": args.memory_mb}))


if __name__ == "__main__":
    main()
