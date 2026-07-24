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
SCENARIO_CREDITS = {
    "exact": 1000,
    "overpaid": 10000,
    "underpaid-complete": 21000,
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


def session_cookie_header(home: Path) -> str:
    session_path = home / ".openmates" / "session.json"
    if not session_path.exists():
        raise SettlementSmokeError("CLI session file missing after test-account login")
    cookies = json.loads(session_path.read_text(encoding="utf-8")).get("cookies") or {}
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
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/v1/payments/{path.lstrip('/')}",
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
    with tempfile.TemporaryDirectory(prefix="openmates-revolut-smoke-") as home_dir:
        env = dict(os.environ)
        env["HOME"] = home_dir
        login(args.api_url, env=env, slot=args.slot)
        cookie_header = session_cookie_header(Path(home_dir))

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
                env=env,
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
