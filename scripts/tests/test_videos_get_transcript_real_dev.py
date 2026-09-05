#!/usr/bin/env python3
"""Run the approved authenticated real-dev audio timestamp REST gate.

Purpose: create only synthetic speech, authenticate through the established test
account helper in an isolated HOME, then delegate upload and REST assertions to
the committed Node harness. Security: no credentials, media, transcript text,
signed URLs, or encryption material are printed or retained.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LOADER = ROOT / "frontend/packages/openmates-cli/tests/loader.mjs"
HARNESS = ROOT / "scripts/tests/videos_get_transcript_real_dev.mjs"
LOGIN_HELPER = ROOT / "scripts/openmates_cli_test_account.mjs"
DEFAULT_API_URL = "https://api.dev.openmates.org"
# Paid integration checks run only through this script's explicit CLI entry point.
__test__ = False


def safe_failure(stage: str, result: subprocess.CompletedProcess[str] | None = None) -> RuntimeError:
    status = f" exit={result.returncode}" if result else ""
    if result:
        diagnostic = re.search(r"^OPENMATES_REST_FAILURE stage=([a-z_]+) http=([0-9]{1,3})$", result.stderr, re.MULTILINE)
        if diagnostic:
            status += f" stage={diagnostic[1]} http={diagnostic[2]}"
        reason = re.search(r"^OPENMATES_REST_REASON ([a-z_0-9]+)$", result.stderr, re.MULTILINE)
        if reason:
            status += f" reason={reason[1]}"
        runtime_code = re.search(r"\b(ERR_[A-Z_]+)\b", result.stderr)
        if runtime_code:
            status += f" runtime={runtime_code[1]}"
        exception = re.search(r"\b(SyntaxError|TypeError|ReferenceError|RangeError):", result.stderr)
        if exception:
            status += f" exception={exception[1]}"
    if stage == "Test-account login":
        return RuntimeError(
            "Test-account login failed"
            f"{status}. Set OPENMATES_TEST_ACCOUNT_EMAIL and OPENMATES_TEST_ACCOUNT_PASSWORD "
            "(plus OPENMATES_TEST_ACCOUNT_OTP_KEY when required), then retry. "
            "Credentials and response bodies are intentionally redacted."
        )
    return RuntimeError(f"{stage} failed{status}. Credentials and response bodies are intentionally redacted.")


def require_dependencies() -> None:
    missing = [name for name in ("node", "ffmpeg") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"Missing required executable(s): {', '.join(missing)}. Install them and retry.")
    for path in (LOADER, HARNESS, LOGIN_HELPER):
        if not path.is_file():
            raise RuntimeError(f"Required committed helper is missing: {path.relative_to(ROOT)}")


def run(command: list[str], *, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


# contract-test: direct surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction,videos.transcript.audio-results-and-billing,videos.transcript.access-and-export,videos.transcript.existing-media-boundary
def test_rest_gate(api_url: str, slot: str | None, include_segment: bool) -> dict[str, Any]:
    require_dependencies()
    with tempfile.TemporaryDirectory(prefix="openmates-videos-transcript-") as home:
        env = os.environ.copy()
        env["HOME"] = home
        env["OPENMATES_TRANSCRIPT_TEST_HOME"] = home
        env["OPENMATES_CLI_DEVICE_IDENTITY"] = "videos-transcript-rest-gate"

        login_command = ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url]
        if slot:
            login_command.extend(["--slot", slot])
        login = run(login_command, env=env, timeout=120)
        if login.returncode:
            raise safe_failure("Test-account login", login)

        command = [
            "node",
            "--experimental-strip-types",
            "--loader",
            str(LOADER),
            str(HARNESS),
            "--api-url",
            api_url,
        ]
        if include_segment:
            command.append("--include-segment")
        result = run(command, env=env, timeout=600)
        if result.returncode:
            raise safe_failure("Real-dev REST timestamp gate", result)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Real-dev REST timestamp gate emitted invalid JSON.") from exc
        if not isinstance(payload, dict) or payload.get("surface") != "rest":
            raise RuntimeError("Real-dev REST timestamp gate emitted an invalid summary.")
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real-dev Videos transcript REST timestamp gate.")
    parser.add_argument("--surface", default="rest", choices=("rest", "cli", "npm", "pip"))
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--include-segment", action="store_true", help="Also verify the optional explicit segment timing request.")
    parser.add_argument("--check", action="store_true", help="Check local executable and committed-helper prerequisites without logging in or calling services.")
    args = parser.parse_args()

    if args.surface != "rest":
        raise NotImplementedError(f"--surface {args.surface} is explicitly not implemented; only --surface rest is an approved gate.")
    if args.check:
        require_dependencies()
        print(json.dumps({"surface": args.surface, "check": "passed"}))
        return 0

    print(json.dumps(test_rest_gate(args.api_url, args.slot, args.include_segment)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, NotImplementedError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
