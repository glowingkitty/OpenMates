#!/usr/bin/env python3
"""Check a production web app in a fresh browser; never sign in or send AI requests."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright


def validate_url(url: str) -> str:
    if not re.fullmatch(
        r"https://(?:app\.openmates\.org|open-mates-webapp-[a-z0-9-]+\.vercel\.app)/?", url
    ):
        raise ValueError("Use the production app root or its immutable Vercel deployment URL")
    return url.rstrip("/") + "/"


def verify(url: str, output: Path, expected_version: str | None = None) -> dict:
    url = validate_url(url)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"url": url, "started_at": datetime.now(timezone.utc).isoformat(),
               "expected_version": expected_version, "result": "failed", "views": []}
    # Production APIs allow the app origin, not arbitrary Vercel hostnames.
    # Before promotion, serve the real candidate's public files into this one
    # fresh browser at the production origin. No public alias or API is mocked.
    browser_url = "https://app.openmates.org/"
    receipt["browser_origin"] = browser_url
    try:
        with sync_playwright() as playwright:
            options = {"headless": True}
            if os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"):
                options["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE"]
            browser = playwright.chromium.launch(**options)
            try:
                for name, width, height in [("laptop", 1440, 1000), ("phone", 390, 844)]:
                    view = {"name": name, "errors": [], "result": "failed"}
                    receipt["views"].append(view)
                    context = browser.new_context(
                        viewport={"width": width, "height": height}, locale="en-US",
                        record_video_dir=str(output / name),
                        record_video_size={"width": width, "height": height},
                        service_workers="block",
                    )
                    if url != browser_url:
                        def candidate_file(route):
                            path = route.request.url.removeprefix(browser_url)
                            response = route.fetch(url=url + path)
                            route.fulfill(response=response)
                        context.route(browser_url + "**", candidate_file)
                    page = context.new_page()
                    page.on("pageerror", lambda error: view["errors"].append(str(error)))
                    page.on("console", lambda message: view["errors"].append(
                        message.text + " " + message.location.get("url", "").split("?")[0])
                            if message.type == "error" else None)
                    try:
                        version_response = context.request.get(url + "_app/version.json")
                        if not version_response.ok:
                            raise RuntimeError("Production version manifest is unavailable")
                        version = version_response.json()["version"]
                        view["version"] = version
                        if expected_version and version != expected_version:
                            raise RuntimeError("Served version differs from the reviewed deployment")
                        for navigate in [lambda: page.goto(browser_url, wait_until="domcontentloaded"),
                                         lambda: page.reload(wait_until="domcontentloaded")]:
                            response = navigate()
                            if response is None or not response.ok:
                                raise RuntimeError("App navigation did not return a successful response")
                            expect(page.get_by_test_id("header-login-signup-btn")).to_be_visible(timeout=30_000)
                            # Do not abort the app's initial API reads with our own reload.
                            page.wait_for_load_state("networkidle")
                        page.screenshot(path=str(output / f"{name}-app.png"))
                        page.get_by_test_id("header-login-signup-btn").click()
                        expect(page.get_by_test_id("login-tabs")).to_be_visible(timeout=10_000)
                        page.get_by_test_id("tab-login").click()
                        expect(page.locator("#login-email-input")).to_be_editable(timeout=10_000)
                        # Allow asynchronous startup failures to surface after hydration.
                        page.wait_for_timeout(1500)
                        page.screenshot(path=str(output / f"{name}-login.png"), animations="disabled")
                        after = context.request.get(url + "_app/version.json")
                        if not after.ok or after.json()["version"] != version:
                            raise RuntimeError("Deployment changed during browser verification")
                        if view["errors"]:
                            raise RuntimeError("Browser reported startup errors")
                        view["result"] = "passed"
                    except Exception as error:
                        view["failure"] = str(error)
                        page.screenshot(path=str(output / f"{name}-failure.png"))
                    finally:
                        video = page.video
                        context.close()
                        if video:
                            view["video"] = str(video.path())
            finally:
                browser.close()
        if receipt["views"] and all(view["result"] == "passed" for view in receipt["views"]):
            receipt["result"] = "passed"
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    receipt = verify(args.url, args.out, args.expected_version)
    print(f"Production browser check: {receipt['result']}; receipt: {args.out / 'receipt.json'}")
    return 0 if receipt["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
