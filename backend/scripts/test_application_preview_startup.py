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
import threading
from pathlib import Path
from typing import Any

import e2b

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async


from application_preview_interaction_probe import RemoteInteractionProbe, sandbox_resources


async def _api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow disposable E2B app VM (plus browser helper in prepared mode)")
    parser.add_argument("--prepared-browser-probe", action="store_true", help="Prepare a separate E2B client browser before starting the cold app clock")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider-source", type=Path, default=Path(
        "/app/backend/shared/providers/e2b_application_preview.py",
    ))
    parser.add_argument("--fixture", type=Path, default=Path(
        "/app/backend/apps/ai/testing/fixtures/application_preview.json",
    ))
    parser.add_argument("--max-ready-seconds", type=float, default=15.0)
    parser.add_argument("--max-screenshot-seconds", type=float, default=15.0)
    parser.add_argument("--interaction-scenario", choices=("recipe", "todo"), default="recipe")
    parser.add_argument("--max-interactive-seconds", type=float, default=15.0)
    templates = parser.add_mutually_exclusive_group()
    templates.add_argument("--template", help="Force base template; clears inherited warm-template setting")
    templates.add_argument("--warm-template", help="Force eligible warm template; verify SDK selects this exact ID")
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
        os.environ.pop(provider.APPLICATION_PREVIEW_WARM_TEMPLATE_ENV, None)
    elif args.warm_template:
        os.environ[provider.APPLICATION_PREVIEW_WARM_TEMPLATE_ENV] = args.warm_template
    fixture = json.loads(args.fixture.read_text())
    file_data = fixture["embeds"]["11111111-1111-4111-8111-111111111111"]["files"]
    if {file["path"] for file in file_data} != {"package.json", "src/App.svelte"}:
        raise ValueError("The startup regression must use the incomplete two-file bundle")
    api_key = asyncio.run(_api_key())
    sdk_sandbox = e2b.Sandbox
    sandboxes: list[Any] = []
    browser_helpers: list[Any] = []
    started = time.monotonic()
    receipt: dict[str, Any] = {
        "provider_source_sha256": hashlib.sha256(args.provider_source.read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "input_paths": [file["path"] for file in file_data],
        "max_ready_seconds": args.max_ready_seconds,
        "max_screenshot_seconds": args.max_screenshot_seconds,
        "max_interactive_seconds": args.max_interactive_seconds,
        "measurement": "cold provider invocation including sandbox create/upload/build; remote public-preview interaction",
        "execution_location": "generated app and browser exclusively in E2B",
        "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "template": args.template,
        "warm_template": args.warm_template,
        "prepared_browser_probe": args.prepared_browser_probe,
        "events": [],
    }

    event_lock = threading.Lock()
    probe: RemoteInteractionProbe | None = None

    def event(phase: str) -> float:
        elapsed = round(time.monotonic() - started, 3)
        item = {"phase": phase, "elapsed_seconds": elapsed}
        with event_lock:
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
            receipt["actual_sdk_template"] = kwargs.get("template")
            expected_template = args.warm_template or args.template
            if expected_template and kwargs.get("template") != expected_template:
                raise ValueError("Requested template was not selected by provider")
            receipt["sandbox_resources"] = {key: kwargs[key] for key in ("template", "cpu_count", "memory_mb") if key in kwargs}
            receipt["sandbox_timeout_seconds"] = 600
            kwargs["timeout"] = 600
            sandbox = sdk_sandbox.create(**kwargs)
            sandboxes.append(sandbox)
            event("sandbox_created")
            return SandboxProxy(sandbox)

        kill = staticmethod(sdk_sandbox.kill)

    def ready(_runtime: Any) -> None:
        nonlocal probe
        receipt["http_ready_seconds"] = event("http_ready")
        if args.prepared_browser_probe:
            if probe is None:
                raise AssertionError("Prepared browser is missing")
            receipt["browser_target_upload_started_seconds"] = event("browser_target_upload_started")
            probe.send_target(_runtime.upstream_base_url, sandboxes[-1].get_host(5173))
            receipt["browser_target_upload_finished_seconds"] = event("browser_target_upload_finished")
            return
        probe = RemoteInteractionProbe(
            sandbox=sandboxes[-1], url=_runtime.upstream_base_url,
            capture_directory=provider.APPLICATION_CAPTURE_DIRECTORY,
            scenario=args.interaction_scenario, output_dir=args.output_dir, event=event,
        )
        probe.start()

    try:
        if args.prepared_browser_probe:
            helper_started = time.monotonic()
            receipt["browser_helper"] = {"events": [], "clock": "separate helper-preparation clock"}
            receipt["measurement"] = "cold app provider invocation -> already prepared separate E2B browser public-HTTPS interaction"

            def helper_event(phase: str) -> float:
                if phase not in ("interactive_probe_started", "browser_ready"):
                    return event(phase)
                elapsed = round(time.monotonic() - helper_started, 3)
                receipt["browser_helper"]["events"].append({"phase": phase, "elapsed_seconds": elapsed})
                print(json.dumps({"helper_phase": phase, "helper_elapsed_seconds": elapsed}), flush=True)
                return elapsed

            helper_template = args.warm_template or args.template
            if not helper_template:
                raise ValueError("Prepared browser requires an explicit template")
            helper = sdk_sandbox.create(
                template=helper_template, api_key=api_key, timeout=600,
                envs={"PLAYWRIGHT_BROWSERS_PATH": provider.APPLICATION_CAPTURE_DIRECTORY + "/browsers"},
                secure=True, allow_internet_access=True, network={"allow_public_traffic": True},
            )
            browser_helpers.append(helper)
            receipt["browser_helper"].update(template=helper_template, timeout_seconds=600)
            probe = RemoteInteractionProbe(
                sandbox=helper, url=None, capture_directory=provider.APPLICATION_CAPTURE_DIRECTORY,
                scenario=args.interaction_scenario, output_dir=args.output_dir, event=helper_event,
                prepared=True,
            )
            probe.start()
            probe.wait_for_browser_ready()
            receipt["browser_helper"]["preparation_seconds"] = round(time.monotonic() - helper_started, 3)
            # Client browser is now listening. No generated app has been uploaded or started.
            started = time.monotonic()
        e2b.Sandbox = TrackedSandbox
        event("cold_app_provider_invoked")
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
        if probe is None:
            raise AssertionError("Provider did not call on_runtime_ready")
        receipt["interaction"] = probe.finish()
        receipt["sandbox_resources"].update(sandbox_resources(sandboxes[-1]))
        if browser_helpers:
            receipt["browser_helper"]["resources"] = sandbox_resources(browser_helpers[-1])
        receipt["interactive"] = receipt["interaction"].get("interactive", False)
        receipt["interactive_verified_seconds"] = receipt["interaction"].get("interaction_acknowledged_seconds")
        if not receipt["interactive"]:
            raise AssertionError("Public preview interaction failed")
        receipt["status"] = "pass" if (
            receipt["http_ready_seconds"] <= args.max_ready_seconds
            and receipt["first_screenshot_seconds"] <= args.max_screenshot_seconds
            and receipt["interactive_verified_seconds"] <= args.max_interactive_seconds
        ) else "slow"
    except Exception as exc:
        receipt.update(status="fail", error_type=type(exc).__name__)
    finally:
        e2b.Sandbox = sdk_sandbox
        if probe is not None and "interaction" not in receipt:
            receipt["interaction"] = probe.finish()
        stopped = 0
        for sandbox in sandboxes:
            try:
                sdk_sandbox.kill(sandbox_id=sandbox.sandbox_id, api_key=api_key)
                stopped += 1
            except Exception as exc:
                receipt.setdefault("cleanup_errors", []).append(type(exc).__name__)
                receipt["status"] = "fail"
        receipt["sandboxes_stopped"] = stopped
        helper_stopped = 0
        for helper in browser_helpers:
            try:
                sdk_sandbox.kill(sandbox_id=helper.sandbox_id, api_key=api_key)
                helper_stopped += 1
            except Exception as exc:
                receipt.setdefault("cleanup_errors", []).append(type(exc).__name__)
                receipt["status"] = "fail"
        receipt["browser_helpers_stopped"] = helper_stopped
        receipt["all_sandboxes_stopped"] = stopped == len(sandboxes) and helper_stopped == len(browser_helpers)
        (args.output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
