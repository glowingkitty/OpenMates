#!/usr/bin/env python3
"""
scripts/_opencode_daily_meeting.py

Creates the weekday daily standup as a persisted OpenCode chat.
The chat is visible in the already-running OpenCode web server because
OpenCode stores CLI-created sessions in the same project session store.
All public URLs and recipients are read from environment variables so the
script can run unchanged across dev, staging, and private deployments.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
TMP_DIR = SCRIPT_DIR / ".tmp"
LOG_PREFIX = "[daily-meeting]"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return

    for line in env_path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _is_weekday() -> bool:
    return datetime.now().weekday() < 5


def _project_path_token(path: Path) -> str:
    encoded = base64.urlsafe_b64encode(str(path).encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _build_session_url(session_id: str) -> str | None:
    base_url = _env("OPENCODE_WEB_BASE_URL")
    if not base_url:
        return None
    path_token = _project_path_token(PROJECT_ROOT)
    return f"{base_url.rstrip('/')}/{path_token}/session/{session_id}"


def _build_prompt(today: str) -> str:
    return f"""Start the OpenMates daily standup meeting for {today}.

Load and follow the `daily-meeting` skill. Gather the meeting data inline in
this OpenCode chat, then present only the first agenda section and wait for the
user to continue. Do not call `scripts/_daily_meeting_helper.py run-meeting`.
Do not launch Claude, do not use Zellij, and do not create another chat.

Important meeting behavior:
- This is an interactive meeting, not a report dump.
- Ask for confirmation before changing Linear tasks or writing meeting state.
- When the user confirms priorities later in this same chat, save the state and
  summary exactly as the daily-meeting skill specifies.
"""


def _run_opencode_session(today: str) -> tuple[str, int, str]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    prompt_path = TMP_DIR / f"daily-meeting-opencode-{today}.md"
    prompt_path.write_text(_build_prompt(today), encoding="utf-8")

    relative_prompt_path = prompt_path.relative_to(PROJECT_ROOT)
    title = f"daily-meeting {today}"
    message = f"Read {relative_prompt_path} in full and follow all instructions precisely."
    command = [
        "opencode",
        "run",
        "--title",
        title,
        "--format",
        "json",
        "--dangerously-skip-permissions",
        message,
    ]

    run_env = os.environ.copy()
    run_env["PATH"] = (
        "/home/superdev/.local/bin:/home/superdev/.npm-global/bin:"
        + run_env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    )

    start = time.monotonic()
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=int(_env("DAILY_MEETING_OPENCODE_TIMEOUT_SECONDS") or "1800"),
        cwd=PROJECT_ROOT,
        env=run_env,
    )
    duration = int(time.monotonic() - start)

    session_id = ""
    for line in result.stdout.splitlines():
        try:
            event: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("sessionID"):
            session_id = str(event["sessionID"])
            break

    combined_output = (result.stdout + "\n" + result.stderr).strip()
    if not session_id:
        raise RuntimeError(f"OpenCode session id not found. Output:\n{combined_output[:4000]}")
    if result.returncode != 0:
        raise RuntimeError(f"OpenCode exited with {result.returncode}. Output:\n{combined_output[:4000]}")

    return session_id, duration, title


def _dispatch_email(
    *,
    recipient_email: str,
    job_name: str,
    session_id: str,
    session_url: str | None,
    duration_seconds: int,
) -> None:
    if _env("CRON_SESSION_EMAILS_DISABLED").lower() in {"true", "1", "yes"}:
        print(f"{LOG_PREFIX} Cron session emails disabled.")
        return

    internal_token = _env("INTERNAL_API_SHARED_TOKEN")
    if not internal_token:
        print(f"{LOG_PREFIX} INTERNAL_API_SHARED_TOKEN missing; skipping email notification.", file=sys.stderr)
        return

    summary_lines = ["OpenCode daily meeting chat is ready."]
    if session_url:
        summary_lines.append(f"Open: {session_url}")
    else:
        summary_lines.append("OPENCODE_WEB_BASE_URL is not configured, so no deep link was generated.")

    payload = {
        "recipient_email": recipient_email,
        "job_type": "daily-meeting",
        "job_name": job_name,
        "status": "ready",
        "session_id": session_id,
        "session_url": session_url,
        "duration_seconds": duration_seconds,
        "context_summary": "\n".join(summary_lines),
        "exit_code": 0,
    }

    api_base_url = (_env("INTERNAL_API_URL") or "http://localhost:8000").rstrip("/")
    request = urllib.request.Request(
        f"{api_base_url}/internal/dispatch-cron-session-email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Internal-Service-Token": internal_token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        print(f"{LOG_PREFIX} Email notification dispatched to configured recipient.")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:500]
        print(f"{LOG_PREFIX} Email notification failed: HTTP {error.code}: {body}", file=sys.stderr)
    except Exception as error:
        print(f"{LOG_PREFIX} Email notification failed: {error}", file=sys.stderr)


def main() -> None:
    _load_dotenv()

    weekdays_only = _env("DAILY_MEETING_WEEKDAYS_ONLY").lower() not in {"false", "0", "no"}
    if weekdays_only and not _is_weekday():
        print(f"{LOG_PREFIX} Weekend detected; skipping daily meeting.")
        return

    recipient_email = (
        _env("DAILY_MEETING_NOTIFY_EMAIL")
        or _env("SERVER_OWNER_EMAIL")
        or _env("ADMIN_NOTIFY_EMAIL")
    )
    if not recipient_email:
        print(
            f"{LOG_PREFIX} DAILY_MEETING_NOTIFY_EMAIL, SERVER_OWNER_EMAIL, or ADMIN_NOTIFY_EMAIL must be configured.",
            file=sys.stderr,
        )
        sys.exit(1)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"{LOG_PREFIX} Creating OpenCode daily meeting chat for {today}...")
    session_id, duration_seconds, job_name = _run_opencode_session(today)
    session_url = _build_session_url(session_id)

    print(f"{LOG_PREFIX} OpenCode session: {session_id}")
    if session_url:
        print(f"{LOG_PREFIX} Deep link: {session_url}")
    else:
        print(f"{LOG_PREFIX} OPENCODE_WEB_BASE_URL not configured; deep link unavailable.", file=sys.stderr)

    _dispatch_email(
        recipient_email=recipient_email,
        job_name=job_name,
        session_id=session_id,
        session_url=session_url,
        duration_seconds=duration_seconds,
    )


if __name__ == "__main__":
    main()
