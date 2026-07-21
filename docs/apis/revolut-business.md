# Revolut Business Sandbox

Purpose: document the read-only Revolut Business Sandbox credentials used by the Finance `check_accounts` connected-account provider.

Run the manual probe with:

```bash
/home/superdev/projects/OpenMates/.venv/bin/python3 scripts/api_tests/test_revolut_business_api.py --test all
```

Use the same names in `.env` or Vault. Prefer the `SANDBOX` names for development:

| Purpose | `.env` / Vault name |
| --- | --- |
| Refresh token | `REVOLUT_BUSINESS_SANDBOX_REFRESH_TOKEN` |
| Client ID | `REVOLUT_BUSINESS_SANDBOX_CLIENT_ID` |
| Private key PEM | `REVOLUT_BUSINESS_SANDBOX_PRIVATE_KEY_PEM` |
| Private key file path | `REVOLUT_BUSINESS_SANDBOX_PRIVATE_KEY_FILE` |
| Manual client assertion override | `REVOLUT_BUSINESS_SANDBOX_CLIENT_ASSERTION` |
| Short-lived access token override | `REVOLUT_BUSINESS_SANDBOX_ACCESS_TOKEN` |

Fallback production-shaped names are also accepted by the manual script for local operator convenience: `REVOLUT_BUSINESS_REFRESH_TOKEN`, `REVOLUT_BUSINESS_CLIENT_ID`, `REVOLUT_BUSINESS_PRIVATE_KEY_PEM`, `REVOLUT_BUSINESS_PRIVATE_KEY_FILE`, `REVOLUT_BUSINESS_CLIENT_ASSERTION`, and `REVOLUT_BUSINESS_ACCESS_TOKEN`.

Only one assertion credential is required: either `REVOLUT_BUSINESS_SANDBOX_PRIVATE_KEY_PEM`, `REVOLUT_BUSINESS_SANDBOX_PRIVATE_KEY_FILE`, or `REVOLUT_BUSINESS_SANDBOX_CLIENT_ASSERTION`. The generated client assertion is short-lived and signed locally; the script never prints secret values.

Register the OAuth redirect URI on the app host, not the API host:

| Environment | Redirect URI |
| --- | --- |
| Sandbox/dev | `https://app.dev.openmates.org/oauth/revolut-business/callback` |
| Production | `https://openmates.org/oauth/revolut-business/callback` |

After registering the redirect URI and certificate in the Revolut Business Developer Portal, generate the consent URL with:

```bash
openmates connect-account revolut-business consent-url --client-id <client-id>
```

The callback page shows a copyable `openmates connect-account revolut-business exchange-code ...` command for completing the local sandbox token exchange.

Revolut Business also requires the API certificate's `Production IP whitelist` to contain the public egress IP of the OpenMates server that calls Revolut. For OpenMates cloud, use the IP shown by the web setup flow or by:

```bash
openmates connect-account revolut-business
```

For self-hosted OpenMates, whitelist the self-hosted server's public outbound IP. Set `REVOLUT_BUSINESS_SERVER_EGRESS_IPS` on the API server when the deployment uses a known static egress IP or multiple NAT IPs; otherwise OpenMates detects the current public egress IP during setup.
