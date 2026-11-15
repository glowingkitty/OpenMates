# status.openmates.org: external status server

One small VPS outside our own infrastructure: UpCloud Starter (1 vCPU, 1 GB, 10 GB), Amsterdam, Ubuntu 24.04 LTS. A different company and network than production. The owner creates it by hand in the UpCloud control panel; no UpCloud API token is stored. It checks production from the outside, publishes the public status page and sends alerts. It runs there only, never next to production, so it stays up when production is down.
Design: `docs/architecture/infrastructure/status-page.md`. Contract: `specifications/architecture/external-status-monitoring`.

One image, `ghcr.io/glowingkitty/openmates-status` (`Dockerfile`, published by CI from `dev` and `main`):

```
gatus   1-min HTTP checks + provider status feeds; stores results (loopback only)
agent   real chat/skill probes, escalating alerts (Discord, then email), status.json
caddy   TLS, static page (site/) and /data/status.json; no access log
```

The repository and the image contain no secrets, tokens or server addresses. They come from Vault at setup time.

## What is checked

| Component (public)  | Checks                                                                     | Every   |
|---------------------|----------------------------------------------------------------------------|---------|
| Web app             | web app, app shell, link previews                                          | 1 min   |
| API                 | API reachability                                                           | 1 min   |
| AI chat             | AI-worker liveness; real chat without an account; real chat with an account | 1/5/5 min |
| Voice calls         | AI-worker liveness + Mistral status                                        | 1/5 min |
| Apps and skills     | real web-search skill run                                                  | 30 min  |
| File uploads        | upload service                                                             | 1 min   |
| External providers  | official status feeds (OpenAI, Anthropic, Google Cloud, Mistral, Groq, Cerebras, Stripe, Brevo, Vercel) | 5 min |

Alert-only checks come from production `/v1/health`, one per configured provider, app and service. They replace the backend's own Discord transition posts once production sets `OPENMATES_HEALTH_ALERTS_DELEGATED=true`.

Alerts: 2 failures in a row trigger a "DOWN" message. "STILL DOWN … for X" reminders follow at 15 min, at 1 h, then every 3 h. One "RESOLVED … after X" message is sent when it recovers. Alerts go to Discord first and also by email.

## Operating it (from the dev server, canonical checkout)

```bash
python3 scripts/status_server.py secret status            # which secrets exist (never values)
python3 scripts/status_server.py secret set monitor_api_key  # monitoring account's API key, hidden input
python3 scripts/status_server.py publish-config           # tokens, Discord webhook, alert email into Vault (via .env + vault-setup)
python3 scripts/status_server.py ssh-key                  # deploy public key to paste when creating the UpCloud server
python3 scripts/status_server.py setup --host <IPv4> [--image <ref>]  # first setup and config changes
scripts/status-server-watch-setup.sh                      # dev-server cross-check every 5 minutes
```

Creating the server (UpCloud control panel): Deploy server → Starter plan 1 vCPU / 1 GB / 10 GB → location Amsterdam (NL-AMS1) → Ubuntu Server 24.04 LTS → login method SSH key (the output of `ssh-key`) → hostname `status-openmates`. Leave the UpCloud firewall off: it is stateless and would also block the server's own outgoing checks unless every reply is allowed; the setup turns on the server's own firewall (ufw: 22, 80, 443). `--image` defaults to `…:main`; before the first main release pass a published tag such as `…:sha-<dev commit>`. `setup` refuses an image that cannot be pulled without login.

On the VPS (as root):

```
openmates-status-setup        # update: pull the newest image and restart (keeps status.env)
```

`setup.sh` is installed as `/usr/local/bin/openmates-status-setup`. On the first run it installs Docker, a firewall (22/80/443) and automatic security updates. On every run it pulls the image, writes `/opt/openmates-status/status.env` (mode 600) when new config arrives, installs the compose file from the image and restarts. Optional `/opt/openmates-status/settings.env`: `STATUS_IMAGE` (default `…:main`), or `VAULT_ADDR` plus `VAULT_TOKEN_FILE` if the VPS should read Vault itself.

Secrets live in Vault at `kv/data/providers/status_monitor`:
- `monitor_api_key`
- `probe_token`, auto-generated
- `gatus_external_token`, auto-generated
- `discord_webhook_url`, `alert_email_to`, `status_domain`, `ai_worker_check` (written by `publish-config`)

The email key is read from `kv/data/providers/brevo`. On the VPS the values exist only in `/opt/openmates-status/status.env` (mode 600). `status_agent/vault_env.py` decides which keys go there.

Production needs, once and with owner approval:
- the same `probe_token` and the monitoring account's user id in production Vault (`status_monitor.probe_token`, `status_monitor.account_user_ids`);
- `OPENMATES_HEALTH_ALERTS_DELEGATED=true`;
- a deployed `GET /v1/health/liveness`. After that, run `publish-config --ai-worker-check on` and `setup` again.

Until production has the probe token, the anonymous probe uses the normal free allowance. That allowance runs out within the day, so the chat-without-account check would fail. Keep the agent's `MONITOR_PROBE_TOKEN` and production's in sync.

DNS: an `A` record (plus `AAAA`) for `status.openmates.org` pointing to the VPS, set at the registrar. Caddy gets the certificate on first request.

Brevo: email alerts go through the Brevo API, which accepts only authorized IPs. Add the VPS's IPv4 and IPv6 addresses under Brevo → Security → Authorized IPs. Otherwise backup emails fail with HTTP 401 and only Discord alerts arrive.

Gatus UI (internal): `ssh -i ~/.ssh/openmates_status_ed25519 -L 8080:127.0.0.1:8080 root@<ip>`, then open http://localhost:8080.
