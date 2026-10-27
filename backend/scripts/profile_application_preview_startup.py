#!/usr/bin/env python3
# contract-test-file: tooling
"""Profile real E2B preview startup and bounded experimental fast paths.

Runs in the API container with Vault-backed provider credentials. Records only
phase durations and sanitized transport timings; no request bodies or headers.
Uses one or two disposable sandboxes and attempts cleanup, including paused VMs.
The experimental dependency bypass is gated to exact prepared dependencies.
It does not change the deployed provider, runtime configuration, or user chats.
Usage: python profile_application_preview_startup.py --execute --fixture FILE
       --browser-check FILE --output-dir /tmp/preview-performance
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
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import e2b
import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from application_preview_interaction_probe import RemoteInteractionProbe, sandbox_resources


EXPECTED = {"svelte": "5.55.7", "vite": "5.4.21", "@sveltejs/vite-plugin-svelte": "4.0.4", "typescript": "5.9.2"}


async def api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--browser-check", type=Path, help="Deprecated; trusted built-in probe is always used")
    parser.add_argument("--interaction-scenario", choices=("recipe", "todo"), default="recipe")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batched-only", action="store_true")
    parser.add_argument("--provider-source", type=Path, default=Path("/app/backend/shared/providers/e2b_application_preview.py"))
    templates = parser.add_mutually_exclusive_group()
    templates.add_argument("--template", help="Force base template; clear inherited warm template")
    templates.add_argument("--warm-template", help="Force eligible warm template and verify SDK-selected ID")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for disposable real-provider sandboxes")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    fixture = json.loads(args.fixture.read_text())
    files = fixture["embeds"]["11111111-1111-4111-8111-111111111111"]["files"]
    assert {file["path"] for file in files} == {"package.json", "src/App.svelte"}
    manifest = json.loads(next(file["content"] for file in files if file["path"] == "package.json"))
    dependencies = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
    assert dependencies == {name: f"^{version}" for name, version in EXPECTED.items()}
    key = asyncio.run(api_key())
    sdk = e2b.Sandbox
    created: dict[str, Any] = {}
    receipt: dict[str, Any] = {
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "variants": [],
    }
    original_send = httpx.Client.send
    lock = threading.Lock()
    current: dict[str, Any] = {}
    phase = "setup"

    def traced_send(client: Any, request: Any, **kwargs: Any) -> Any:
        began = time.monotonic()
        request_phase = phase
        timings: dict[str, float] = {}
        starts: dict[str, float] = {}
        previous_trace = request.extensions.get("trace")

        def trace(name: str, info: Any) -> None:
            if name.endswith(".started"):
                starts[name[:-8]] = time.monotonic()
            elif name.endswith(".complete"):
                label = name[:-9]
                if label in starts:
                    timings[label] = round(time.monotonic() - starts.pop(label), 4)
            if previous_trace:
                previous_trace(name, info)

        request.extensions["trace"] = trace
        try:
            response = original_send(client, request, **kwargs)
            status = response.status_code
            return response
        finally:
            path = request.url.path
            route = "control" if path.startswith("/sandboxes") else (
                "process" if "process" in path.lower() else "files" if "files" in path.lower() else "other"
            )
            with lock:
                current.setdefault("http", []).append({
                    "phase": request_phase, "route": route, "method": request.method,
                    "until_headers_seconds": round(time.monotonic() - began, 4),
                    "status": locals().get("status"), "transport_seconds": timings,
                })

    httpx.Client.send = traced_send
    try:
        variants = ["batched_prepared_setup"] if args.batched_only else ["current_provider", "prepared_dependencies_fast_poll"]
        for name in variants:
            fast = name != "current_provider"
            batched = name == "batched_prepared_setup"
            out = args.output_dir / name
            out.mkdir()
            current = {"name": name, "events": [], "http": [], "readiness_requests": [], "sleeps": []}
            receipt["variants"].append(current)
            spec = importlib.util.spec_from_file_location(f"preview_profile_{name}", str(args.provider_source))
            assert spec and spec.loader
            provider = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = provider
            spec.loader.exec_module(provider)
            if args.template:
                os.environ[provider.APPLICATION_PREVIEW_TEMPLATE_ENV] = args.template
                os.environ.pop(provider.APPLICATION_PREVIEW_WARM_TEMPLATE_ENV, None)
            elif args.warm_template:
                os.environ[provider.APPLICATION_PREVIEW_WARM_TEMPLATE_ENV] = args.warm_template
            receipt["provider_sha256"] = hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest()
            started = time.monotonic()

            def event(label: str) -> float:
                elapsed = round(time.monotonic() - started, 4)
                current["events"].append({"phase": label, "seconds": elapsed})
                print(json.dumps({"variant": name, "phase": label, "seconds": elapsed}), flush=True)
                return elapsed

            class Commands:
                def __init__(self, commands: Any) -> None:
                    self.commands = commands

                def run(self, command: str, **kwargs: Any) -> Any:
                    nonlocal phase
                    phase = "batched_setup" if "OPENMATES_BATCHED_SETUP" in command else "capture" if "chromium.launch" in command else (
                        "browser_setup" if "chromium.executablePath" in command else
                        "server_launch" if kwargs.get("background") else "dependencies"
                    )
                    label = phase
                    event(label + "_started")
                    result = self.commands.run(command, **kwargs)
                    event(label + "_finished")
                    return result

            class Proxy:
                def __init__(self, sandbox: Any) -> None:
                    self.sandbox = sandbox
                    self.commands = Commands(sandbox.commands)

                def __getattr__(self, attr: str) -> Any:
                    return getattr(self.sandbox, attr)

            class TrackedSandbox:
                @staticmethod
                def create(**kwargs: Any) -> Any:
                    nonlocal phase
                    phase = "sandbox_create"
                    current["actual_sdk_template"] = kwargs.get("template")
                    expected_template = args.warm_template or args.template
                    if expected_template and kwargs.get("template") != expected_template:
                        raise ValueError("Requested template was not selected by provider")
                    kwargs["timeout"] = 600
                    sandbox = sdk.create(**kwargs)
                    created[sandbox.sandbox_id] = sandbox
                    event("sandbox_created")
                    return Proxy(sandbox)

                kill = staticmethod(sdk.kill)

            for function_name, label in (("_write_files", "file_upload"), ("_write_vite_allowed_hosts_config", "vite_config")):
                original = getattr(provider, function_name)

                def wrap(*pos: Any, _original: Any = original, _label: str = label, **kw: Any) -> Any:
                    nonlocal phase
                    phase = _label
                    event(_label + "_started")
                    result = _original(*pos, **kw)
                    event(_label + "_finished")
                    return result

                setattr(provider, function_name, wrap)

            original_wait = provider._wait_for_preview_ready
            original_fetch = provider._fetch_preview_status
            persistent = httpx.Client(timeout=5, follow_redirects=True)

            def fetch(url: str) -> int:
                began = time.monotonic()
                status = persistent.get(url).status_code if fast else original_fetch(url)
                current["readiness_requests"].append({"seconds": round(time.monotonic() - began, 4), "status": status})
                return status

            def sleep(seconds: float) -> None:
                current["sleeps"].append(seconds)
                time.sleep(seconds)

            def wait(url: str, **kw: Any) -> None:
                nonlocal phase
                phase = "readiness"
                event("readiness_started")
                original_wait(url, fetch_status=fetch, sleep=sleep,
                              interval_seconds=0.05 if fast else 1.5, **kw)
                event("readiness_finished")

            provider._wait_for_preview_ready = wait
            if fast:
                guard = "const fs=require('fs'); const expected=" + json.dumps(EXPECTED) + "; for(const [name,version] of Object.entries(expected)){ if(JSON.parse(fs.readFileSync('node_modules/'+name+'/package.json','utf8')).version!==version) throw new Error('Prepared dependency mismatch'); }"
                provider._dependency_commands = lambda _files: ["node -e " + shlex.quote(guard)]
            if batched:
                def batched_start(**kwargs: Any) -> Any:
                    nonlocal phase
                    plan = provider.plan_application_preview_startup(files=kwargs["files"], entrypoints=kwargs["entrypoints"])
                    sandbox = TrackedSandbox.create(
                        template=os.environ[provider.APPLICATION_PREVIEW_TEMPLATE_ENV], api_key=key,
                        envs={"PLAYWRIGHT_BROWSERS_PATH": f"{provider.APPLICATION_CAPTURE_DIRECTORY}/browsers"},
                        secure=True, network={"allow_public_traffic": True}, allow_internet_access=True,
                    )
                    url = provider._sandbox_host(sandbox, 5173)
                    allowed_hosts = provider._vite_allowed_hosts({"frontend": url})
                    payload = [{"path": file.path, "data": file.content} for file in plan.files]

                    class Collector:
                        def write_files(self, entries: list[dict[str, str]]) -> None:
                            payload.extend(entries)

                    config = provider._write_vite_allowed_hosts_config(SimpleNamespace(files=Collector()), plan.files, allowed_hosts)
                    command = provider._with_vite_preview_settings(str(plan.start_commands[0]["command"]), allowed_hosts, config)
                    sandbox.files.write("/tmp/openmates-profile-payload.json", json.dumps(payload))
                    bootstrap = r"""
// OPENMATES_BATCHED_SETUP
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const began = performance.now();
const files = JSON.parse(fs.readFileSync('/tmp/openmates-profile-payload.json', 'utf8'));
for (const file of files) {
  fs.mkdirSync(path.dirname(file.path), { recursive: true });
  fs.writeFileSync(file.path, file.data);
}
const written = performance.now();
const expected = __EXPECTED__;
for (const [name, version] of Object.entries(expected)) {
  if (JSON.parse(fs.readFileSync('node_modules/' + name + '/package.json', 'utf8')).version !== version)
    throw new Error('Prepared dependency mismatch');
}
const checked = performance.now();
const log = fs.openSync('/tmp/openmates-profile-vite.log', 'a');
const child = spawn('bash', ['-lc', __COMMAND__], { detached: true, stdio: ['ignore', log, log] });
child.unref();
(async () => {
  let successes = 0;
  const local = [];
  const deadline = performance.now() + 15000;
  while (successes < 2 && performance.now() < deadline) {
    const at = performance.now();
    try {
      const response = await fetch('http://127.0.0.1:5173/');
      await response.text();
      local.push({ ms: performance.now() - at, status: response.status });
      successes = response.status === 200 ? successes + 1 : 0;
    } catch (_) { successes = 0; }
    if (successes < 2) await new Promise(resolve => setTimeout(resolve, 50));
  }
  if (successes < 2) throw new Error('Local Vite readiness failed');
  console.log(JSON.stringify({ write_ms: written-began, dependency_check_ms: checked-written,
    server_ready_ms: performance.now()-checked, total_ms: performance.now()-began, local }));
})().catch(error => { console.error(error.message); process.exitCode=1; });
""".replace("__EXPECTED__", json.dumps(EXPECTED)).replace("__COMMAND__", json.dumps(command))
                    result = sandbox.commands.run("node - <<'NODE'\n" + bootstrap + "\nNODE", timeout=30)
                    current["inside_sandbox"] = json.loads(result.stdout.strip())
                    current["readiness_contract"] = "two local HTTP 200 responses, then one public HTTP success"
                    phase = "readiness"
                    deadline = time.monotonic() + 15
                    while fetch(url) != 200:
                        if time.monotonic() > deadline:
                            raise TimeoutError("Public readiness failed")
                        time.sleep(0.05)
                    runtime = provider.ApplicationPreviewRuntime(sandbox_id=sandbox.sandbox_id, upstream_base_url=url, ports={"frontend": 5173})
                    kwargs["on_runtime_ready"](runtime)
                    image = provider._sandbox_screenshot_bytes(sandbox, 5173)
                    return provider.ApplicationPreviewRuntime(
                        sandbox_id=sandbox.sandbox_id, upstream_base_url=url, ports={"frontend": 5173},
                        latest_screenshot_bytes=image,
                    )

                provider.start_application_preview_in_e2b = batched_start
            interaction_probe: RemoteInteractionProbe | None = None

            def ready(runtime: Any) -> None:
                nonlocal interaction_probe
                current["http_ready_seconds"] = event("http_ready")
                interaction_probe = RemoteInteractionProbe(
                    sandbox=created[runtime.sandbox_id], url=runtime.upstream_base_url,
                    capture_directory=provider.APPLICATION_CAPTURE_DIRECTORY,
                    scenario=args.interaction_scenario, output_dir=out, event=event,
                )
                interaction_probe.start()

            e2b.Sandbox = TrackedSandbox
            try:
                runtime = provider.start_application_preview_in_e2b(
                    files=[provider.ApplicationPreviewFile(path=file["path"], content=file["content"]) for file in files],
                    entrypoints=[provider.ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
                    api_key=key,
                    on_runtime_ready=ready,
                )
                current["screenshot_seconds"] = event("first_screenshot")
                assert runtime.latest_screenshot_bytes
                (out / "preview.png").write_bytes(runtime.latest_screenshot_bytes)
                phase = "interactive_verification"
                sandbox = created[runtime.sandbox_id]
                if interaction_probe is None:
                    raise AssertionError("Provider did not call on_runtime_ready")
                current["interaction"] = interaction_probe.finish()
                current["sandbox_resources"] = sandbox_resources(sandbox)
                assert current["interaction"].get("interactive")
                current["interactive"] = True
                current["interactive_verified_seconds"] = current["interaction"]["interaction_acknowledged_seconds"]
                if fast and not batched:
                    phase = "pause"
                    began = time.monotonic()
                    sandbox.pause(mode="full")
                    current["pause_seconds"] = round(time.monotonic() - began, 4)
                    phase = "resume"
                    began = time.monotonic()
                    sandbox.connect(timeout=600)
                    current["resume_connect_seconds"] = round(time.monotonic() - began, 4)
                    original_wait(runtime.upstream_base_url, fetch_status=fetch, interval_seconds=0.05)
                    current["resume_http_ready_seconds"] = round(time.monotonic() - began, 4)
                current["status"] = "pass"
            except Exception as exc:
                current.update(status="fail", error_type=type(exc).__name__, failed_phase=phase)
                raise
            finally:
                e2b.Sandbox = sdk
                persistent.close()
                if interaction_probe is not None and "interaction" not in current:
                    current["interaction"] = interaction_probe.finish()
                (out / "receipt.json").write_text(json.dumps(current, indent=2) + "\n")
                for sandbox_id in list(created):
                    sdk.kill(sandbox_id=sandbox_id, api_key=key)
                    del created[sandbox_id]
            print(json.dumps({k: v for k, v in current.items() if k not in {"http", "events", "readiness_requests"}}), flush=True)
    finally:
        e2b.Sandbox = sdk
        httpx.Client.send = original_send
        failures = 0
        for sandbox_id in list(created):
            try:
                sdk.kill(sandbox_id=sandbox_id, api_key=key)
                del created[sandbox_id]
            except Exception:
                failures += 1
        receipt["cleanup_failures"] = failures
        receipt["all_sandboxes_stopped"] = not created
        (args.output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
