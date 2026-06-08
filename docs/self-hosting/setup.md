---
status: active
doc_type: how-to
audience:
  - technical-users
last_verified: 2026-06-08
claims:
  - id: self-hosting-cli-detects-openmates-installation-path
    type: unit
    file: frontend/packages/openmates-cli/tests/server.test.ts
    assertion: cli-server-path-resolution-validates-installation
  - id: self-hosting-cli-detects-real-llm-api-key
    type: unit
    file: frontend/packages/openmates-cli/tests/server.test.ts
    assertion: cli-server-requires-real-llm-api-key
  - id: self-hosting-cli-starts-without-provider-keys
    type: e2e
    file: .github/workflows/selfhost-smoke.yml
    assertion: self-host install smoke passes without provider API keys
  - id: self-hosting-signup-admin-smoke
    type: e2e
    file: frontend/apps/web_app/tests/selfhost-smoke.spec.ts
    assertion: invite signup creates a normal user and make-admin promotes that user
coverage:
  policy: assertion-backed
  reviewed_context:
    - frontend/packages/openmates-cli/src/server.ts
    - frontend/packages/openmates-cli/src/serverConfig.ts
    - frontend/apps/web_app/tests/selfhost-smoke.spec.ts
---

# OpenMates Self-Hosting Edition

## Summary

- Use `openmates server` for the default install, start, stop, status, logs, update, reset, and uninstall flow.
- Default installs use prebuilt GHCR images and do not require Git or a source checkout.
- `openmates server start` brings up the backend and the web app. Open the app at `http://localhost:5173`.
- Default installs generate an invite-only signup configuration; edit `.env` if you want a domain allowlist or invite-plus-domain mode.
- The first invite creates a normal user. Promote your account separately with `openmates server make-admin <email>`.
- A fresh self-hosted install can start without provider API keys. AI chat and model processing stay unavailable until you add at least one real LLM provider key.
- The no-key startup path is verified by the GitHub Actions self-host install smoke workflow.

The self-hosted edition currently uses API-based AI providers. Offline model support is planned but is not part of this setup path yet.

## Requirements

- Linux server or workstation. Ubuntu/Debian is recommended.
- Docker with Docker Compose support.
- Node.js/npm.
- 4 GB RAM minimum. 8 GB or more is recommended.
- 20 GB or more free disk space.
- Internet access for Docker images, package installs, and any external AI providers you enable.

Git is only required when you explicitly choose source mode with `--from-source` or `--source-path`.

Provider API keys are optional for installation and startup. Add them when you want AI chat, model processing, or provider-backed skills to work.

## Quick Start

### 1. Install the CLI from npm

```bash
npm install -g openmates
```

### 2. Run the installer

```bash
openmates server install --path ~/openmates
```

The installer prepares a lightweight runtime directory, writes the image-mode Docker Compose file, creates `.env`, generates local secrets, and prints the next command to start the server. It does not clone the OpenMates repository.

By default the stack pulls OpenMates images from `ghcr.io/glowingkitty` using the CLI version tag, for example `v0.11.0-alpha.0`. Expect the first start to download several GB of compressed images; later updates reuse Docker's image cache.

Image-mode install defaults to invite codes only. You can edit `~/openmates/.env` before starting if you want a different signup mode:

| Mode | Best for | Signup requirement |
| --- | --- | --- |
| Invite codes only | Individuals and private servers | Valid invite code |
| Email domain allowlist | Teams with a shared email domain | Allowed email domain |
| Invite code + email domain | More restrictive team/private servers | Both invite code and allowed email domain |

Setup generates and prints the first signup invite code. This invite code creates a normal user, not an admin.

For contributors testing an existing checkout, use source mode:

```bash
openmates server install --from-source --path ~/openmates-source
openmates server install --source-path /path/to/OpenMates --path /tmp/openmates-selfhost
```

Source mode clones or copies a repository, requires Git for clone-based installs and updates, and rebuilds Docker images locally.

### 3. Start the Server

```bash
openmates server start --path ~/openmates
```

Startup without LLM keys is allowed. If no key is present, the CLI prints a warning and starts the stack anyway. The web app and backend should still be reachable, but AI model features remain unavailable.

The default self-host stack exposes:

| Service | URL |
| --- | --- |
| Web app | `http://localhost:5173` |
| Backend API | `http://localhost:8000` |

To include admin UIs such as Directus CMS and Grafana, start with overrides:

```bash
openmates server start --path ~/openmates --with-overrides
```

### 4. Verify the install

```bash
openmates server status --path ~/openmates
curl http://localhost:8000/health
curl http://localhost:8000/v1/settings/server-status
```

For a fresh no-key install, `/v1/settings/server-status` should include:

```json
{
  "is_self_hosted": true,
  "payment_enabled": false,
  "ai_models_configured": false
}
```

### 5. Create your first user and promote admin

Open `http://localhost:5173` in your browser.

If your signup mode uses invite codes, sign up with the first signup invite code printed by `openmates server install`. It is also available in `~/openmates/.env` as `SELF_HOST_FIRST_INVITE_CODE`.

The first signup creates a normal user. After signup, grant admin privileges to your user from the server terminal:

```bash
openmates server make-admin your@email.com --path ~/openmates
```

Keep the browser session open or refresh the app. The `Server` and `Logs` settings entries should appear after the next auth check.

## Adding AI Provider Keys

Edit the generated `.env` file in your install directory:

```bash
nano ~/openmates/.env
```

Add at least one real LLM provider key:

```env
SECRET__OPENAI__API_KEY=sk-...
SECRET__ANTHROPIC__API_KEY=sk-ant-...
SECRET__GOOGLE_AI_STUDIO__API_KEY=...
```

Then restart:

```bash
openmates server restart --path ~/openmates
```

Provider keys for non-model features, such as search or mail providers, enable only those specific integrations. They do not make AI model processing available.

## Common Management Commands

```bash
openmates server status --path ~/openmates
openmates server logs --path ~/openmates --tail 200
openmates server logs --path ~/openmates --container api --follow
openmates server restart --path ~/openmates
openmates server stop --path ~/openmates
openmates server update --path ~/openmates
openmates server uninstall --path ~/openmates --yes
```

For image-mode installs, `openmates server update` pulls newer images and restarts the stack. For source-mode installs, it runs `git pull --ff-only`, rebuilds images, and restarts containers.

See [CLI server management](../cli/server-management.md) for the full command reference.

## Production Notes

### Domains and HTTPS

For public deployments, put OpenMates behind a reverse proxy such as Caddy, Traefik, or Nginx.

Example Caddy shape:

```caddyfile
api.example.com {
    reverse_proxy localhost:8000
}

app.example.com {
    reverse_proxy localhost:5173
}
```

Set production origins and domains in `~/openmates/.env` before restarting. Use HTTPS for any public instance.

### Security checklist

- Keep Docker and the host OS updated.
- Use real random secrets generated by setup; do not commit `.env`.
- Restrict database, Redis, Directus, and monitoring ports to trusted networks.
- Back up Docker volumes before updates.
- Rotate provider API keys if the `.env` file is exposed.

## Troubleshooting

### Server does not start

- Check Docker is running: `docker info`.
- Check port conflicts: `lsof -i :5173` and `lsof -i :8000`.
- Inspect logs: `openmates server logs --path ~/openmates --tail 200`.

### Web app loads but AI chat does not work

- Check server status: `curl http://localhost:8000/v1/settings/server-status`.
- If `ai_models_configured` is `false`, add an LLM provider API key and restart.
- Placeholder values such as `IMPORTED_TO_VAULT` do not count as runnable LLM keys.

### Signup mode needs to change

Edit `~/openmates/.env`, then restart:

```env
SELF_HOST_SIGNUP_MODE=invite_only
SELF_HOST_SIGNUP_ALLOWED_DOMAINS=
SELF_HOST_FIRST_INVITE_CODE=1234-5678-9012
```

Supported signup modes are `invite_only`, `domain_allowlist`, and `invite_and_domain`.

### Backend is unreachable from the browser

- Confirm the API health endpoint: `curl http://localhost:8000/health`.
- If serving from another domain, configure your reverse proxy and frontend API URL consistently.
- Check browser console errors for blocked CORS or mixed-content requests.

### Complete reset

This deletes server data unless `--keep-data` is used during uninstall:

```bash
openmates server uninstall --path ~/openmates --yes
openmates server install --path ~/openmates
openmates server start --path ~/openmates
```

## Getting Help

- GitHub Issues: report bugs and feature requests.
- Logs: include relevant `openmates server logs` output when asking for help.
- Documentation: see the rest of `docs/self-hosting/` and `docs/cli/`.
