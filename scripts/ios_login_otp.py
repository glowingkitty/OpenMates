#!/usr/bin/env python3
"""Generate the current iOS login test-account TOTP code.

Reads OPENMATES_TEST_OTP_KEY from .env.ios-login.local by default and prints
the current 6-digit code without exposing the secret. This helper is intended
for local simulator login testing only; do not commit real OTP secrets into the
repository. The TOTP implementation uses RFC 6238 defaults: SHA-1, 30-second
steps, and 6 digits.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import shlex
import struct
import time
from pathlib import Path


DEFAULT_ENV_FILE = ".env.ios-login.local"
OTP_ENV_KEY = "OPENMATES_TEST_OTP_KEY"
TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        values[key.strip()] = shlex.split(value)[0] if value else ""
    return values


def current_totp(secret: str, now: int | None = None) -> tuple[str, int]:
    clean_secret = "".join(secret.split()).upper()
    padded_secret = clean_secret + "=" * ((8 - len(clean_secret) % 8) % 8)
    key = base64.b32decode(padded_secret, casefold=True)

    timestamp = int(time.time()) if now is None else now
    counter = timestamp // TOTP_STEP_SECONDS
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    code = str(code_int % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)
    seconds_remaining = TOTP_STEP_SECONDS - (timestamp % TOTP_STEP_SECONDS)
    return code, seconds_remaining


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the current OpenMates iOS test OTP code.")
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f"Path to env file containing {OTP_ENV_KEY}. Defaults to {DEFAULT_ENV_FILE}.",
    )
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="Print only the 6-digit code.",
    )
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if not env_path.exists():
        parser.error(f"Env file not found: {env_path}")

    secret = parse_env_file(env_path).get(OTP_ENV_KEY)
    if not secret:
        parser.error(f"{OTP_ENV_KEY} is missing or empty in {env_path}")

    code, seconds_remaining = current_totp(secret)
    if args.code_only:
        print(code)
    else:
        print(f"{code} ({seconds_remaining}s remaining)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
