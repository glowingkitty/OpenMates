"""Account lifecycle stages of an AI test user session: signup, gift card, reports, deletion.

Each stage records `{"status", "seconds", "error"}` in `result.json` and never raises, so a failed stage cannot
skip the account deletion. The driver does all browser work; the mailbox code goes through
the job's inbox (`inbox.make_inbox`) straight into the driver, and nothing here logs the address, password or codes.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from typing import Any, Awaitable, Callable

import httpx

from backend.shared.providers.browser_models import BrowserModelError
from backend.shared.providers.e2b_browser import BrowserUnavailable
from inbox import InboxError, make_inbox
from models import fit_for_jev
from reports import report_text, screenshot_steps, select_reports

SANDBOX_HOME = "/home/user/.ai-tester"
MAX_SCREENSHOT_BYTES = 2_000_000
STAGE_ERRORS = (BrowserUnavailable, BrowserModelError, InboxError, KeyError, ValueError, OSError, httpx.HTTPError)


async def run_stage(result: dict[str, Any], key: str, body: Callable[[], Awaitable[Any]], session: Any = None) -> bool:
    started = time.monotonic()
    try:
        await body()
    except STAGE_ERRORS as exc:
        result[key] = {"status": "failed", "seconds": round(time.monotonic() - started, 1),
                       "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        if session is not None:
            result[key]["screenshot"] = await failure_screenshot(session, key)
        return False
    result[key] = {"status": "ok", "seconds": round(time.monotonic() - started, 1), "error": None}
    return True


async def failure_screenshot(session: Any, key: str) -> str | None:
    """What the page showed when a scripted stage failed; stays in the private run folder on the dev host."""
    try:
        image = (await session.rpc({"operation": "frame"}, timeout=30)).get("image")
    except BrowserUnavailable:
        return None
    if not image:
        return None
    name = f"stage-{key}-failed.jpg"
    (session.out / name).write_bytes(base64.b64decode(image))
    return name


async def signup(session: Any) -> None:
    spec = session.job["signup"]
    inbox = make_inbox(spec)
    session.inbox = inbox
    requested = time.time()
    await session.rpc({
        "operation": "signup", "url": session.job["app_url"], "email": spec["email"], "username": spec["username"],
        "gift_card_code": spec.get("gift_card_code"), "invite_code": spec.get("invite_code"),
    }, timeout=120)
    code = await inbox.wait_for_code(requested)
    session.account_created = True  # the account exists once the code is accepted, whatever happens next
    state = (await session.rpc({"operation": "signup_code", "code": code, "password": spec["password"]}, timeout=200))["state"]
    if state != "auth":
        raise BrowserUnavailable(f"Signup did not reach the app (state {state}).")


async def gift_card(session: Any) -> None:
    if not session.job["signup"].get("gift_card_code"):
        session.result["credits_start"] = (await session.rpc({"operation": "credits"}, timeout=60))["credits"]
        return
    shown = await session.rpc({"operation": "redeem_gift_card", "timeout": 90}, timeout=240)
    session.result["credits_start"] = shown.get("credits")
    if not shown.get("redeemed"):
        raise BrowserUnavailable("The gift card did not add credits.")


def jpeg_for_upload(image_b64: str) -> bytes:
    data = base64.b64decode(image_b64)
    return data if len(data) <= MAX_SCREENSHOT_BYTES else base64.b64decode(fit_for_jev(image_b64))


async def ensure_signed_in(session: Any) -> None:
    """Personas may end their own session (a reload without "Stay logged in"); sign in again for the scripted stages."""
    spec = session.job["signup"]
    state = await session.rpc({"operation": "ensure_signed_in", "url": session.job["app_url"], "email": spec["email"],
                               "password": spec["password"]}, timeout=150)
    if state.get("relogin"):
        session.result["relogins"] = session.result.get("relogins", 0) + 1
    if state.get("state") != "auth":
        raise BrowserUnavailable(f"Could not sign the test account back in (state {state.get('state')}).")


async def submit_reports(session: Any) -> None:
    settings = session.job["report"]
    result = session.result
    result["reports"] = []
    if not settings.get("enabled"):
        return
    groups = select_reports(result["findings"], settings.get("skip_titles", []), int(settings.get("max_reports", 3)))
    if groups:
        await run_stage(result, "relogin", lambda: ensure_signed_in(session), session)
    for number, group in enumerate(groups):
        entry: dict[str, Any] = {"finding_ids": [f["id"] for f in group], "short_issue_id": None, "screenshots": 0, "status": "failed"}
        result["reports"].append(entry)
        try:
            steps = screenshot_steps(group[0].get("step"), sorted(session.screenshots), int(settings.get("max_screenshots", 5)))
            paths = []
            for step in steps:
                path = f"{SANDBOX_HOME}/report-{number}-{step:03d}.jpg"
                await asyncio.to_thread(session.sandbox.files.write, path, jpeg_for_upload(session.screenshots[step]))
                paths.append(path)
            title, description = report_text(group, session.persona, session.job["target"],
                                             str(session.job.get("video_url") or ""))
            sent = await session.rpc(
                {"operation": "report_issue", "title": title, "description": description, "files": paths}, timeout=120)
            entry.update(short_issue_id=sent["short_issue_id"], screenshots=sent.get("screenshots", 0), status="submitted")
        except STAGE_ERRORS as exc:
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"


async def delete_account(session: Any) -> None:
    spec = session.job["signup"]
    await ensure_signed_in(session)
    requested = time.time()
    await session.rpc({"operation": "delete_account", "password": spec["password"]}, timeout=120)
    code = await session.inbox.wait_for_code(requested, purpose="delete_account")
    state = (await session.rpc({"operation": "delete_account_code", "code": code}, timeout=120))["state"]
    if state != "deleted":
        raise BrowserUnavailable(f"Deletion did not complete (state {state}).")


async def delete_stage(session: Any) -> None:
    """Delete the throwaway account. `deletion.status` is "failed" when it must be retried by the orchestrator."""
    if not session.job.get("delete_account", True) or not session.account_created:
        session.result["deletion"] = {"status": "skipped", "error": None}
        return
    if not getattr(session.inbox, "reads_deletion_code", True):
        # The web deletion code exists only in the email; the orchestrator deletes the account instead.
        session.result["deletion"] = {"status": "host", "error": None}
        return
    ok = await run_stage(session.result, "deletion", lambda: delete_account(session), session)
    stage = session.result["deletion"]
    stage["status"] = "deleted" if ok else "failed"


ABSENT_LOGIN_TEXT = re.compile(r"(no account|does not exist|doesn't exist|not found|couldn't find|could not find|unknown (user|account|email))", re.I)


def validate_job(job: dict[str, Any]) -> str:
    """Return the job mode ("run" or "delete_only"); raise ValueError for a job the worker cannot run."""
    mode = job.get("mode", "run")
    if mode not in ("run", "delete_only"):
        raise ValueError(f"Unknown job mode {mode!r}.")
    if mode == "delete_only":
        spec = job.get("signup") or {}
        if not spec.get("email") or not spec.get("password"):
            raise ValueError("delete_only needs signup.email and signup.password.")
        if job.get("persona") is not None:
            raise ValueError("delete_only takes no persona.")
    elif not job.get("persona"):
        raise ValueError("A run job needs a persona.")
    return mode


async def login_and_delete(session: Any) -> str:
    """Log in with the saved password and delete the account. Returns "deleted" or "absent"; raises otherwise."""
    spec = session.job["signup"]
    session.inbox = make_inbox(spec)
    login = await session.rpc({"operation": "login_password", "email": spec["email"], "password": spec["password"]}, timeout=120)
    if login["state"] == "error":
        if ABSENT_LOGIN_TEXT.search(login.get("error_text") or ""):
            return "absent"
        raise BrowserUnavailable(f"Login failed: {(login.get('error_text') or '')[:120]}")
    if login["state"] != "auth":
        raise BrowserUnavailable(f"Login did not reach the app (state {login['state']}).")
    await delete_account(session)
    return "deleted"
