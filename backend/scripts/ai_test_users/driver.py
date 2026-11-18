"""AI test-user browser driver. Runs ONLY inside a disposable E2B sandbox.

Dev test tooling, never a product surface. The session worker
(`session.py`, api container) uploads this file next to a copy of the Browse
runtime (`backend/shared/providers/web_browse_runtime.py`, saved as
`browse_runtime.py`) and talks to it over the sandbox's authenticated port.

It reuses the runtime's page snapshot, observation format, batched step
executor and settle logic, but launches its own Chromium the way a real user
would see the OpenMates web app: WebSockets and service workers on, a phone or
laptop device profile, locale and time zone, Playwright video recording and
an optional fake microphone fed from a WAV clip. Top-level navigation is
limited to the dev web app hosts the worker allows; any other destination
(a booking link in an answer, for example) is recorded and aborted, and
popups are recorded and closed, so the judge can still check where a button
pointed.

Credentials arrive only in the body of the `login_*` operations, are typed
into the login form and never written to disk or logged. Screenshots of pages
with visible password/OTP fields are masked by the runtime.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browse_runtime as rt  # noqa: E402 - uploaded sibling copy of web_browse_runtime.py

HOME = Path("/home/user/.ai-tester")
VIDEO_DIR = HOME / "video"
VOICE_FILE = HOME / "voice.wav"
PORT = 8766
TEXT_STABLE_SECONDS = 4.0
TEXT_POLL_SECONDS = 1.0


class Driver:
    def __init__(self, playwright) -> None:
        self.playwright = playwright
        self.browser = None
        self.context = None
        self.page = None
        self.runtime = None
        self.allowed_hosts: set[str] = set()
        self.events: list[dict] = []
        self.started = time.monotonic()

    # Events the judge reads: console errors, failed API calls, blocked exits.
    def event(self, kind: str, **fields) -> None:
        if len(self.events) < 400:
            self.events.append({"t": round(time.monotonic() - self.started, 1), "kind": kind, **fields})

    def host_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        return parts.scheme == "https" and (parts.hostname or "") in self.allowed_hosts

    async def crawler_allowed(self, url: str) -> bool:
        return self.host_allowed(url)

    async def guard(self, route) -> None:
        request = route.request
        if request.is_navigation_request() and request.frame is self.page.main_frame:
            if not self.host_allowed(request.url) and not request.url.startswith(("about:", "blob:", "data:")):
                self.event("external_navigation_blocked", url=request.url[:500])
                await route.abort("blockedbyclient")
                return
        await route.continue_()

    def on_console(self, message) -> None:
        if message.type in ("error", "warning") and len(self.events) < 400:
            self.event("console_" + message.type, text=message.text[:400])

    def on_page_error(self, error) -> None:
        self.event("page_error", text=str(error)[:400])

    def on_response(self, response) -> None:
        self.runtime.on_response(response)
        if response.status >= 400 and urlsplit(response.url).hostname in self.allowed_hosts:
            path = urlsplit(response.url).path
            self.event("http_error", status=response.status, path=path[:200])

    async def on_popup(self, popup) -> None:
        self.event("popup_opened", url=popup.url[:500])
        await popup.close()

    async def launch(self, body: dict) -> dict:
        if self.context is not None:
            raise ValueError("Already launched")
        device = body["device"]
        width, height = int(device["width"]), int(device["height"])
        self.allowed_hosts = {str(h) for h in body["allowed_hosts"]}
        args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-quic"]
        if body.get("voice"):
            if not VOICE_FILE.exists():
                raise ValueError("Voice clip missing")
            args += [
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={VOICE_FILE}",
            ]
        self.browser = await self.playwright.chromium.launch(headless=True, args=args)
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        options = dict(
            viewport={"width": width, "height": height},
            device_scale_factor=float(device.get("scale", 1)),
            is_mobile=bool(device.get("mobile")),
            has_touch=bool(device.get("touch")),
            locale=body.get("locale", "en-US"),
            timezone_id=body.get("timezone", "Europe/Berlin"),
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": width, "height": height},
            accept_downloads=False,
        )
        if device.get("user_agent"):
            options["user_agent"] = device["user_agent"]
        self.context = await self.browser.new_context(**options)
        if body.get("voice"):
            for host in self.allowed_hosts:
                await self.context.grant_permissions(["microphone"], origin="https://" + host)
        self.page = await self.context.new_page()
        self.runtime = rt.BrowseRuntime(self.page, self.context, self.crawler_allowed)
        await self.context.route("**/*", self.guard)
        self.page.on("popup", lambda popup: asyncio.ensure_future(self.on_popup(popup)))
        self.page.on("request", self.runtime.on_request)
        self.page.on("requestfinished", self.runtime.on_request_done)
        self.page.on("requestfailed", self.runtime.on_request_done)
        self.page.on("response", self.on_response)
        self.page.on("framenavigated", self.runtime.on_frame_navigated)
        self.page.on("console", self.on_console)
        self.page.on("pageerror", self.on_page_error)
        await self.page.goto(body["url"], wait_until="domcontentloaded", timeout=30000)
        await self.runtime.settle()
        return {"url": self.page.url}

    # Deterministic login with the web app's own test ids (same order as the
    # Playwright helper `loginToTestAccount`). No model sees these steps.
    async def login_password(self, body: dict) -> dict:
        page = self.page
        await page.wait_for_load_state("load", timeout=30000)
        login_tab = page.get_by_test_id("tab-login")
        if not await login_tab.is_visible():
            banner = page.get_by_test_id("banner-signup-button")
            if await banner.is_visible():
                await banner.click(timeout=10000)
            else:
                await page.get_by_test_id("header-login-signup-btn").click(timeout=20000)
        await login_tab.click(timeout=15000)
        await page.get_by_test_id("login-email-input").fill(body["email"], timeout=15000)
        stay = page.locator('label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)')
        if await stay.count() and not await page.locator("#stayLoggedIn").is_checked():
            await stay.first.click(timeout=3000)
        continue_button = page.get_by_test_id("login-continue-button")
        await continue_button.click(timeout=15000)
        password = page.get_by_test_id("login-password-input")
        await password.wait_for(state="visible", timeout=20000)
        await page.wait_for_function(
            "() => Boolean(sessionStorage.getItem('openmates_email_salt') || localStorage.getItem('openmates_email_salt'))",
            timeout=15000,
        )
        await password.fill(body["password"], timeout=10000)
        await page.get_by_test_id("login-submit-button").click(timeout=10000)
        return {"state": await self.login_state(25)}

    async def login_otp(self, body: dict) -> dict:
        await self.page.get_by_test_id("login-otp-input").fill(body["code"], timeout=10000)
        submit = self.page.get_by_test_id("login-submit-button")
        try:
            if await submit.is_enabled():
                await submit.click(timeout=3000)
        except rt_errors():
            pass  # The six-digit field can submit itself and remove the button.
        return {"state": await self.login_state(30)}

    async def login_state(self, seconds: float) -> str:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if await self.page.locator('[data-authenticated="true"]').count():
                return "auth"
            if await self.page.get_by_test_id("login-otp-input").is_visible():
                otp_value = await self.page.get_by_test_id("login-otp-input").input_value()
                if not otp_value:
                    return "otp"
            error = self.page.get_by_test_id("error-message")
            if await error.count() and await error.first.is_visible():
                return "error"
            await asyncio.sleep(0.5)
        return "timeout"

    async def wait_for_text(self, body: dict) -> dict:
        """Wait until the page text stops changing (an answer finished streaming)."""
        timeout = min(float(body.get("timeout", 90)), 180)
        started = time.monotonic()
        last, stable_since, first_change = None, time.monotonic(), None
        baseline = await self.page.evaluate("() => (document.body?.innerText||'').length")
        while time.monotonic() - started < timeout:
            length = await self.page.evaluate("() => (document.body?.innerText||'').length")
            if first_change is None and length != baseline:
                first_change = time.monotonic() - started
            if length != last:
                last, stable_since = length, time.monotonic()
            elif time.monotonic() - stable_since >= TEXT_STABLE_SECONDS and first_change is not None:
                break
            await asyncio.sleep(TEXT_POLL_SECONDS)
        total = time.monotonic() - started
        settled = time.monotonic() - stable_since >= TEXT_STABLE_SECONDS
        return {
            "seconds": round(total, 1),
            "first_change_seconds": round(first_change, 1) if first_change is not None else None,
            "settled": settled and first_change is not None,
        }

    async def finish(self) -> dict:
        videos = []
        if self.context is not None:
            pages = list(self.context.pages)
            await self.context.close()
            for page in pages:
                if page.video:
                    videos.append(str(await page.video.path()))
        if self.browser is not None:
            await self.browser.close()
        return {"videos": videos}

    async def command(self, body: dict) -> dict:
        op = body.get("operation")
        if op == "ping":
            return {"ok": True}
        if op == "launch":
            return await self.launch(body)
        if self.runtime is None:
            raise ValueError("Not launched")
        if op == "login_password":
            return await self.login_password(body)
        if op == "login_otp":
            return await self.login_otp(body)
        if op == "observe":
            self.runtime.control = "ai"
            observation = await self.runtime.observe_page(True)
            observation["viewport"] = self.page.viewport_size
            return observation
        if op == "step":
            return await self.runtime.step(body)
        if op == "frame":
            return {"image": await self.runtime.screenshot()}
        if op == "wait_for_text":
            return await self.wait_for_text(body)
        if op == "events":
            events, self.events = self.events, []
            return {"events": events, "url": self.page.url}
        if op == "finish":
            return await self.finish()
        raise ValueError("Unsupported operation")


def rt_errors():
    from playwright.async_api import Error as PlaywrightError

    return PlaywrightError


async def serve() -> None:
    from playwright.async_api import async_playwright

    authorization = rt.SessionAuthorization(HOME / "config.json")
    playwright = await async_playwright().start()
    driver = Driver(playwright)
    lock = asyncio.Lock()

    async def handle(reader, writer):
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            lines = header.decode("ascii").split("\r\n")
            headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            headers = {k.strip().lower(): v.strip() for k, v in headers.items()}
            if not authorization.permits(headers.get("authorization", "")):
                raise ValueError("Unauthorized")
            size = int(headers.get("content-length", "0"))
            if not 0 < size <= 64000:
                raise ValueError("Invalid body")
            body = json.loads(await asyncio.wait_for(reader.readexactly(size), 5))
            async with lock:
                result = await driver.command(body)
            status = "200 OK"
        except Exception as exc:  # report the class only; bodies may hold credentials
            status = "409 Conflict"
            result = {"error": type(exc).__name__, "detail": str(exc)[:200] if not isinstance(exc, KeyError) else ""}
            if body_is_login(locals().get("body")):
                result["detail"] = ""
        data = json.dumps(result).encode()
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n"
            f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "0.0.0.0", PORT, limit=70000)
    async with server:
        await server.serve_forever()


def body_is_login(body) -> bool:
    return isinstance(body, dict) and str(body.get("operation", "")).startswith("login")


if __name__ == "__main__":
    asyncio.run(serve())
