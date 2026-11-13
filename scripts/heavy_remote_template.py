#!/usr/bin/env python3
"""Build (or refresh) the E2B template that heavy_slot runs cargo and vitest in.

The template holds the public repository at one commit of origin/dev, the Rust
toolchain pinned by `packages/openmates-rust/Cargo.toml` (`rust-version`), the
crates `cargo fetch` downloads, and the installed pnpm workspace. It holds no
compiled Rust output: measured on 2026-11-12, a day-old compiled baseline saved
nothing (270 s against 250 s cold) because most of the time is the
`openmates-sdk` crate itself, which changes daily.

Started with the E2B SDK venv through `python3 scripts/heavy_slot.py remote-template`.
Rebuilding under the same alias replaces the template for new sandboxes only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heavy_remote  # noqa: E402 - sibling module; path set up above

REPO_URL = "https://github.com/glowingkitty/OpenMates.git"
NODE_IMAGE_MAJOR = "24"
# python3-cryptography: Rust tests spawn the tests/sdk-conformance Python peers.
APT_PACKAGES = ["build-essential", "pkg-config", "git", "ca-certificates", "curl", "xz-utils",
                "python3", "python3-cryptography"]


def rust_version(root: Path) -> str:
    manifest = (root / "packages" / "openmates-rust" / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^rust-version\s*=\s*"([^"]+)"', manifest, re.MULTILINE)
    if not match:
        raise SystemExit("heavy_remote_template: rust-version missing in packages/openmates-rust/Cargo.toml")
    return match.group(1)


def origin_dev(root: Path) -> str:
    subprocess.run(["git", "-C", str(root), "fetch", "-q", "origin", "dev"], check=True)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "origin/dev"], check=True,
                          capture_output=True, text=True).stdout.strip()


def template_definition(commit: str, toolchain: str):
    from e2b import Template

    repo = heavy_remote.plan.REMOTE_ROOT
    return (
        Template().from_node_image(NODE_IMAGE_MAJOR)
        .set_user("root")
        .apt_install(APT_PACKAGES)
        .set_user("user")
        .set_workdir("/home/user")
        .run_cmd("curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal "
                 f"--component clippy --default-toolchain {toolchain}")
        .run_cmd("mkdir -p $HOME/.local/bin && corepack enable --install-directory $HOME/.local/bin")
        .run_cmd(f"git init -q {repo} && cd {repo} && git remote add origin {REPO_URL} && "
                 f"git fetch -q --depth 1 origin {commit} && git checkout -q FETCH_HEAD")
        .set_workdir(repo)
        .run_cmd("$HOME/.cargo/bin/cargo fetch --locked")
        .run_cmd("CI=1 PATH=$HOME/.local/bin:$PATH corepack pnpm install --frozen-lockfile")
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", help="origin/dev commit to bake in (default: current origin/dev)")
    args = parser.parse_args(argv)
    from e2b import Template

    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True,
                               capture_output=True, text=True).stdout.strip())
    commit = args.commit or origin_dev(root)
    toolchain = rust_version(root)
    started = time.monotonic()
    print(f"heavy_remote_template: building {heavy_remote.TEMPLATE_ALIAS} at {commit[:12]} "
          f"(Rust {toolchain}, {heavy_remote.SANDBOX_CPUS} CPUs, {heavy_remote.SANDBOX_MEMORY_MB} MB)",
          flush=True)
    info = Template.build(template_definition(commit, toolchain), name=heavy_remote.TEMPLATE_ALIAS,
                          cpu_count=heavy_remote.SANDBOX_CPUS, memory_mb=heavy_remote.SANDBOX_MEMORY_MB,
                          api_key=heavy_remote.e2b_api_key())
    print(f"heavy_remote_template: built {info.template_id} in {time.monotonic() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
