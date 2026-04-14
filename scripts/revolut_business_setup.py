#!/usr/bin/env python3
"""
Revolut Business API Setup Helper

Interactive helper to set up Revolut Business webhooks for SEPA bank transfer
monitoring. Handles the full OAuth + JWT flow, creates the webhook, fetches
the EUR account IBAN/BIC, and prints Vault-ready secrets.

Usage:
    python3 scripts/revolut_business_setup.py --env sandbox
    python3 scripts/revolut_business_setup.py --env production

Prerequisites:
    1. Generated an X509 self-signed certificate (publickey.cer + privatekey.pem)
       Default location: ~/revolut-sandbox/  or  ~/revolut-prod/
    2. Uploaded publickey.cer to Revolut Business → API Keys → Add API certificate
    3. Got a Client ID from Revolut

The script is interactive — it walks you through each step and saves artifacts
(refresh token, webhook ID) to a JSON file for later management.

Required pip packages: cryptography, PyJWT, requests
    pip install cryptography PyJWT requests
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

try:
    import jwt  # PyJWT
    import requests
except ImportError as exc:
    print(f"Missing dependency: {exc}\n")
    print("Install with: pip install cryptography PyJWT requests")
    sys.exit(1)


# ────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────

REVOLUT_HOSTS = {
    "sandbox": {
        "ui": "https://sandbox-business.revolut.com",
        "api": "https://sandbox-b2b.revolut.com/api/1.0",
        "api_v2": "https://sandbox-b2b.revolut.com/api/2.0",
        "auth": "https://sandbox-b2b.revolut.com/api/1.0/auth/token",
        "authorize": "https://sandbox-business.revolut.com/app-confirm",
    },
    "production": {
        "ui": "https://business.revolut.com",
        "api": "https://b2b.revolut.com/api/1.0",
        "api_v2": "https://b2b.revolut.com/api/2.0",
        "auth": "https://b2b.revolut.com/api/1.0/auth/token",
        "authorize": "https://business.revolut.com/app-confirm",
    },
}

DEFAULT_CERT_DIRS = {
    "sandbox": "~/revolut-sandbox",
    "production": "~/revolut-prod",
}

# Webhook events we need for SEPA monitoring
WEBHOOK_EVENTS = ["TransactionCreated", "TransactionStateChanged"]


# ────────────────────────────────────────────────────────────────────
# JWT generation (Revolut requires a JWT signed with the private key
# as the client_assertion in OAuth2 token requests)
# ────────────────────────────────────────────────────────────────────

def generate_client_assertion(client_id: str, private_key: str, env: str, issuer: str) -> str:
    """Generate a JWT to authenticate the client during OAuth token exchange.

    Note: Revolut requires:
      - `aud=https://revolut.com` for BOTH sandbox and production
      - `iss` must match the domain of the OAuth redirect URI registered with the
        certificate (without https://). E.g. `api.dev.openmates.org`.
    """
    now = int(time.time())
    payload = {
        "iss": issuer,
        "sub": client_id,
        "aud": "https://revolut.com",
        "exp": now + 60 * 60,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


# ────────────────────────────────────────────────────────────────────
# OAuth flow
# ────────────────────────────────────────────────────────────────────

def get_authorization_url(client_id: str, env: str) -> str:
    """Build the URL the user must visit in their browser to authorize the app."""
    host = REVOLUT_HOSTS[env]["authorize"]
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": "https://api.dev.openmates.org/v1/payments/webhook",
        "scope": "READ,WRITE",
    }
    return f"{host}?{urlencode(params)}"


def exchange_auth_code_for_tokens(
    client_id: str, auth_code: str, private_key: str, env: str
) -> dict:
    """Exchange the authorization code (from the redirect URL) for refresh + access tokens."""
    issuer = "api.dev.openmates.org" if env == "sandbox" else "api.openmates.org"
    assertion = generate_client_assertion(client_id, private_key, env, issuer)
    response = requests.post(
        REVOLUT_HOSTS[env]["auth"],
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": client_id,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Token exchange failed ({response.status_code}): {response.text}")
    return response.json()


def refresh_access_token(
    client_id: str, refresh_token: str, private_key: str, env: str
) -> dict:
    """Use a stored refresh token to get a fresh access token (refresh tokens last ~90 days)."""
    issuer = "api.dev.openmates.org" if env == "sandbox" else "api.openmates.org"
    assertion = generate_client_assertion(client_id, private_key, env, issuer)
    response = requests.post(
        REVOLUT_HOSTS[env]["auth"],
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Token refresh failed ({response.status_code}): {response.text}")
    return response.json()


# ────────────────────────────────────────────────────────────────────
# Revolut API calls
# ────────────────────────────────────────────────────────────────────

def list_accounts(access_token: str, env: str) -> list:
    """List all accounts on the Revolut Business profile."""
    response = requests.get(
        f"{REVOLUT_HOSTS[env]['api']}/accounts",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"List accounts failed ({response.status_code}): {response.text}")
    return response.json()


def get_account_bank_details(access_token: str, env: str, account_id: str) -> dict:
    """Get IBAN/BIC for a specific account."""
    response = requests.get(
        f"{REVOLUT_HOSTS[env]['api']}/accounts/{account_id}/bank-details",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Get bank details failed ({response.status_code}): {response.text}")
    return response.json()


def list_webhooks(access_token: str, env: str) -> list:
    """List all existing webhooks."""
    response = requests.get(
        f"{REVOLUT_HOSTS[env]['api_v2']}/webhooks",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"List webhooks failed ({response.status_code}): {response.text}")
    return response.json()


def create_webhook(access_token: str, env: str, url: str) -> dict:
    """Create a new webhook subscribing to TransactionCreated + TransactionStateChanged."""
    response = requests.post(
        f"{REVOLUT_HOSTS[env]['api_v2']}/webhooks",
        json={"url": url, "events": WEBHOOK_EVENTS},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Create webhook failed ({response.status_code}): {response.text}")
    return response.json()


def delete_webhook(access_token: str, env: str, webhook_id: str) -> None:
    """Delete an existing webhook by ID."""
    response = requests.delete(
        f"{REVOLUT_HOSTS[env]['api_v2']}/webhooks/{webhook_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Delete webhook failed ({response.status_code}): {response.text}")


# ────────────────────────────────────────────────────────────────────
# State persistence (refresh token + webhook ID for later management)
# ────────────────────────────────────────────────────────────────────

def project_root() -> Path:
    """Project root (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def write_env_secrets(env: str, secrets: dict) -> None:
    """
    Write the SECRET__REVOLUT_BUSINESS__{ENV}_* values to the project's .env file.

    For each key:
      - If the line already exists in .env (any value, including ""), replaces in place
      - If the line does not exist, appends after the last SECRET__REVOLUT_BUSINESS__ line
        (or at the end of the file if none exist)

    Args:
        env: 'sandbox' or 'production'
        secrets: dict with keys 'webhook_secret', 'iban', 'bic'
    """
    env_upper = env.upper()
    target = {
        f"SECRET__REVOLUT_BUSINESS__{env_upper}_WEBHOOK_SECRET": secrets["webhook_secret"],
        f"SECRET__REVOLUT_BUSINESS__{env_upper}_IBAN": secrets["iban"],
        f"SECRET__REVOLUT_BUSINESS__{env_upper}_BIC": secrets["bic"],
    }

    env_path = project_root() / ".env"
    if not env_path.exists():
        print(f"  ✗ .env not found at {env_path} — skipping auto-write")
        return

    lines = env_path.read_text().splitlines()
    existing_keys = set()
    last_revolut_idx = -1

    # First pass: replace existing lines
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("SECRET__REVOLUT_BUSINESS__"):
            last_revolut_idx = i
        for key, value in target.items():
            if stripped.startswith(f"{key}="):
                lines[i] = f'{key}="{value}"'
                existing_keys.add(key)
                break

    # Second pass: append any keys that didn't exist
    missing = [(k, v) for k, v in target.items() if k not in existing_keys]
    if missing:
        # Insert right after the last SECRET__REVOLUT_BUSINESS__ line
        insert_at = last_revolut_idx + 1 if last_revolut_idx >= 0 else len(lines)
        new_lines = [f'{k}="{v}"' for k, v in missing]
        lines = lines[:insert_at] + new_lines + lines[insert_at:]

    env_path.write_text("\n".join(lines) + ("\n" if lines and lines[-1] else ""))

    print(f"  ✓ Wrote {len(target)} secrets to {env_path}")
    print(f"    ({len(existing_keys)} updated in place, {len(missing)} appended)")


def state_path(env: str) -> Path:
    return Path(os.path.expanduser(DEFAULT_CERT_DIRS[env])) / "state.json"


def save_state(env: str, data: dict) -> None:
    path = state_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        existing = json.loads(path.read_text())
    existing.update(data)
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(existing, indent=2))
    os.chmod(path, 0o600)
    print(f"  → State saved to {path}")


def load_state(env: str) -> dict:
    path = state_path(env)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ────────────────────────────────────────────────────────────────────
# Interactive flow
# ────────────────────────────────────────────────────────────────────

def prompt(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or default


def section(title: str) -> None:
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}")


def setup(env: str, write_env: bool = False) -> None:
    section(f"Revolut Business Setup — {env.upper()}")

    # ── Step 1: Locate certificate ────────────────────────────────
    cert_dir = Path(os.path.expanduser(DEFAULT_CERT_DIRS[env]))
    private_key_path = cert_dir / "privatekey.pem"

    if not private_key_path.exists():
        print(f"\nPrivate key not found at {private_key_path}")
        custom = prompt("Enter path to privatekey.pem")
        private_key_path = Path(os.path.expanduser(custom))
        if not private_key_path.exists():
            print(f"Error: file not found at {private_key_path}")
            sys.exit(1)

    private_key = private_key_path.read_text()
    print(f"\n✓ Loaded private key from {private_key_path}")

    # ── Step 2: Get Client ID ────────────────────────────────────
    state = load_state(env)
    client_id = state.get("client_id") or prompt(
        "\nClient ID from Revolut Business (paste here)"
    )
    if not client_id:
        print("Error: Client ID required")
        sys.exit(1)

    # ── Step 3: OAuth flow (or use existing refresh token) ────────
    refresh_token = state.get("refresh_token")

    if refresh_token:
        print("\n✓ Using stored refresh token from previous setup")
        try:
            tokens = refresh_access_token(client_id, refresh_token, private_key, env)
            access_token = tokens["access_token"]
            # Refresh token may rotate — store the new one
            if tokens.get("refresh_token") and tokens["refresh_token"] != refresh_token:
                save_state(env, {"refresh_token": tokens["refresh_token"]})
            print(f"  → Got fresh access token (expires in {tokens.get('expires_in', '?')}s)")
        except RuntimeError as e:
            print(f"  → Refresh failed ({e}). Re-authorizing...")
            refresh_token = None

    if not refresh_token:
        section("Authorize the App (one-time)")
        auth_url = get_authorization_url(client_id, env)
        print(f"\n1. Open this URL in your browser:\n\n   {auth_url}\n")
        print("2. Approve the app for your Revolut Business profile.")
        print("3. You'll be redirected to a URL like:\n")
        print("     https://api.dev.openmates.org/v1/payments/webhook?code=oa_sand_XXX...\n")
        print("4. The page will show an error (that's expected — the redirect URI is")
        print("   just a placeholder). Copy the `code` parameter from the URL.\n")
        auth_code = prompt("Paste the authorization code (the value after `code=`)")
        if not auth_code:
            print("Error: authorization code required")
            sys.exit(1)

        print("\n  → Exchanging code for tokens...")
        tokens = exchange_auth_code_for_tokens(client_id, auth_code, private_key, env)
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]
        print("  ✓ Got refresh token (saved for future runs)")

        save_state(env, {
            "client_id": client_id,
            "refresh_token": refresh_token,
        })

    # ── Step 4: List accounts → find EUR account ────────────────
    section("Find EUR Account")
    accounts = list_accounts(access_token, env)
    eur_accounts = [a for a in accounts if a.get("currency") == "EUR"]

    if not eur_accounts:
        print("Error: No EUR account found on this Revolut Business profile.")
        print("Available currencies:", [a.get("currency") for a in accounts])
        sys.exit(1)

    print(f"\nFound {len(eur_accounts)} EUR account(s):")
    for i, acc in enumerate(eur_accounts):
        print(f"  [{i}] {acc.get('name', '(unnamed)')} — ID: {acc['id']}")

    if len(eur_accounts) == 1:
        eur_account = eur_accounts[0]
    else:
        idx = int(prompt("Which EUR account to use? (number)", "0"))
        eur_account = eur_accounts[idx]

    bank_details_list = get_account_bank_details(access_token, env, eur_account["id"])
    if not bank_details_list:
        print(f"Error: No bank details found for account {eur_account['id']}")
        sys.exit(1)

    # bank-details endpoint returns a list (one entry per local scheme: SEPA, SWIFT, etc.)
    sepa_details = next(
        (d for d in bank_details_list if d.get("scheme") in ("SEPA", "BACS", None)),
        bank_details_list[0],
    )
    iban = sepa_details.get("iban", "")
    bic = sepa_details.get("bic", "")
    print(f"\n  ✓ EUR account: {eur_account['id']}")
    print(f"  ✓ IBAN: {iban}")
    print(f"  ✓ BIC:  {bic}")

    save_state(env, {
        "eur_account_id": eur_account["id"],
        "iban": iban,
        "bic": bic,
    })

    # ── Step 5: Create webhook (or reuse existing) ────────────────
    section("Configure Webhook")

    default_url = (
        "https://api.dev.openmates.org/v1/payments/webhook"
        if env == "sandbox"
        else "https://api.openmates.org/v1/payments/webhook"
    )
    webhook_url = prompt("Webhook URL", default_url)

    existing_webhooks = list_webhooks(access_token, env)
    matching = [w for w in existing_webhooks if w.get("url") == webhook_url]

    if matching:
        print(f"\n⚠  Webhook for {webhook_url} already exists (ID: {matching[0]['id']}).")
        recreate = prompt("Delete and recreate to get a fresh signing secret? (y/N)", "n")
        if recreate.lower() == "y":
            delete_webhook(access_token, env, matching[0]["id"])
            print(f"  → Deleted existing webhook {matching[0]['id']}")
            webhook = create_webhook(access_token, env, webhook_url)
        else:
            stored_secret = state.get("webhook_signing_secret")
            if not stored_secret:
                print("\n⚠  Existing webhook found but no signing secret stored locally.")
                print("   You must recreate the webhook to get a new signing secret.")
                sys.exit(1)
            webhook = {
                "id": matching[0]["id"],
                "signing_secret": stored_secret,
            }
    else:
        webhook = create_webhook(access_token, env, webhook_url)
        print(f"  ✓ Created webhook (ID: {webhook['id']})")

    signing_secret = webhook["signing_secret"]
    save_state(env, {
        "webhook_id": webhook["id"],
        "webhook_url": webhook_url,
        "webhook_signing_secret": signing_secret,
    })

    # ── Step 6: Write secrets to .env (or print) ──────────────────
    section("✓ Setup Complete")
    env_upper = env.upper()

    if write_env:
        print("\nWriting secrets to .env...")
        write_env_secrets(env, {
            "webhook_secret": signing_secret,
            "iban": iban,
            "bic": bic,
        })
    else:
        print(f"""
Add these secrets to your `.env` (cloud only — not in .env.example):

  SECRET__REVOLUT_BUSINESS__{env_upper}_WEBHOOK_SECRET={signing_secret}
  SECRET__REVOLUT_BUSINESS__{env_upper}_IBAN={iban}
  SECRET__REVOLUT_BUSINESS__{env_upper}_BIC={bic}

Tip: re-run with --write-env to update .env automatically.""")

    print(f"""
Next: run your Vault import flow to push secrets to kv/data/providers/revolut_business

Local artifacts saved to: {state_path(env)}
  - Refresh token (rotates ~90 days — re-run this script when needed)
  - Webhook ID, URL, signing secret
  - EUR account ID, IBAN, BIC
  - Permissions: 0600 (private key + state file)

For sandbox testing, simulate an incoming SEPA transfer:

  python3 scripts/revolut_business_setup.py --env sandbox --simulate-topup --reference OM-XXX --amount 100
""")


def simulate_topup(env: str, reference: str, amount: float) -> None:
    """Simulate an incoming SEPA transfer (sandbox only)."""
    if env != "sandbox":
        print("Error: --simulate-topup only works for sandbox")
        sys.exit(1)

    state = load_state(env)
    if not state.get("refresh_token") or not state.get("eur_account_id"):
        print("Error: run setup first to populate state.json")
        sys.exit(1)

    cert_dir = Path(os.path.expanduser(DEFAULT_CERT_DIRS[env]))
    private_key = (cert_dir / "privatekey.pem").read_text()

    tokens = refresh_access_token(
        state["client_id"], state["refresh_token"], private_key, env
    )
    access_token = tokens["access_token"]
    if tokens.get("refresh_token"):
        save_state(env, {"refresh_token": tokens["refresh_token"]})

    response = requests.post(
        f"{REVOLUT_HOSTS[env]['api']}/sandbox/topup",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "account_id": state["eur_account_id"],
            "amount": amount,
            "currency": "EUR",
            "reference": reference,
            "state": "completed",
        },
        timeout=30,
    )
    if response.status_code not in (200, 201):
        print(f"✗ Topup failed ({response.status_code}): {response.text}")
        sys.exit(1)

    data = response.json()
    print("✓ Simulated incoming transfer:")
    print(f"  Amount:    €{amount:.2f}")
    print(f"  Reference: {reference}")
    print(f"  Txn ID:    {data.get('id')}")
    print(f"  State:     {data.get('state')}")
    print("\nThe webhook should fire shortly. Watch dev server logs for the match.")


# ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Revolut Business setup helper for SEPA bank transfer monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env", choices=["sandbox", "production"], required=True,
        help="Which Revolut Business environment to set up",
    )
    parser.add_argument(
        "--write-env", action="store_true",
        help="Write the resulting secrets directly to project .env (replaces existing values in place)",
    )
    parser.add_argument(
        "--simulate-topup", action="store_true",
        help="(Sandbox only) Simulate an incoming SEPA transfer",
    )
    parser.add_argument("--reference", help="Reference for --simulate-topup")
    parser.add_argument("--amount", type=float, default=100.0, help="Amount for --simulate-topup")
    args = parser.parse_args()

    if args.simulate_topup:
        if not args.reference:
            parser.error("--simulate-topup requires --reference")
        simulate_topup(args.env, args.reference, args.amount)
    else:
        setup(args.env, write_env=args.write_env)


if __name__ == "__main__":
    main()
