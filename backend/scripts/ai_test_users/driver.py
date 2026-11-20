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

Signup, gift card, credits, report-issue and account-deletion operations are
scripted the same way (no model sees them). Credentials arrive only in the body of the `login_*`, `signup*` and
`delete_account*` operations, are typed
into the login form and never written to disk or logged. Screenshots of pages
with visible password/OTP fields are masked by the runtime.
"""

from __future__ import annotations

import asyncio
import json
import re
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
LIFECYCLE_OPERATIONS = {
    "signup", "signup_code", "redeem_gift_card", "credits", "report_issue", "delete_account", "delete_account_code",
    "ensure_signed_in",
}
SECRET_OPERATIONS = {
    "login_password", "login_otp", "signup", "signup_code", "delete_account", "delete_account_code", "ensure_signed_in",
}
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
        try:
            await password.wait_for(state="visible", timeout=20000)
        except rt_errors():
            error = page.get_by_test_id("error-message")
            if await error.count() and await error.first.is_visible():
                return {"state": "error", "error_text": (await error.first.inner_text())[:300]}
            raise
        await page.wait_for_function(
            "() => Boolean(sessionStorage.getItem('openmates_email_salt') || localStorage.getItem('openmates_email_salt'))",
            timeout=15000,
        )
        await password.fill(body["password"], timeout=10000)
        await page.get_by_test_id("login-submit-button").click(timeout=10000)
        state = await self.login_state(25)
        out = {"state": state}
        if state == "error":
            out["error_text"] = (await self.page.get_by_test_id("error-message").first.inner_text())[:300]
        return out

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

    # --- Scripted account lifecycle (no model sees these values) -------------
    # Selectors follow signup-skip-2fa-flow.spec.ts, prod-smoke-signup-giftcard-chat.spec.ts
    # and report-issue-flow.spec.ts.
    async def set_toggle(self, input_id: str, wanted: bool) -> None:
        box = self.page.locator(input_id)
        if await box.is_checked() != wanted:
            await self.page.locator(f"label.toggle[for='{input_id.lstrip('#')}'], label.toggle:has({input_id})").first.click(timeout=5000)

    async def signup(self, body: dict) -> dict:
        page = self.page
        if body.get("gift_card_code"):
            # The deep link stashes the code; signup completion redeems it (as the prod smoke spec).
            await page.goto(body["url"].rstrip("/") + "/#gift-card=" + body["gift_card_code"], wait_until="domcontentloaded", timeout=30000)
            await page.reload(wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_load_state("load", timeout=30000)
        await page.get_by_test_id("header-login-signup-btn").click(timeout=20000)
        tabs = page.get_by_test_id("login-tabs")
        await tabs.wait_for(state="visible", timeout=10000)
        await tabs.get_by_test_id("tab-signup").click(timeout=10000)  # test id: personas use other UI languages
        email_input = page.locator('input[type="email"][autocomplete="email"]')
        await email_input.fill(body["email"], timeout=15000)
        await page.locator('input[autocomplete="username"]').fill(body["username"], timeout=10000)
        if body.get("invite_code"):
            invite = page.locator('[data-testid="invite-code-input"], input[autocomplete="off"][name="invite_code"], #invite-code').first
            if await invite.count() and await invite.is_visible():
                await invite.fill(body["invite_code"], timeout=5000)
        await self.set_toggle("#terms-agreed-toggle", True)
        await self.set_toggle("#privacy-agreed-toggle", True)
        # The button stays disabled until the email and username checks answer, which is slower under load.
        create = page.locator("button.signup-button").first
        await page.wait_for_function("(el) => el && !el.disabled", arg=await create.element_handle(timeout=10000), timeout=45000)
        await create.click(timeout=10000)
        # The email-code field, not the "Open mail app" link: personas use other UI languages.
        await page.locator('input[inputmode="numeric"][maxlength="6"]').wait_for(state="visible", timeout=30000)
        return {"state": "awaiting_code"}

    async def signup_code(self, body: dict) -> dict:
        page = self.page
        await page.locator('input[inputmode="numeric"][maxlength="6"]').fill(body["code"], timeout=15000)
        option = page.locator("#signup-password-option")
        await option.wait_for(state="visible", timeout=20000)
        await option.click(timeout=5000)
        inputs = page.locator('input[autocomplete="new-password"]')
        await inputs.nth(1).wait_for(state="visible", timeout=10000)
        await inputs.nth(0).fill(body["password"], timeout=5000)
        await inputs.nth(1).fill(body["password"], timeout=5000)
        await page.locator("#signup-password-continue").click(timeout=5000)
        editor = page.get_by_test_id("message-editor")
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            if await editor.is_visible():
                return {"state": "auth"}
            skip = page.get_by_role("button", name=re.compile(r"^\s*(skip|later|not now|überspringen)", re.I))
            if await skip.count() and await skip.first.is_visible():
                try:
                    await skip.first.click(timeout=3000)
                except rt_errors():  # the prompt closed by itself between the check and the click
                    pass
            await asyncio.sleep(1)
        return {"state": "timeout"}

    async def open_settings_menu(self) -> None:
        menu = self.page.locator('[data-testid="settings-menu"].visible')
        if not await menu.count():
            await self.page.locator("#settings-menu-toggle").click(timeout=10000)
        await menu.wait_for(state="visible", timeout=10000)

    async def close_settings_menu(self) -> None:
        close = self.page.locator("#settings-menu-toggle .close-icon-container.visible").first
        if await close.count():
            await close.click(timeout=3000)

    async def settings_main_page(self) -> None:
        """Step back from a settings sub-page (the app may open one by itself, e.g. Gift Cards)."""
        back = self.page.locator('[data-testid="settings-menu"].visible [data-testid="settings-back-button"]').first
        for _ in range(5):
            if not (await back.count() and await back.is_visible()):
                return
            if await back.get_attribute("aria-disabled") == "true":  # already on the main page
                return
            # DOM click: the header animates and toasts can overlap it, which stalls a pointer click.
            await back.evaluate("button => button.click()")
            await asyncio.sleep(0.8)

    async def credits(self, body: dict | None = None) -> dict:
        """The balance as the settings header shows it (digits only; None when not readable)."""
        await self.open_settings_menu()
        await self.settings_main_page()
        amount = self.page.get_by_test_id("credits-amount").first
        try:
            await amount.wait_for(state="visible", timeout=8000)
            text = (await amount.inner_text()).strip()
        except rt_errors():
            text = ""
        await self.close_settings_menu()
        digits = re.sub(r"[^\d]", "", text)
        return {"credits": int(digits) if digits else None, "text": text[:60]}

    async def redeem_gift_card(self, body: dict) -> dict:
        """The code redeems itself when signup completes; wait until credits show up."""
        deadline = time.monotonic() + float(body.get("timeout", 90))
        shown = {"credits": None, "text": ""}
        while time.monotonic() < deadline:
            shown = await self.credits()
            if shown["credits"]:
                return {**shown, "redeemed": True}
            await asyncio.sleep(3)
        return {**shown, "redeemed": False}

    async def ensure_signed_in(self, body: dict) -> dict:
        """Sign back in with the password when the persona's own actions ended the session.

        Without "Stay logged in" a page reload signs the user out by design, and personas reload pages.
        """
        if await self.page.locator('[data-authenticated="true"]').count():
            return {"state": "auth", "relogin": False}
        await self.page.goto(body["url"], wait_until="domcontentloaded", timeout=30000)
        await self.page.keyboard.press("Escape")  # close a login modal or drawer the persona left open
        if await self.page.locator('[data-authenticated="true"]').count():
            return {"state": "auth", "relogin": False}
        login = await self.login_password(body)
        return {**login, "relogin": True}

    async def report_issue(self, body: dict) -> dict:
        page = self.page
        await self.open_settings_menu()
        await self.settings_main_page()  # the menu reopens on the last sub-page (e.g. the previous report)
        item = page.locator('[data-testid="settings-menu"].visible').get_by_role(
            "menuitem", name=re.compile(r"report.*issue|issue.*report|problem.*melden", re.I)).first
        await item.click(timeout=8000)
        form = page.get_by_test_id("report-issue-form")
        await form.wait_for(state="visible", timeout=15000)
        await page.get_by_test_id("report-issue-title").fill(f"{body['title']}\n\n{body['description']}"[:4000], timeout=10000)
        files = [str(f) for f in body.get("files", [])][:5]
        uploader = page.get_by_test_id("screenshot-file-input")
        attached = 0
        if files:
            try:
                await uploader.set_input_files(files, timeout=10000)
                attached = len(files)
            except rt_errors():
                await uploader.set_input_files(files[0], timeout=10000)  # single-file input: keep the finding's own shot
                attached = 1
            await page.get_by_test_id("screenshot-preview").first.wait_for(state="visible", timeout=10000)
            await asyncio.sleep(1)
        await page.get_by_test_id("report-issue-submit").click(timeout=10000)
        confirmation = page.get_by_test_id("report-issue-confirmation")
        await confirmation.wait_for(state="visible", timeout=45000)
        issue_id = (await confirmation.get_by_test_id("report-issue-id-value").inner_text(timeout=10000)).strip()
        await self.close_settings_menu()
        return {"short_issue_id": issue_id, "screenshots": attached}

    async def open_delete_account(self, container) -> None:
        """Settings > Account > Delete through the menu; reuses a menu the run left open and falls
        back to the app's own #settings/account/delete link when the menu sits on a sub-page."""
        page = self.page
        menu = page.locator('[data-testid="settings-menu"].visible')
        try:
            if not await menu.count():
                await page.get_by_test_id("profile-container").click(timeout=10000)
            await menu.wait_for(state="visible", timeout=10000)
            await self.settings_main_page()
            await page.get_by_role("menuitem", name=re.compile("account", re.I)).click(timeout=6000)
            await page.get_by_role("menuitem", name=re.compile("delete", re.I)).click(timeout=6000)
            await container.wait_for(state="visible", timeout=10000)
        except Exception as exc:  # Playwright is imported lazily in the sandbox; only its timeout falls back
            if type(exc).__name__ != "TimeoutError":
                raise
            origin = re.match(r"^https?://[^/]+", page.url).group(0)
            await page.goto(origin + "/#settings/account/delete", wait_until="domcontentloaded", timeout=30000)
            await page.reload(wait_until="domcontentloaded", timeout=30000)

    async def delete_account(self, body: dict) -> dict:
        page = self.page
        container = page.get_by_test_id("delete-account-container")
        await self.open_delete_account(container)
        await container.wait_for(state="visible", timeout=15000)
        box = container.locator('input[type="checkbox"]').first
        await box.wait_for(state="attached", timeout=10000)
        if not await box.is_checked():
            await container.locator("label.toggle").first.click(timeout=5000)
        await container.get_by_test_id("delete-button").click(timeout=10000)
        modal = page.get_by_test_id("auth-modal")
        await modal.wait_for(state="visible", timeout=15000)
        password = modal.locator(".auth-password")
        if await password.is_visible():
            await password.get_by_test_id("password-input").fill(body["password"], timeout=10000)
            await password.get_by_test_id("auth-btn").click(timeout=10000)
        otp = modal.get_by_test_id("auth-email-otp")
        await otp.wait_for(state="visible", timeout=20000)
        if await otp.get_by_test_id("auth-btn").count() and not await otp.locator('input[inputmode="numeric"], input.tfa-input').first.is_visible():
            await otp.get_by_test_id("auth-btn").click(timeout=10000)
        await otp.locator('input[inputmode="numeric"], input.tfa-input').first.wait_for(state="visible", timeout=30000)
        return {"state": "awaiting_code"}

    async def delete_account_code(self, body: dict) -> dict:
        page = self.page
        otp = page.get_by_test_id("auth-modal").get_by_test_id("auth-email-otp")
        await otp.locator('input[inputmode="numeric"], input.tfa-input').first.fill(body["code"], timeout=10000)
        await page.get_by_role("button", name=re.compile("login", re.I)).first.wait_for(state="visible", timeout=45000)
        return {"state": "deleted"}

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
        if op in LIFECYCLE_OPERATIONS:
            return await getattr(self, op)(body)
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
                result["detail"] = redact(result["detail"], locals().get("body"))
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


def redact(detail: str, body) -> str:
    """Error detail of a credential operation with every submitted value removed (selectors stay)."""
    for value in (body or {}).values() if isinstance(body, dict) else ():
        if isinstance(value, str) and len(value) >= 4 and value != body.get("operation"):
            detail = detail.replace(value, "<redacted>")
            if "@" in value:
                detail = detail.replace(value.split("@")[0], "<redacted>")
    return detail


def body_is_login(body) -> bool:
    return isinstance(body, dict) and str(body.get("operation", "")) in SECRET_OPERATIONS


if __name__ == "__main__":
    asyncio.run(serve())
