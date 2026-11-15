# status.openmates.org: external status server

One small VPS outside our own infrastructure: netcup VPS pico, Nuremberg. It checks production from the outside, publishes the public status page and sends alerts.
Design: `docs/architecture/infrastructure/status-page.md`. Contract: `specifications/architecture/external-status-monitoring`.

```
gatus   1-min HTTP checks + provider status feeds; stores results (loopback only)
agent   real chat/skill probes, escalating alerts (Discord, then email), status.json
caddy   TLS, static page (site/) and /data/status.json; no access log
```

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
python3 scripts/status_server.py netcup-login             # one browser approval; stores the netcup API token
python3 scripts/status_server.py secret set monitor_api_key  # monitoring account's API key, hidden input
python3 scripts/status_server.py provision                # dry run: shows the server and IP
python3 scripts/status_server.py provision --wipe         # installs Debian 13 with our deploy key (erases disk)
python3 scripts/status_server.py deploy                   # copies this folder, writes .env from Vault, starts it
scripts/status-server-watch-setup.sh                      # dev-server cross-check every 5 minutes
```

Secrets live in Vault at `kv/data/providers/status_monitor`:
- `monitor_api_key`
- `netcup_refresh_token`
- `probe_token`, auto-generated
- `gatus_external_token`, auto-generated

On the VPS they exist only in `/opt/openmates-status/.env` (mode 600).

Production needs, once and with owner approval:
- the same `probe_token` and the monitoring account's user id in production Vault (`status_monitor.probe_token`, `status_monitor.account_user_ids`);
- `OPENMATES_HEALTH_ALERTS_DELEGATED=true`;
- a deployed `GET /v1/health/liveness`. After that, set `"ai_worker_check": true` in `~/.config/openmates/status_server.json` and deploy again.

Until production has the probe token, the anonymous probe uses the normal free allowance. That allowance runs out within the day, so the chat-without-account check would fail. Keep the agent's `MONITOR_PROBE_TOKEN` and production's in sync.

DNS: an `A` record (plus `AAAA`) for `status.openmates.org` pointing to the VPS, set at the registrar. Caddy gets the certificate on first request.

Brevo: email alerts go through the Brevo API, which accepts only authorized IPs. Add the VPS's IPv4 and IPv6 addresses under Brevo → Security → Authorized IPs. Otherwise backup emails fail with HTTP 401 and only Discord alerts arrive.

Gatus UI (internal): `ssh -i ~/.ssh/openmates_status_ed25519 -L 8080:127.0.0.1:8080 root@<ip>`, then open http://localhost:8080.
