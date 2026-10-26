#!/usr/bin/env python3
"""Live E2B-only smoke probe; prints timings/counts, never browser credentials.

Run inside the API container after selecting E2B_BROWSE_TEMPLATE. Creates one
ephemeral browser, reads public Example Domain, proves explicit pause/resume and
manual/AI exclusivity, then deletes it. This is provider proof, not CLI evidence.
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import json
import time
import uuid

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_browser import E2BBrowser, BrowserUnavailable
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.python_utils.private_inference_logging import (
    private_inference_logging,
)


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.network-and-content,web-browse.exclusive-takeover
async def test_live_browser_runtime() -> dict:
    secrets = SecretsManager()
    await secrets.initialize()
    provider = None
    report = {}

    async def created(value):
        nonlocal provider
        provider = value

    try:
        browser = E2BBrowser(await get_e2b_api_key_async(secrets))
        started = time.monotonic()
        with private_inference_logging():
            await browser.create(
                session_id=str(uuid.uuid4()),
                owner="engineering-provider-probe",
                on_created=created,
            )
            report["startup_seconds"] = round(time.monotonic() - started, 3)
            await browser.rpc(
                provider, {"operation": "navigate", "url": "https://example.com/"}
            )
            observation_started = time.monotonic()
            observed = await browser.rpc(provider, {"operation": "observe"})
            report["observation_seconds"] = round(
                time.monotonic() - observation_started, 3
            )
            assert observed["title"] == "Example Domain"
            assert observed["text"] and observed["screenshot"]
            report.update(
                observed_text_characters=len(observed["text"]),
                screenshot_base64_characters=len(observed["screenshot"]),
                cpu_count=provider["cpu_count"],
                memory_mb=provider["memory_mb"],
            )
            try:
                await browser.rpc(
                    provider, {"operation": "navigate", "url": "https://127.0.0.1/"}
                )
            except BrowserUnavailable:
                report["private_navigation_denied"] = True
            else:
                raise AssertionError("Private navigation was admitted")
            await browser.rpc(provider, {"operation": "control", "mode": "user"})
            try:
                await browser.rpc(provider, {"operation": "observe"})
            except BrowserUnavailable:
                report["manual_observation_denied"] = True
            else:
                raise AssertionError("AI observed a manually controlled browser")
            pause_started = time.monotonic()
            await browser.pause(provider)
            report["pause_seconds"] = round(time.monotonic() - pause_started, 3)
            stopped = time.time()
            info = await browser.info(provider)
            report["paused_state"] = str(getattr(info.state, "value", info.state))
            assert report["paused_state"] == "paused"
            resume_started = time.monotonic()
            await browser.resume(provider)
            report["resume_seconds"] = round(time.monotonic() - resume_started, 3)
            await browser.rpc(provider, {"operation": "control", "mode": "ai"})
            restored = await browser.rpc(provider, {"operation": "observe"})
            assert restored["title"] == "Example Domain"
            report["resumed_same_page"] = True
            report["active_supplier_rate_usd_per_second"] = str(
                Decimal(provider["cpu_count"]) * Decimal("0.000014")
                + Decimal(provider["memory_mb"]) / 1024 * Decimal("0.0000045")
            )
            report["first_pause_confirmed_at"] = stopped
            from e2b import Sandbox

            metrics = await asyncio.to_thread(
                Sandbox.get_metrics, provider["sandbox_id"], api_key=browser.api_key
            )
            report["peak_observed_memory_bytes"] = max(
                (m.mem_used for m in metrics), default=None
            )
        report["status"] = "passed"
        return report
    finally:
        if provider:
            await browser.kill(provider)
        await secrets.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for a paid E2B smoke probe")
    print(json.dumps(asyncio.run(test_live_browser_runtime())))


if __name__ == "__main__":
    main()
