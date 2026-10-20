#!/usr/bin/env python3
# contract-test-file: tooling
"""Measure a cold two-file Svelte preview using the real E2B provider.

Runs in the api container with Vault-backed credentials; no AI inference or
OpenMates account data is involved. One disposable sandbox is always stopped.
Records HTTP readiness separately from screenshot installation/capture and saves
an interactive browser recording. Candidate provider files can be staged under
/tmp without changing the running API or workers.
Usage: python test_application_preview_startup.py --execute --output-dir /tmp/preview-proof
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any

import e2b

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async


BROWSER_CHECK = r"""
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
           '--no-zygote', '--single-process', '--js-flags=--jitless'],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      recordVideo: { dir: '/tmp/openmates-startup-proof', size: { width: 1280, height: 800 } },
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    const response = await page.goto('http://127.0.0.1:5173/', { waitUntil: 'load', timeout: 15000 });
    assert.equal(response.status(), 200);
    await page.getByRole('heading', { name: 'Recipe Manager', exact: true }).waitFor();
    await page.getByTestId('recipe-filter').fill('berry');
    await page.getByTestId('recipe-option').click();
    await page.getByTestId('cook-button').click();
    assert.equal((await page.getByTestId('cook-count').textContent()).trim(), 'Cooked 1 times');
    assert.equal((await page.getByTestId('recipe-count').textContent()).trim(), '1 recipes');
    assert.deepEqual(errors, []);
    await page.waitForTimeout(500);
    const video = page.video();
    await context.close();
    console.log(JSON.stringify({ interactive: true, page_errors: errors, video_path: await video.path() }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(String(error)); process.exit(1); });
"""


async def _api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicitly allow one real E2B sandbox")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider-source", type=Path, default=Path(
        "/app/backend/shared/providers/e2b_application_preview.py",
    ))
    parser.add_argument("--fixture", type=Path, default=Path(
        "/app/backend/apps/ai/testing/fixtures/application_preview.json",
    ))
    parser.add_argument("--max-ready-seconds", type=float, default=15.0)
    parser.add_argument("--max-screenshot-seconds", type=float, default=15.0)
    parser.add_argument("--template", help="Prepared secured-access-compatible E2B template ID")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for the live provider check")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    spec = importlib.util.spec_from_file_location("application_preview_candidate", args.provider_source)
    assert spec and spec.loader
    provider = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = provider
    spec.loader.exec_module(provider)
    if args.template:
        os.environ[provider.APPLICATION_PREVIEW_TEMPLATE_ENV] = args.template
    fixture = json.loads(args.fixture.read_text())
    file_data = fixture["embeds"]["11111111-1111-4111-8111-111111111111"]["files"]
    if {file["path"] for file in file_data} != {"package.json", "src/App.svelte"}:
        raise ValueError("The startup regression must use the incomplete two-file bundle")
    api_key = asyncio.run(_api_key())
    sdk_sandbox = e2b.Sandbox
    sandboxes: list[Any] = []
    started = time.monotonic()
    receipt: dict[str, Any] = {
        "provider_source_sha256": hashlib.sha256(args.provider_source.read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "input_paths": [file["path"] for file in file_data],
        "max_ready_seconds": args.max_ready_seconds,
        "max_screenshot_seconds": args.max_screenshot_seconds,
        "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "template": args.template,
        "events": [],
    }

    def event(phase: str) -> float:
        elapsed = round(time.monotonic() - started, 3)
        item = {"phase": phase, "elapsed_seconds": elapsed}
        receipt["events"].append(item)
        print(json.dumps(item), flush=True)
        return elapsed

    class TrackedCommands:
        def __init__(self, commands: Any) -> None:
            self.commands = commands

        def run(self, command: str, **kwargs: Any) -> Any:
            arguments = shlex.split(command)
            shell_command = arguments[:2] == ["bash", "-lc"]
            inner_command = arguments[2] if shell_command else command
            capture = "chromium.launch" in inner_command and "const png =" in inner_command
            phase = "browser_capture" if capture else (
                "browser_setup" if "playwright install" in command else "server_launch" if kwargs.get("background") else "dependency_install"
            )
            if capture:
                inner_command = inner_command.replace(
                    "(async () => {",
                    "const began = Date.now();\n"
                    "const stamp = phase => console.error('OPENMATES_CAPTURE_PHASE:' + JSON.stringify({phase, seconds:(Date.now()-began)/1000}));\n"
                    "(async () => {",
                ).replace(
                    "  try {\n    const page",
                    "  stamp('browser_launched');\n  try {\n    const page",
                ).replace(
                    "    try { await page.waitForLoadState",
                    "    stamp('page_loaded');\n    try { await page.waitForLoadState",
                ).replace(
                    "    try { await page.evaluate",
                    "    stamp('network_settled');\n    try { await page.evaluate",
                ).replace(
                    "    process.stdout.write",
                    "    stamp('screenshot_captured');\n    process.stdout.write",
                )
                command = f"bash -lc {shlex.quote(inner_command)}" if shell_command else inner_command
            event(f"{phase}_started")
            result = self.commands.run(command, **kwargs)
            event(f"{phase}_finished")
            if capture:
                receipt["browser_phases"] = [
                    json.loads(line.split(":", 1)[1])
                    for line in result.stderr.splitlines()
                    if line.startswith("OPENMATES_CAPTURE_PHASE:")
                ]
            return result

    class SandboxProxy:
        def __init__(self, sandbox: Any) -> None:
            self.sandbox = sandbox
            self.commands = TrackedCommands(sandbox.commands)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.sandbox, name)

    class TrackedSandbox:
        @staticmethod
        def create(**kwargs: Any) -> Any:
            # Bound the external resource even if process cleanup is interrupted.
            kwargs["timeout"] = 600
            sandbox = sdk_sandbox.create(**kwargs)
            sandboxes.append(sandbox)
            event("sandbox_created")
            return SandboxProxy(sandbox)

        kill = staticmethod(sdk_sandbox.kill)

    def ready(_runtime: Any) -> None:
        receipt["http_ready_seconds"] = event("http_ready")

    e2b.Sandbox = TrackedSandbox
    try:
        runtime = provider.start_application_preview_in_e2b(
            files=[provider.ApplicationPreviewFile(path=file["path"], content=file["content"]) for file in file_data],
            entrypoints=[provider.ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
            api_key=api_key,
            on_runtime_ready=ready,
        )
        receipt["first_screenshot_seconds"] = event("first_screenshot")
        if not runtime.latest_screenshot_bytes:
            raise AssertionError("Provider did not return a rendered PNG")
        (args.output_dir / "preview.png").write_bytes(runtime.latest_screenshot_bytes)
        command = f"cd {shlex.quote(provider.APPLICATION_CAPTURE_DIRECTORY)} && node - <<'NODE'\n{BROWSER_CHECK}\nNODE"
        check = sandboxes[0].commands.run(f"bash -lc {shlex.quote(command)}", timeout=60)
        if check.exit_code != 0:
            raise RuntimeError(f"Interactive preview check failed: {check.stderr[-1000:]}")
        browser_result = json.loads(check.stdout.strip())
        receipt["interactive"] = browser_result["interactive"]
        receipt["interactive_verified_seconds"] = event("interactive_verified")
        video_bytes = sandboxes[0].files.read(browser_result["video_path"], format="bytes")
        (args.output_dir / "interactive.webm").write_bytes(bytes(video_bytes))
        receipt["status"] = "pass" if (
            receipt["http_ready_seconds"] <= args.max_ready_seconds
            and receipt["first_screenshot_seconds"] <= args.max_screenshot_seconds
        ) else "slow"
    except Exception as exc:
        receipt.update(status="fail", error=str(exc))
    finally:
        e2b.Sandbox = sdk_sandbox
        for sandbox in sandboxes:
            sdk_sandbox.kill(sandbox_id=sandbox.sandbox_id, api_key=api_key)
        receipt["sandboxes_stopped"] = len(sandboxes)
        (args.output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
