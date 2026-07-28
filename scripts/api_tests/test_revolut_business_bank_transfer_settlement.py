#!/usr/bin/env python3
"""
Revolut Business bank-transfer settlement smoke test.

This operator-run script verifies the official-cloud SEPA settlement path against
the real dev API and Revolut Sandbox. It creates real dev bank-transfer orders,
uses Revolut Sandbox /sandbox/topup to emit incoming transfer webhooks, then
polls the OpenMates order status endpoint for settlement.

It intentionally defaults to a read-only readiness check. Pass --execute to
create orders, trigger sandbox topups, and mutate the dev test account balance.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_URL = "https://api.dev.openmates.org"
DEFAULT_SCENARIOS = "exact,overpaid,underpaid-complete"
REVOLUT_SANDBOX_DIR_NAME = "revolut-sandbox"
REVOLUT_SANDBOX_STATE_FILE = "state.json"
REVOLUT_SANDBOX_PRIVATE_KEY_FILE = "privatekey.pem"
REVOLUT_SETUP_HELPER_PATH = ROOT / "scripts" / "revolut_business_setup.py"
REVOLUT_SANDBOX_STATE_KEYS = ("client_id", "refresh_token", "eur_account_id")
DUPLICATE_BALANCE_STABILITY_SECONDS = 45
API_TRANSACTION_SECRET_ENV_KEYS = (
    "SECRET__REVOLUT_BUSINESS__SANDBOX_ACCOUNT_ID",
    "SECRET__REVOLUT_BUSINESS__SANDBOX_CLIENT_ID",
    "SECRET__REVOLUT_BUSINESS__SANDBOX_REFRESH_TOKEN",
)
API_TRANSACTION_SECRET_ASSERTION_ENV_KEYS = (
    "SECRET__REVOLUT_BUSINESS__SANDBOX_PRIVATE_KEY_PEM",
    "SECRET__REVOLUT_BUSINESS__SANDBOX_CLIENT_ASSERTION",
)
SCENARIO_CREDITS = {
    "exact": 1000,
    "overpaid": 10000,
    "underpaid-complete": 21000,
    "duplicate-completed-reference": 1000,
}


class SettlementSmokeError(RuntimeError):
    pass


def run(command: list[str], *, env: dict[str, str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise SettlementSmokeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def read_cli_session(home: Path) -> dict[str, Any]:
    session_path = home / ".openmates" / "session.json"
    if not session_path.exists():
        raise SettlementSmokeError("CLI session file missing after test-account login")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    if not isinstance(session, dict):
        raise SettlementSmokeError("CLI session file was not a JSON object")
    return session


def session_cookie_header(session: dict[str, Any]) -> str:
    cookies = session.get("cookies") or {}
    if not isinstance(cookies, dict) or not cookies:
        raise SettlementSmokeError("CLI session did not include cookies")
    return "; ".join(f"{key}={value}" for key, value in cookies.items() if isinstance(value, str))


def request_json(
    api_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    cookie_header: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if cookie_header:
        headers["Cookie"] = cookie_header
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if path.startswith("/"):
        request_path = path
    else:
        request_path = f"/v1/payments/{path.lstrip('/')}"
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}{request_path}",
        method=method,
        headers=headers,
        data=data,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SettlementSmokeError(f"{method} {path} failed with HTTP {exc.code}: {body}") from exc


def cents_from_eur(value: str) -> int:
    cents = (Decimal(value) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def eur_from_cents(value: int) -> str:
    return f"{Decimal(value) / Decimal('100'):.2f}"


def login(api_url: str, *, env: dict[str, str], slot: str | None) -> None:
    command = ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url]
    if slot:
        command.extend(["--slot", slot])
    run(command, env=env, timeout=180)


def check_sandbox_topup_prerequisites(env: dict[str, str]) -> None:
    if not REVOLUT_SETUP_HELPER_PATH.exists():
        raise SettlementSmokeError(
            "Local official-cloud setup helper is missing: "
            f"{REVOLUT_SETUP_HELPER_PATH}. This helper is intentionally gitignored; "
            "copy it from the private operator store before running --execute."
        )
    home = Path(env.get("HOME") or str(Path.home())).expanduser()
    sandbox_dir = home / REVOLUT_SANDBOX_DIR_NAME
    state_path = sandbox_dir / REVOLUT_SANDBOX_STATE_FILE
    private_key_path = sandbox_dir / REVOLUT_SANDBOX_PRIVATE_KEY_FILE
    missing = []
    if not state_path.exists():
        missing.append(str(state_path))
    if not private_key_path.exists():
        missing.append(str(private_key_path))
    if missing:
        raise SettlementSmokeError(
            "Revolut Sandbox topup prerequisites are missing: "
            + ", ".join(missing)
            + ". Run `python3 scripts/revolut_business_setup.py --env sandbox` from the operator account first."
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettlementSmokeError(f"Revolut Sandbox state file is not valid JSON: {state_path}") from exc
    missing_keys = [key for key in REVOLUT_SANDBOX_STATE_KEYS if not state.get(key)]
    if missing_keys:
        raise SettlementSmokeError(
            "Revolut Sandbox state file is incomplete: missing "
            + ", ".join(missing_keys)
            + f" in {state_path}. Re-run the sandbox setup helper."
        )


def check_local_api_transaction_secret_prerequisites(env: dict[str, str]) -> None:
    configured_keys = {key for key in API_TRANSACTION_SECRET_ENV_KEYS + API_TRANSACTION_SECRET_ASSERTION_ENV_KEYS if env.get(key)}
    dotenv_path = ROOT / ".env"
    if dotenv_path.exists():
        for raw_line in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value and key in API_TRANSACTION_SECRET_ENV_KEYS + API_TRANSACTION_SECRET_ASSERTION_ENV_KEYS:
                configured_keys.add(key)

    missing = [key for key in API_TRANSACTION_SECRET_ENV_KEYS if key not in configured_keys]
    if not any(key in configured_keys for key in API_TRANSACTION_SECRET_ASSERTION_ENV_KEYS):
        missing.append(
            "SECRET__REVOLUT_BUSINESS__SANDBOX_PRIVATE_KEY_PEM "
            "or SECRET__REVOLUT_BUSINESS__SANDBOX_CLIENT_ASSERTION"
        )
    if missing:
        raise SettlementSmokeError(
            "Local API transaction-confirmation secrets are missing: "
            + ", ".join(missing)
            + ". Add them to .env, run vault-setup, and restart the api service before --execute."
        )


def create_bank_transfer_order(api_url: str, *, cookie_header: str, credits: int) -> dict[str, Any]:
    return request_json(
        api_url,
        "create-bank-transfer-order",
        method="POST",
        cookie_header=cookie_header,
        payload={
            "credits_amount": credits,
            "currency": "eur",
            "email_encryption_key": "sandbox-smoke-email-key",
            "is_signup": False,
            "is_gift_card": False,
        },
    )


def current_user_credits(api_url: str, *, cookie_header: str, session_id: str) -> int:
    session = request_json(
        api_url,
        "/v1/auth/session",
        method="POST",
        cookie_header=cookie_header,
        payload={"session_id": session_id},
    )
    if not session.get("success"):
        raise SettlementSmokeError(f"Session check failed while reading user credits: {session.get('message')}")
    credits = (session.get("user") or {}).get("credits")
    if not isinstance(credits, int):
        raise SettlementSmokeError("Session response did not include an integer user credit balance")
    return credits


def poll_credits(
    api_url: str,
    *,
    cookie_header: str,
    session_id: str,
    expected_credits: int,
    timeout_seconds: int,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    last_credits: int | None = None
    while time.monotonic() < deadline:
        last_credits = current_user_credits(api_url, cookie_header=cookie_header, session_id=session_id)
        if last_credits == expected_credits:
            return last_credits
        time.sleep(5)
    raise SettlementSmokeError(
        f"User credits did not reach {expected_credits} within {timeout_seconds}s; last_credits={last_credits}"
    )


def assert_credits_stable(
    api_url: str,
    *,
    cookie_header: str,
    session_id: str,
    expected_credits: int,
    duration_seconds: int,
) -> int:
    deadline = time.monotonic() + duration_seconds
    observed = expected_credits
    while time.monotonic() < deadline:
        observed = current_user_credits(api_url, cookie_header=cookie_header, session_id=session_id)
        if observed != expected_credits:
            raise SettlementSmokeError(
                f"Duplicate completed-reference transfer changed user credits: expected {expected_credits}, got {observed}"
            )
        time.sleep(5)
    return observed


def simulate_sandbox_topup(reference: str, amount_eur: str, *, env: dict[str, str]) -> None:
    run(
        [
            sys.executable,
            "scripts/revolut_business_setup.py",
            "--env",
            "sandbox",
            "--simulate-topup",
            "--reference",
            reference,
            "--amount",
            amount_eur,
        ],
        env=env,
        timeout=120,
    )


def poll_status(
    api_url: str,
    *,
    cookie_header: str,
    order_id: str,
    expected_status: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status = request_json(
            api_url,
            f"bank-transfer-status/{order_id}",
            cookie_header=cookie_header,
        )
        if last_status.get("status") == expected_status:
            return last_status
        time.sleep(5)
    raise SettlementSmokeError(
        f"Order {order_id} did not reach status={expected_status!r} within {timeout_seconds}s; "
        f"last_status={last_status}"
    )


def run_scenario(
    scenario: str,
    *,
    api_url: str,
    cookie_header: str,
    session_id: str,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    credits = SCENARIO_CREDITS[scenario]
    order = create_bank_transfer_order(api_url, cookie_header=cookie_header, credits=credits)
    expected_cents = cents_from_eur(str(order["amount_eur"]))
    reference = str(order["reference"])
    order_id = str(order["order_id"])

    if scenario == "exact":
        simulate_sandbox_topup(reference, eur_from_cents(expected_cents), env=env)
        status = poll_status(
            api_url,
            cookie_header=cookie_header,
            order_id=order_id,
            expected_status="completed",
            timeout_seconds=timeout_seconds,
        )
    elif scenario == "overpaid":
        simulate_sandbox_topup(reference, eur_from_cents(expected_cents + 100), env=env)
        status = poll_status(
            api_url,
            cookie_header=cookie_header,
            order_id=order_id,
            expected_status="completed",
            timeout_seconds=timeout_seconds,
        )
    elif scenario == "underpaid-complete":
        first_cents = max(1, expected_cents - 100)
        simulate_sandbox_topup(reference, eur_from_cents(first_cents), env=env)
        time.sleep(10)
        simulate_sandbox_topup(reference, eur_from_cents(expected_cents - first_cents), env=env)
        status = poll_status(
            api_url,
            cookie_header=cookie_header,
            order_id=order_id,
            expected_status="completed",
            timeout_seconds=timeout_seconds,
        )
    elif scenario == "duplicate-completed-reference":
        starting_credits = current_user_credits(api_url, cookie_header=cookie_header, session_id=session_id)
        simulate_sandbox_topup(reference, eur_from_cents(expected_cents), env=env)
        status = poll_status(
            api_url,
            cookie_header=cookie_header,
            order_id=order_id,
            expected_status="completed",
            timeout_seconds=timeout_seconds,
        )
        credited_balance = poll_credits(
            api_url,
            cookie_header=cookie_header,
            session_id=session_id,
            expected_credits=starting_credits + credits,
            timeout_seconds=timeout_seconds,
        )
        simulate_sandbox_topup(reference, eur_from_cents(expected_cents), env=env)
        assert_credits_stable(
            api_url,
            cookie_header=cookie_header,
            session_id=session_id,
            expected_credits=credited_balance,
            duration_seconds=min(timeout_seconds, DUPLICATE_BALANCE_STABILITY_SECONDS),
        )
    else:
        raise SettlementSmokeError(f"Unsupported scenario: {scenario}")

    return {
        "scenario": scenario,
        "status": "pass",
        "order_id": order_id,
        "reference_prefix": reference[:8],
        "credits": credits,
        "expected_amount_eur": order["amount_eur"],
        "final_order_status": status.get("status"),
    }


def parse_scenarios(raw: str) -> list[str]:
    scenarios = [item.strip() for item in raw.split(",") if item.strip()]
    unsupported = sorted(set(scenarios) - set(SCENARIO_CREDITS))
    if unsupported:
        raise SettlementSmokeError(f"Unsupported scenarios: {', '.join(unsupported)}")
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Revolut Sandbox bank-transfer settlement against the dev API")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--scenarios", default=DEFAULT_SCENARIOS)
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--execute", action="store_true", help="Create dev orders and trigger Revolut Sandbox topups")
    args = parser.parse_args()

    scenarios = parse_scenarios(args.scenarios)
    operator_env = dict(os.environ)
    check_local_api_transaction_secret_prerequisites(operator_env)
    if args.execute:
        check_sandbox_topup_prerequisites(operator_env)

    with tempfile.TemporaryDirectory(prefix="openmates-revolut-smoke-") as home_dir:
        cli_env = dict(operator_env)
        cli_env["HOME"] = home_dir
        login(args.api_url, env=cli_env, slot=args.slot)
        session = read_cli_session(Path(home_dir))
        cookie_header = session_cookie_header(session)
        session_id = str(session.get("sessionId") or "")
        if not session_id:
            raise SettlementSmokeError("CLI session did not include a session ID")

        config = request_json(args.api_url, "config", cookie_header=cookie_header)
        if not config.get("bank_transfer_available"):
            raise SettlementSmokeError(
                "Bank transfer is not available on this API. Configure sandbox IBAN/BIC/webhook secret, "
                "restart the API service, and confirm the request is hitting an official-cloud domain."
            )

        if not args.execute:
            print(json.dumps({"status": "ready", "execute_required": True, "scenarios": scenarios}, indent=2))
            return

        results = [
            run_scenario(
                scenario,
                api_url=args.api_url,
                cookie_header=cookie_header,
                session_id=session_id,
                env=operator_env,
                timeout_seconds=args.timeout_seconds,
            )
            for scenario in scenarios
        ]
        print(json.dumps({"status": "pass", "results": results}, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except SettlementSmokeError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, indent=2), file=sys.stderr)
        sys.exit(1)
