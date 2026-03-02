"""
Payment Provider Routing Tests
===============================
Tests that /v1/payments/config correctly routes to Stripe (EU IPs) or Polar (non-EU IPs),
and that provider_override query parameter works correctly.

Uses Webshare rotating residential proxies to simulate requests from different geographic
regions, so results reflect the actual IP-based geo-detection logic on the server.

Prerequisites:
  - OPENMATES_TEST_ACCOUNT_API_KEY set in .env (an active account API key)
  - Webshare credentials stored in Vault at kv/data/providers/webshare
    (proxy_username / proxy_password) — fetched via docker exec into the api container
  - Server running at API_BASE_URL (dev server)
  - Docker running with the 'api' container active

Execution:
  /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_payment_provider_routing.py

Note: Polar provider routes to Stripe as fallback until Polar Vault secrets are configured.
      These tests verify routing intent (EU→stripe, non-EU→polar-or-stripe-fallback).

Webshare credentials are fetched from HashiCorp Vault via `docker exec api python3`.
This is required because .env contains IMPORTED_TO_VAULT placeholders, not real credentials.
The api container has access to Vault via the token at /vault-data/api.token.
"""

import os
import json
import subprocess
import httpx
import pytest
import time
from typing import Optional, Tuple
from dotenv import load_dotenv

# Load environment variables from the root .env file
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))


class ProxyAuthError(Exception):
    """
    Raised when Webshare proxy returns 407 Proxy Authentication Required.

    This typically means the current machine's IP is not whitelisted in the
    Webshare dashboard. To fix:
      1. Log in to proxy.webshare.io → Proxy → IP Authorization
      2. Add the Docker host IP to the whitelist, OR
      3. Disable IP whitelisting to use username:password auth only
    """

# =============================================================================
# Configuration
# =============================================================================

API_BASE_URL = "https://api.dev.openmates.org"
API_KEY = os.getenv("OPENMATES_TEST_ACCOUNT_API_KEY")

WEBSHARE_PROXY_HOST = "p.webshare.io"
WEBSHARE_PROXY_PORT = 80

# Skip all tests if API key is missing or still a placeholder
_PLACEHOLDER = "IMPORTED_TO_VAULT"
if not API_KEY or API_KEY == _PLACEHOLDER:
    pytest.skip(
        "OPENMATES_TEST_ACCOUNT_API_KEY not set in .env. "
        "Set it to a valid sk-api-... key to run payment routing tests.",
        allow_module_level=True,
    )


def _fetch_webshare_credentials_from_vault() -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch Webshare proxy credentials from HashiCorp Vault via docker exec.

    The .env file contains IMPORTED_TO_VAULT placeholders for SECRET__WEBSHARE__*
    because real credentials were imported to Vault. This function runs a Python
    script file inside the 'api' Docker container (which has a valid Vault token
    at /vault-data/api.token) to retrieve the actual credentials.

    Strategy: write the script to a temp file inside the container (to avoid
    Python -c async def syntax restrictions), then execute it.

    Returns:
        (username, password) tuple, or (None, None) if fetching fails.
    """
    # The script content to execute inside the container
    script_content = (
        "import asyncio, sys\n"
        "sys.path.insert(0, '/app')\n"
        "from backend.core.api.app.utils.secrets_manager import SecretsManager\n"
        "\n"
        "async def main():\n"
        "    sm = SecretsManager()\n"
        "    await sm.initialize()\n"
        "    u = await sm.get_secret('kv/data/providers/webshare', 'proxy_username')\n"
        "    p = await sm.get_secret('kv/data/providers/webshare', 'proxy_password')\n"
        "    await sm.aclose()\n"
        "    print(u + '|||' + p)\n"
        "\n"
        "asyncio.run(main())\n"
    )
    try:
        # Step 1: write the script to a temp file inside the api container
        write_result = subprocess.run(
            ["docker", "exec", "-i", "api", "sh", "-c",
             "cat > /tmp/_webshare_vault_fetch.py"],
            input=script_content,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if write_result.returncode != 0:
            print(f"\n[VAULT] Failed to write script: {write_result.stderr!r}")
            return None, None

        # Step 2: execute the script inside the container
        result = subprocess.run(
            ["docker", "exec", "api", "python3", "/tmp/_webshare_vault_fetch.py"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip()
        if "|||" in output:
            # Take the last line containing the separator (skips any log noise)
            last_line = [ln for ln in output.splitlines() if "|||" in ln][-1]
            username, password = last_line.split("|||", 1)
            return username.strip(), password.strip()
        else:
            print(f"\n[VAULT] Failed to parse credentials. stdout={output!r} stderr={result.stderr!r}")
            return None, None
    except Exception as e:
        print(f"\n[VAULT] docker exec failed: {e}")
        return None, None


# Fetch Webshare credentials from Vault at module load time (once per pytest session).
# This avoids calling docker exec on every test function.
_WEBSHARE_USERNAME, _WEBSHARE_PASSWORD = _fetch_webshare_credentials_from_vault()
HAS_WEBSHARE = bool(_WEBSHARE_USERNAME and _WEBSHARE_PASSWORD)

if HAS_WEBSHARE:
    WEBSHARE_USERNAME = _WEBSHARE_USERNAME
    WEBSHARE_PASSWORD = _WEBSHARE_PASSWORD
    print(f"\n[VAULT] Webshare credentials loaded from Vault: {WEBSHARE_USERNAME[:5]}...")
else:
    WEBSHARE_USERNAME = None
    WEBSHARE_PASSWORD = None
    print("\n[VAULT] Could not fetch Webshare credentials from Vault — proxy tests will be skipped.")


# =============================================================================
# Helpers
# =============================================================================

def log_response(response: httpx.Response):
    """Event hook to log API responses for debugging."""
    try:
        response.read()
    except Exception:
        pass
    print(f"\n[API] {response.request.method} {response.request.url} -> {response.status_code}")
    try:
        data = response.json()
        print(f"[RESPONSE] {json.dumps(data, indent=2)}")
    except Exception:
        text = getattr(response, "text", "")
        if text:
            print(f"[RESPONSE] {text[:500]}")


def make_webshare_proxy_url(country: Optional[str] = None) -> str:
    """
    Build a Webshare rotating residential proxy URL.

    Webshare's rotating endpoint (p.webshare.io:80) selects a random IP from their
    residential pool each connection.

    Country targeting (e.g. username-country-us) requires a Webshare Premium plan.
    On a basic plan, country is ignored and the proxy just picks a random IP.
    The country parameter is accepted here for documentation purposes but is NOT
    appended to the username unless Webshare's country-targeting plan is active.

    To enable country targeting, set WEBSHARE_COUNTRY_TARGETING=1 in .env AND
    upgrade to a Webshare Premium plan.

    See: https://proxy.webshare.io/documentation/rotating-proxy

    Args:
        country: Two-letter ISO country code hint (e.g. "us", "de").
                 Only used if WEBSHARE_COUNTRY_TARGETING env var is set.
    Returns:
        Proxy URL string for use with httpx.
    """
    username = WEBSHARE_USERNAME
    country_targeting = os.getenv("WEBSHARE_COUNTRY_TARGETING", "").lower() in ("1", "true", "yes")
    if country and country_targeting:
        username = f"{username}-country-{country.lower()}"
    return f"http://{username}:{WEBSHARE_PASSWORD}@{WEBSHARE_PROXY_HOST}:{WEBSHARE_PROXY_PORT}"


def get_payment_config_via_docker(
    proxy_url: Optional[str] = None,
    provider_override: Optional[str] = None,
    timeout: float = 30.0,
) -> dict:
    """
    Call GET /v1/payments/config from inside the 'api' Docker container via docker exec.

    This is needed for proxy tests because Webshare has IP whitelisting:
    the Docker container's outbound IP is whitelisted, but the host machine's IP is not.
    Running the HTTP call from within the container uses the whitelisted Docker host IP.

    Uses httpx inside the container (already installed as part of the api requirements).

    Args:
        proxy_url: Optional Webshare proxy URL to route the request through.
        provider_override: Optional 'stripe' or 'polar' query param.
        timeout: Request timeout in seconds.
    Returns:
        Parsed JSON dict with at least 'provider' key.
    Raises:
        AssertionError: If the response is not 200 OK or JSON is invalid.
        RuntimeError: If docker exec fails.
    """
    url = f"{API_BASE_URL}/v1/payments/config"
    if provider_override:
        url += f"?provider_override={provider_override}"

    # Build the Python snippet to run inside the container
    proxy_arg = f'"{proxy_url}"' if proxy_url else "None"
    script_lines = [
        "import httpx, json, sys",
        f"url = {url!r}",
        f"proxy_url = {proxy_arg}",
        f"api_key = {API_KEY!r}",
        f"timeout = {timeout}",
        "headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}",
        "client_kwargs = {'headers': headers, 'timeout': timeout}",
        "if proxy_url: client_kwargs['proxy'] = proxy_url",
        "with httpx.Client(**client_kwargs) as c:",
        "    r = c.get(url)",
        "    sys.stdout.write(json.dumps({'status': r.status_code, 'body': r.json()}) + '\\n')",
    ]
    script_content = "\n".join(script_lines)

    try:
        # Write the script to a temp file inside the container
        write_result = subprocess.run(
            ["docker", "exec", "-i", "api", "sh", "-c",
             "cat > /tmp/_proxy_config_test.py"],
            input=script_content,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if write_result.returncode != 0:
            raise RuntimeError(f"Failed to write script: {write_result.stderr}")

        # Execute it inside the container
        run_result = subprocess.run(
            ["docker", "exec", "api", "python3", "/tmp/_proxy_config_test.py"],
            capture_output=True,
            text=True,
            timeout=int(timeout) + 15,
        )
        output = run_result.stdout.strip()
        stderr = run_result.stderr or ""

        # Detect proxy auth failure (Webshare IP whitelist blocks this machine)
        if not output and ("407 Proxy Authentication Required" in stderr or "ProxyError" in stderr):
            raise ProxyAuthError(
                "Webshare proxy returned 407. The current machine's IP is not whitelisted "
                "in the Webshare dashboard. Add this IP to Webshare → Proxy → IP Authorization, "
                f"or disable IP whitelisting to use username:password auth only.\n"
                f"Stderr: {stderr[:300]}"
            )

        if not output:
            raise RuntimeError(
                f"No output from docker exec. stderr={stderr!r}"
            )

        # Parse the last non-empty line (skip any log noise)
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                result = json.loads(line)
                status = result["status"]
                body = result["body"]
                print(f"\n[DOCKER-API] GET {url} → {status}")
                print(f"[RESPONSE] {json.dumps(body, indent=2)}")
                assert status == 200, f"GET {url} returned {status}: {body}"
                assert "provider" in body, f"Response missing 'provider': {body}"
                return body

        raise RuntimeError(f"Could not parse JSON from output: {output!r}")

    except (ProxyAuthError, RuntimeError, AssertionError):
        raise
    except Exception as e:
        raise RuntimeError(f"docker exec failed: {e}") from e


def get_payment_config(
    proxy_url: Optional[str] = None,
    provider_override: Optional[str] = None,
    timeout: float = 30.0,
) -> dict:
    """
    Call GET /v1/payments/config and return the parsed JSON response.

    Args:
        proxy_url: Optional Webshare proxy URL to route the request through.
        provider_override: Optional 'stripe' or 'polar' to pass as query param.
        timeout: Request timeout in seconds.
    Returns:
        Parsed JSON dict with at least 'provider' key.
    Raises:
        AssertionError: If the response is not 200 OK.
    """
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    url = "/v1/payments/config"
    if provider_override:
        url += f"?provider_override={provider_override}"

    client_kwargs = {
        "base_url": API_BASE_URL,
        "headers": headers,
        "timeout": timeout,
        "event_hooks": {"response": [log_response]},
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    with httpx.Client(**client_kwargs) as client:
        response = client.get(url)
        assert response.status_code == 200, (
            f"GET {url} returned {response.status_code}: {response.text}"
        )
        data = response.json()
        assert "provider" in data, f"Response missing 'provider' field: {data}"
        return data


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def direct_headers() -> dict:
    """Headers for a direct (no proxy) authenticated request."""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


@pytest.fixture
def direct_client(direct_headers):
    """Authenticated httpx client without proxy (server sees the dev machine's IP)."""
    return httpx.Client(
        base_url=API_BASE_URL,
        headers=direct_headers,
        timeout=30.0,
        event_hooks={"response": [log_response]},
    )


# =============================================================================
# Tests: Provider config endpoint — basic
# =============================================================================

@pytest.mark.integration
def test_config_returns_valid_provider(direct_client):
    """
    /v1/payments/config must return a valid provider name without any override.
    Valid providers are 'stripe' and 'polar'.
    This also verifies the endpoint is reachable and authenticated.
    """
    response = direct_client.get("/v1/payments/config")
    assert response.status_code == 200, f"Config endpoint failed: {response.text}"
    data = response.json()

    assert "provider" in data, f"Response missing 'provider': {data}"
    assert data["provider"] in ("stripe", "polar"), (
        f"Unexpected provider '{data['provider']}' — expected 'stripe' or 'polar'"
    )
    print(f"\n[CONFIG] Default provider (dev machine IP): {data['provider']}")


@pytest.mark.integration
def test_config_stripe_override(direct_client):
    """
    ?provider_override=stripe must always return Stripe regardless of caller IP.
    This validates the switch button logic (non-EU user switching to EU/Stripe).
    """
    response = direct_client.get("/v1/payments/config?provider_override=stripe")
    assert response.status_code == 200, f"Config with stripe override failed: {response.text}"
    data = response.json()

    assert data["provider"] == "stripe", (
        f"Expected 'stripe' with override, got '{data['provider']}'"
    )
    # Stripe must return a non-empty public key
    assert data.get("public_key"), (
        "Stripe config must include a non-empty 'public_key' (Stripe publishable key)"
    )
    assert data["public_key"].startswith("pk_"), (
        f"Stripe public key should start with 'pk_', got: {data['public_key']}"
    )
    print(f"\n[CONFIG] Stripe override: provider={data['provider']}, key={data['public_key'][:12]}...")


@pytest.mark.integration
def test_config_polar_override(direct_client):
    """
    ?provider_override=polar must return Polar (or Stripe fallback if Polar is not yet
    configured in Vault). Verifies the override query param is respected.

    When Polar Vault secrets ARE configured:
      - provider == 'polar'
      - public_key == '' (Polar uses checkout URL, not a client-side key)

    When Polar Vault secrets are NOT yet configured (expected during initial setup):
      - provider == 'stripe' (graceful fallback)
      - public_key is set
    """
    response = direct_client.get("/v1/payments/config?provider_override=polar")
    assert response.status_code == 200, f"Config with polar override failed: {response.text}"
    data = response.json()

    assert data["provider"] in ("stripe", "polar"), (
        f"Unexpected provider '{data['provider']}'"
    )
    if data["provider"] == "polar":
        # Polar configured: no client-side key needed (embedded checkout uses URL)
        assert data.get("public_key", "") == "", (
            f"Polar config should return empty public_key, got: {data.get('public_key')}"
        )
        print("\n[CONFIG] Polar override: Polar is configured ✓")
    else:
        # Polar not yet configured: fallback to Stripe
        print(
            "\n[CONFIG] Polar override: Polar secrets not yet in Vault — "
            f"fell back to '{data['provider']}' (expected until Polar is configured)"
        )


@pytest.mark.integration
def test_config_invalid_override_falls_back(direct_client):
    """
    An invalid ?provider_override value should be ignored and fall back to
    IP-based detection (return 200 with a valid provider, not 422 or 500).
    """
    response = direct_client.get("/v1/payments/config?provider_override=invalid_provider")
    assert response.status_code == 200, (
        f"Config with invalid override should still return 200: {response.text}"
    )
    data = response.json()
    assert data["provider"] in ("stripe", "polar"), (
        f"Invalid override should fall back to a valid provider, got: {data['provider']}"
    )
    print(f"\n[CONFIG] Invalid override fell back to: {data['provider']}")


# =============================================================================
# Tests: IP-based geo-routing via Webshare residential proxies
#
# NOTE ON COUNTRY TARGETING:
#   Webshare's country-specific routing (username-country-XX suffix) requires
#   a Premium plan. On a basic plan, the proxy rotates randomly across their pool.
#   To enable country-targeting, set WEBSHARE_COUNTRY_TARGETING=1 in .env and
#   upgrade your Webshare plan.
#
#   Without country targeting, these tests verify that:
#     1. The /config endpoint is reachable via a residential proxy IP
#     2. The endpoint returns a valid provider for whatever IP the proxy assigns
#     3. Provider overrides work even when routed through the proxy
#
#   With country targeting (WEBSHARE_COUNTRY_TARGETING=1), tests additionally
#   verify that specific country → provider mappings are correct.
# =============================================================================

@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
def test_proxy_request_returns_valid_provider():
    """
    A request through Webshare's rotating residential proxy must reach
    /v1/payments/config and return a valid provider.

    This verifies:
    1. The API accepts requests from residential proxy IPs (no IP blocking)
    2. Geo-detection runs and returns a valid provider for the proxy's exit IP
    3. The proxy connectivity itself is working for payment config calls
    """
    proxy_url = make_webshare_proxy_url()
    print("\n[PROXY] Testing /config via Webshare rotating residential proxy (via docker exec)...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url)
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            print(f"[PROXY] Attempt {attempt + 1} failed: {e}")
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    assert data["provider"] in ("stripe", "polar"), (
        f"Proxy request should return a valid provider, got: {data['provider']}"
    )
    print(f"[PROXY] Residential proxy exit IP → provider: {data['provider']} ✓")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
def test_stripe_override_via_proxy():
    """
    ?provider_override=stripe must return Stripe even when routed through a proxy.
    Validates that the override mechanism works regardless of IP origin.
    """
    proxy_url = make_webshare_proxy_url()
    print("\n[PROXY+OVERRIDE] Testing stripe override via Webshare proxy (via docker exec)...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url, provider_override="stripe")
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    print(f"[PROXY+OVERRIDE] Proxy IP + stripe override → provider: {data['provider']}")
    assert data["provider"] == "stripe", (
        f"Stripe override via proxy must return 'stripe', got '{data['provider']}'"
    )
    assert data.get("public_key", "").startswith("pk_"), (
        f"Stripe must return a publishable key via proxy, got: {data.get('public_key')}"
    )
    print("[PROXY+OVERRIDE] Stripe override respected via residential proxy ✓")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
def test_polar_override_via_proxy():
    """
    ?provider_override=polar via proxy must return Polar (or Stripe fallback
    if Polar is not yet configured in Vault).
    """
    proxy_url = make_webshare_proxy_url()
    print("\n[PROXY+OVERRIDE] Testing polar override via Webshare proxy (via docker exec)...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url, provider_override="polar")
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    print(f"[PROXY+OVERRIDE] Proxy IP + polar override → provider: {data['provider']}")
    if data["provider"] == "polar":
        print("[PROXY+OVERRIDE] Polar override via proxy working ✓")
    else:
        print(
            f"[PROXY+OVERRIDE] Fell back to '{data['provider']}' "
            "(Polar not yet configured in Vault — add SECRET__POLAR__* keys)"
        )
    assert data["provider"] in ("stripe", "polar")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
def test_multiple_proxy_calls_all_return_valid_provider():
    """
    5 consecutive proxy calls must each return a valid provider.
    Each call gets a different residential IP (Webshare rotation).
    Validates that IP rotation doesn't cause intermittent failures in geo-detection.
    """
    proxy_url = make_webshare_proxy_url()
    print("\n[ROTATION] Testing 5 consecutive requests via Webshare rotating proxy (via docker exec)...")

    results = []
    for i in range(5):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url)
            results.append(data["provider"])
            print(f"[ROTATION] Call {i+1}: provider={data['provider']}")
            time.sleep(1)  # Allow proxy rotation between calls
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            print(f"[ROTATION] Call {i+1} failed (non-fatal): {e}")
            results.append("error")

    valid_results = [r for r in results if r != "error"]
    assert len(valid_results) >= 3, (
        f"At least 3 of 5 proxy calls must succeed (connectivity test). Got: {results}"
    )

    invalid_providers = [r for r in valid_results if r not in ("stripe", "polar")]
    assert not invalid_providers, (
        f"All successful calls must return 'stripe' or 'polar', got: {invalid_providers}"
    )
    print(f"[ROTATION] {len(valid_results)}/5 calls succeeded, all returned valid providers ✓")


# =============================================================================
# Tests: Country-specific routing (requires WEBSHARE_COUNTRY_TARGETING=1 + Premium plan)
# =============================================================================

COUNTRY_TARGETING_ENABLED = os.getenv("WEBSHARE_COUNTRY_TARGETING", "").lower() in ("1", "true", "yes")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
@pytest.mark.skipif(not COUNTRY_TARGETING_ENABLED, reason="Set WEBSHARE_COUNTRY_TARGETING=1 and use Webshare Premium to run country-specific geo tests")
def test_eu_de_ip_routes_to_stripe():
    """
    German IP (EU) must route to Stripe.
    Requires Webshare Premium plan + WEBSHARE_COUNTRY_TARGETING=1.
    """
    proxy_url = make_webshare_proxy_url(country="de")
    print("\n[GEO] Testing German IP (DE) → expecting Stripe...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url)
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    print(f"[GEO] DE IP → provider: {data['provider']}")
    assert data["provider"] == "stripe", (
        f"German IP must route to Stripe (EU). Got '{data['provider']}'. "
        f"Check that DE is in EU_STRIPE_COUNTRY_CODES in geo_utils.py."
    )


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
@pytest.mark.skipif(not COUNTRY_TARGETING_ENABLED, reason="Set WEBSHARE_COUNTRY_TARGETING=1 and use Webshare Premium to run country-specific geo tests")
def test_eu_fr_ip_routes_to_stripe():
    """French IP (EU) must route to Stripe. Requires Premium Webshare plan."""
    proxy_url = make_webshare_proxy_url(country="fr")
    print("\n[GEO] Testing French IP (FR) → expecting Stripe...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url)
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    assert data["provider"] == "stripe", f"FR IP must route to Stripe, got '{data['provider']}'"
    print(f"[GEO] FR IP → provider: {data['provider']} ✓")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
@pytest.mark.skipif(not COUNTRY_TARGETING_ENABLED, reason="Set WEBSHARE_COUNTRY_TARGETING=1 and use Webshare Premium to run country-specific geo tests")
def test_eu_gb_ip_routes_to_stripe():
    """UK IP (GB, post-Brexit, still in EU_STRIPE_COUNTRY_CODES) must route to Stripe."""
    proxy_url = make_webshare_proxy_url(country="gb")
    print("\n[GEO] Testing UK IP (GB) → expecting Stripe...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url)
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    assert data["provider"] == "stripe", f"GB IP must route to Stripe, got '{data['provider']}'"
    print(f"[GEO] GB IP → provider: {data['provider']} ✓")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
@pytest.mark.skipif(not COUNTRY_TARGETING_ENABLED, reason="Set WEBSHARE_COUNTRY_TARGETING=1 and use Webshare Premium to run country-specific geo tests")
def test_non_eu_us_ip_routes_to_polar_or_fallback():
    """US IP (non-EU) must route to Polar (or Stripe fallback if Polar not configured)."""
    proxy_url = make_webshare_proxy_url(country="us")
    print("\n[GEO] Testing US IP → expecting Polar or Stripe fallback...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url)
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    print(f"[GEO] US IP → provider: {data['provider']}")
    if data["provider"] == "polar":
        print("[GEO] Polar routing non-EU (US) traffic ✓")
    else:
        print(f"[GEO] US IP fell back to '{data['provider']}' (Polar likely not in Vault yet)")
    assert data["provider"] in ("stripe", "polar")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
@pytest.mark.skipif(not COUNTRY_TARGETING_ENABLED, reason="Set WEBSHARE_COUNTRY_TARGETING=1 and use Webshare Premium to run country-specific geo tests")
def test_non_eu_au_ip_routes_to_polar_or_fallback():
    """Australian IP (non-EU) must route to Polar (or Stripe fallback)."""
    proxy_url = make_webshare_proxy_url(country="au")
    print("\n[GEO] Testing Australian IP (AU) → expecting Polar or Stripe fallback...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url)
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    print(f"[GEO] AU IP → provider: {data['provider']}")
    assert data["provider"] in ("stripe", "polar")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
@pytest.mark.skipif(not COUNTRY_TARGETING_ENABLED, reason="Set WEBSHARE_COUNTRY_TARGETING=1 and use Webshare Premium to run country-specific geo tests")
def test_eu_de_with_polar_override():
    """
    EU IP (DE) + ?provider_override=polar must respect override.
    Simulates an EU user clicking 'Pay with a non-EU card instead'.
    """
    proxy_url = make_webshare_proxy_url(country="de")
    print("\n[GEO+OVERRIDE] EU IP (DE) + polar override → expecting Polar...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url, provider_override="polar")
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    print(f"[GEO+OVERRIDE] DE + polar override → provider: {data['provider']}")
    if data["provider"] == "polar":
        print("[GEO+OVERRIDE] Override respected for EU IP ✓")
    else:
        print(f"[GEO+OVERRIDE] Fell back to '{data['provider']}' (Polar not in Vault yet)")
    assert data["provider"] in ("stripe", "polar")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_WEBSHARE, reason="Webshare credentials not available from Vault via docker exec")
@pytest.mark.skipif(not COUNTRY_TARGETING_ENABLED, reason="Set WEBSHARE_COUNTRY_TARGETING=1 and use Webshare Premium to run country-specific geo tests")
def test_non_eu_us_with_stripe_override():
    """
    Non-EU IP (US) + ?provider_override=stripe must return Stripe.
    Simulates a non-EU user clicking 'Pay with an EU card instead'.
    Override must win over IP-based detection.
    """
    proxy_url = make_webshare_proxy_url(country="us")
    print("\n[GEO+OVERRIDE] Non-EU IP (US) + stripe override → expecting Stripe...")

    last_error = None
    for attempt in range(3):
        try:
            data = get_payment_config_via_docker(proxy_url=proxy_url, provider_override="stripe")
            break
        except ProxyAuthError as e:
            pytest.skip(str(e))
        except Exception as e:
            last_error = e
            time.sleep(2)
    else:
        pytest.fail(f"All proxy attempts failed: {last_error}")

    print(f"[GEO+OVERRIDE] US + stripe override → provider: {data['provider']}")
    assert data["provider"] == "stripe", (
        f"Stripe override must win over non-EU IP detection. Got '{data['provider']}'"
    )
    assert data.get("public_key", "").startswith("pk_")
    print("[GEO+OVERRIDE] Stripe override for non-EU IP ✓")
