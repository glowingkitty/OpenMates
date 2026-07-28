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

## Dev Bank-Transfer Auto-Settlement

The dev API does not read the operator probe names above. For automatic SEPA settlement on `https://api.dev.openmates.org`, add these Vault-importer names to `.env`:

| Purpose | `.env` / Vault importer name |
| --- | --- |
| Webhook signing secret | `SECRET__REVOLUT_BUSINESS__SANDBOX_WEBHOOK_SECRET` |
| EUR account IBAN | `SECRET__REVOLUT_BUSINESS__SANDBOX_IBAN` |
| EUR account BIC | `SECRET__REVOLUT_BUSINESS__SANDBOX_BIC` |
| EUR account ID | `SECRET__REVOLUT_BUSINESS__SANDBOX_ACCOUNT_ID` |
| Client ID | `SECRET__REVOLUT_BUSINESS__SANDBOX_CLIENT_ID` |
| Refresh token | `SECRET__REVOLUT_BUSINESS__SANDBOX_REFRESH_TOKEN` |
| Private key PEM | `SECRET__REVOLUT_BUSINESS__SANDBOX_PRIVATE_KEY_PEM` |
| Legal account holder name | `SECRET__REVOLUT_BUSINESS__SANDBOX_ACCOUNT_HOLDER_NAME` |

`SECRET__REVOLUT_BUSINESS__SANDBOX_PRIVATE_KEY_PEM` should contain the PEM with `\n` line breaks. `SECRET__REVOLUT_BUSINESS__SANDBOX_CLIENT_ASSERTION` can replace it temporarily, but assertions expire and are not suitable as the normal dev setup. `SECRET__REVOLUT_BUSINESS__SANDBOX_PRIVATE_KEY_FILE` is only for local operator scripts; the API service does not read file paths from Vault.

After changing `.env`, import the values into Vault and restart the API process:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d --force-recreate vault-setup
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d api
```

Then run the read-only readiness check before any mutating sandbox topup:

```bash
.venv/bin/python3 scripts/api_tests/test_revolut_business_bank_transfer_settlement.py \
  --api-url https://api.dev.openmates.org \
  --scenarios exact,overpaid,underpaid-complete,duplicate-completed-reference
```

Register the OAuth redirect URI on the app host, not the API host:

| Environment | Redirect URI |
| --- | --- |
| Sandbox/dev | `https://app.dev.openmates.org/oauth/revolut-business/callback` |
| Production | `https://openmates.org/oauth/revolut-business/callback` |

The normal setup path is one interactive command:

```bash
openmates connect-account revolut-business
```

After registering the redirect URI, public certificate, and server IP in Revolut, click Revolut's Enable button. The OpenMates callback page shows only the short authorization code; paste that code back into the running OpenMates connection flow. `consent-url` and `exchange-code` remain developer fallbacks, not the normal account-connection path.

Revolut Business also requires the API certificate's `Production IP whitelist` to contain the public egress IP of the OpenMates server that calls Revolut. For OpenMates cloud, use the IP shown by:

```bash
openmates connect-account revolut-business
```

For self-hosted OpenMates, whitelist the self-hosted server's public outbound IP. Set `REVOLUT_BUSINESS_SERVER_EGRESS_IPS` on the API server when the deployment uses a known static egress IP or multiple NAT IPs; otherwise OpenMates detects the current public egress IP during setup.
