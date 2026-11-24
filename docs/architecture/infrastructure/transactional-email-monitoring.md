# Transactional email monitoring

All OpenMates emails (signup and login codes, recovery, receipts and invoices,
newsletters, deletion and security notices, admin alerts) go out through one
Brevo account. Production and development share it; each email carries an
`environment:<name>` tag, so Brevo's event log shows which server sent it.

## Where the key lives

| Caller | Key | Network path |
|---|---|---|
| API and Celery workers (prod and dev) | Vault `kv/data/providers/brevo` → `api_key` | container IPv4 egress |
| Dev-host scripts (`run_tests.py` alerts, accessibility and contract audit summaries, signup email smoke, `prod_email_health.py`) | `BREVO_API_KEY` in the dev `.env` | `scripts/brevo_ipv4.py`, IPv4 only |

Brevo's **Authorised IPs** setting allows API calls only from listed
addresses. The dev host prefers IPv6, and its IPv6 address is not listed, so
plain host calls fail with HTTP 401 "unrecognised IP address" even with a valid
key. That is why host scripts must call Brevo through `scripts/brevo_ipv4.py`
(TASK-427). Containers use the IPv4 egress and are not affected.

## Uptime monitor

The dev-host production uptime monitor uses production Brevo account probes
and real send results. See [Production uptime monitoring](production-uptime-monitoring.md)
for the alert policy, credential locations, and enablement.

## Legacy hourly check

`scripts/prod_smoke_cron.py free-hourly` runs `scripts/prod_email_health.py`
before it dispatches the browser smoke. The check fails when any of these is
true:

1. Production's own Brevo health check (`/v1/status`, service `brevo`) is not
   `operational`. That check runs on the prod server with the prod Vault key,
   so it catches a revoked key or an IP block on prod.
2. `GET /v3/account` fails, or fewer than 200 send credits are left.
3. In the last two hours at least 3 production emails, and at least 25% of
   production requests, ended in Brevo `error` or `blocked` events. Hard
   bounces are recipient problems and do not count.

Failures post to `DISCORD_WEBHOOK_PROD_SMOKE` when the state changes and every
six hours while it stays failing; a recovery is posted once. State:
`test-results/hourly-prod/email-health-state.json`. Manual run:
`python3 scripts/prod_email_health.py --dry-run` (with the dev `.env` loaded).

## When it fails

- **HTTP 401 "unrecognised IP address"**: add the address named in the message
  in Brevo → Security → Authorised IPs, or make the caller use IPv4.
- **HTTP 401 "Key not found"**: the key was revoked. Create a new API key in
  Brevo → SMTP & API → API keys, store it in Vault `kv/data/providers/brevo`
  (`api_key`) on the affected server, and update the dev `.env`.
- **Low credits**: upgrade or top up the Brevo plan.
- **Error rate**: read the Brevo transactional log for the refused emails and
  the prod `core-worker` / `task-worker` logs (`debug.py logs --o2 --prod`).
