"""Build the E2B template for composed videos (videos.generate); never snapshot user data or credentials.

The template holds the pinned Remotion packages (``REMOTION_PACKAGES`` in
``backend/shared/providers/e2b_remotion_renderer.py``, exact versions, no
"latest"), Chrome headless shell with its Debian libraries, and the system
fonts a composition may name (``INSTALLED_FONT_FAMILIES``). Composed-video
sandboxes run without internet, so everything a render needs must be here. The
fixed runner, Root and the composition are uploaded per request, so changes to
them need no rebuild. The build ends with a sample check and render, which
proves the template works and warms the bundler cache.

Run inside the API container with Vault-backed E2B credentials. Publishing
requires cost consent (``--execute``); without it the definition is printed as
a dry run. The default name is the one the provider starts
(``openmates-remotion-renderer-dev``); E2B_REMOTION_TEMPLATE only overrides it.
Usage: docker exec api python /app/backend/scripts/build_remotion_template.py --execute
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shlex
import time

from e2b import Template

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.providers.e2b_remotion_renderer import (
    FONT_APT_PACKAGES,
    INDEX_TS,
    INSTALLED_FONT_FAMILIES,
    REMOTION_PACKAGES,
    REMOTION_WORKDIR,
    ROOT_TSX,
    RUNNER_MJS,
    SOURCE_FILENAME,
    package_json,
    remotion_template_name,
)

# Remotion 4.0.540 bundles with rspack, which needs Node ^20.19 or >=22.12; the E2B base image has 20.9.
NODE_IMAGE = "22.21.1-bookworm"
# Debian 12 list from https://www.remotion.dev/docs/miscellaneous/linux-dependencies plus fontconfig.
CHROME_APT_PACKAGES = (
    "libnss3 libdbus-1-3 libatk1.0-0 libgbm-dev libasound2 libxrandr2 libxkbcommon-dev libxfixes3 "
    "libxcomposite1 libxdamage1 libpango-1.0-0 libcairo2 libcups2 libatk-bridge2.0-0 fontconfig"
)
SAMPLE_COMPOSITION = """import React from 'react';
import {AbsoluteFill, interpolate, Sequence, useCurrentFrame} from 'remotion';

export const video = {fps: 30, durationInFrames: 30, width: 640, height: 360};
export const parts = [
  {id: 'title', label: 'Title', from: 0, durationInFrames: 30, kind: 'text', texts: {title: 'Template check'}},
];

const Title: React.FC<{text: string}> = ({text}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{background: '#101820', justifyContent: 'center', alignItems: 'center'}}>
      <div style={{color: 'white', fontFamily: 'Inter', fontSize: 48, opacity}}>{text}</div>
    </AbsoluteFill>
  );
};

const Main: React.FC = () => (
  <Sequence from={parts[0].from} durationInFrames={parts[0].durationInFrames}>
    <Title text={parts[0].texts.title} />
  </Sequence>
);

export default Main;
"""


def _write(path: str, content: str) -> str:
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"mkdir -p $(dirname {shlex.quote(path)}) && printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}"


def _font_check() -> str:
    families = " ".join(shlex.quote(family) for family in INSTALLED_FONT_FAMILIES)
    return (f"for family in {families}; do fc-list \"$family\" family | grep -q . "
            "|| { echo \"missing font $family\"; exit 1; }; done")


def build_template() -> object:
    """Return the template definition; separated so tests can inspect it without building."""
    work = shlex.quote(REMOTION_WORKDIR)
    sample = " && ".join([
        _write(f"{REMOTION_WORKDIR}/runner.mjs", RUNNER_MJS),
        _write(f"{REMOTION_WORKDIR}/src/index.ts", INDEX_TS),
        _write(f"{REMOTION_WORKDIR}/src/Root.tsx", ROOT_TSX),
        _write(f"{REMOTION_WORKDIR}/src/{SOURCE_FILENAME}", SAMPLE_COMPOSITION),
        f"mkdir -p {work}/public/inputs",
        f"cd {work} && node runner.mjs check && cat out/meta.json && node runner.mjs render 15 2 && ls -la out",
        f"rm -rf {work}/out {work}/build {work}/src/{SOURCE_FILENAME} {work}/runner.mjs",
    ])
    return (
        Template().from_node_image(NODE_IMAGE)
        .set_user("root")
        .run_cmd("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
                 f"{CHROME_APT_PACKAGES} {FONT_APT_PACKAGES} && rm -rf /var/lib/apt/lists/* && fc-cache -f")
        .run_cmd(_font_check())
        .set_user("user")
        .set_workdir("/home/user")
        .run_cmd(f"mkdir -p {work} && " + _write(f"{REMOTION_WORKDIR}/package.json", package_json()))
        .run_cmd(f"cd {work} && npm install --no-audit --no-fund --save-exact && npx remotion versions")
        .run_cmd(f"cd {work} && npx remotion browser ensure")
        .run_cmd(sample)
    )


async def _api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="build and publish (costs E2B build time)")
    parser.add_argument("--name", default=remotion_template_name())
    parser.add_argument("--cpu-count", type=int, default=4)
    parser.add_argument("--memory-mb", type=int, default=4096)
    args = parser.parse_args()
    summary = {"alias": args.name, "node_image": NODE_IMAGE, "packages": REMOTION_PACKAGES, "fonts": INSTALLED_FONT_FAMILIES,
               "cpu_count": args.cpu_count, "memory_mb": args.memory_mb}
    if not args.execute:
        print(json.dumps({"dry_run": True, **summary}))
        return
    started = time.monotonic()
    result = Template.build(build_template(), name=args.name, api_key=asyncio.run(_api_key()),
                            cpu_count=args.cpu_count, memory_mb=args.memory_mb,
                            on_build_logs=lambda entry: print(str(entry)[:400], flush=True))
    print(json.dumps({"template_id": result.template_id, **summary,
                      "build_seconds": round(time.monotonic() - started, 3)}))


if __name__ == "__main__":
    main()
