#!/usr/bin/env python3
"""Measure real E2B provisioning stages, without user data or inference.

Run in the API container with --execute. Every trial creates a fresh isolated
browser and deletes it in finally. Printed results contain timings, not handles
or credentials. This qualifies the provider; it is not app/CLI acceptance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time
import uuid

from e2b import Sandbox

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_browser import E2BBrowser
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.python_utils.private_inference_logging import (
    private_inference_logging,
)


async def trial(key: str, *, paused_resume: bool = False) -> dict:
    stages = []
    provider = None
    descriptor = Sandbox.__dict__["create"]
    original_create = Sandbox.create

    def timed(name, method):
        def call(*args, **kwargs):
            started = time.monotonic()
            try:
                return method(*args, **kwargs)
            finally:
                stages.append(
                    {"stage": name, "seconds": round(time.monotonic() - started, 4)}
                )

        return call

    def create(*args, **kwargs):
        sandbox = timed("vm_create", original_create)(*args, **kwargs)
        sandbox.get_info = timed("native_info", sandbox.get_info)
        native_run, native_write = sandbox.commands.run, sandbox.files.write
        sandbox.commands.run = lambda cmd, **kw: timed(
            "mkdir" if cmd.startswith("mkdir ") else "controller_launch", native_run
        )(cmd, **kw)
        sandbox.files.write = lambda path, data, **kw: timed(
            "config_write" if Path(path).name == "config.json" else "runtime_upload",
            native_write,
        )(path, data, **kw)
        return sandbox

    async def created(value):
        nonlocal provider
        provider = value

    browser = E2BBrowser(key)
    original_rpc = browser.rpc

    async def rpc(*args, **kwargs):
        started = time.monotonic()
        outcome = {"ok": False}
        try:
            result = await original_rpc(*args, **kwargs)
            outcome["ok"] = True
            return result
        except Exception as exc:
            outcome["http_status"] = getattr(exc, "status_code", None)
            outcome["error_type"] = type(exc).__name__
            raise
        finally:
            stages.append(
                {
                    "stage": "ready_rpc",
                    "seconds": round(time.monotonic() - started, 4),
                    **outcome,
                }
            )

    browser.rpc = rpc
    Sandbox.create = staticmethod(create)
    started = time.monotonic()
    try:
        with private_inference_logging():
            await browser.create(
                session_id=str(uuid.uuid4()),
                owner="engineering-startup-d7bf",
                on_created=created,
            )
        ready_seconds = round(time.monotonic() - started, 4)
        acquisition = {}
        if paused_resume:
            with private_inference_logging():
                await browser.pause(provider)
                acquire_started = time.monotonic()
                await browser.resume(provider)
                checked = await browser.rpc(
                    provider,
                    {
                        "operation": "control",
                        "mode": "ai",
                        "check_ready": True,
                        "require_pristine": True,
                    },
                )
                assert checked.get("pristine") is True
                acquisition = {
                    "paused_blank_acquire_seconds": round(
                        time.monotonic() - acquire_started, 4
                    )
                }
        return {
            "ready_seconds": ready_seconds,
            **acquisition,
            "stages": stages,
            "status": "passed",
        }
    finally:
        Sandbox.create = descriptor
        if provider:
            with private_inference_logging():
                await browser.kill(provider)


async def main(count: int, paused_resume: bool):
    secrets = SecretsManager()
    await secrets.initialize()
    try:
        key = await get_e2b_api_key_async(secrets)
        for index in range(count):
            result = await trial(key, paused_resume=paused_resume)
            print(json.dumps({"trial": index + 1, **result}), flush=True)
    finally:
        await secrets.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--count", type=int, default=3, choices=range(1, 11))
    parser.add_argument(
        "--paused-resume",
        action="store_true",
        help="Also time acquisition of a prepared, paused blank browser",
    )
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for paid provider qualification")
    asyncio.run(main(args.count, args.paused_resume))
