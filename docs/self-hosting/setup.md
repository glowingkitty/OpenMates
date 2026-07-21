---
status: active
doc_type: how-to
audience:
  - technical-users
last_verified: 2026-07-16
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

# Self-Host OpenMates

This guide is for people running their own OpenMates instance outside the official OpenMates cloud. You control the server, Docker stack, `.env` file, domains, provider keys, and backups.

The default setup uses the `openmates` CLI and prebuilt Docker images. You do not need Git or an OpenMates source checkout unless you choose source mode.

## What You Get

- Web app: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Invite-only signup by default
- Local secrets generated during install
- Optional API-based or local AI models
- CLI commands for start, stop, logs, status, updates, backups, and reset

OpenMates can start without AI provider keys. The app and backend will run, but chat and model features stay unavailable until you add an LLM provider key or a local OpenAI-compatible model.

## Requirements

- Linux server or workstation. Ubuntu/Debian is recommended.
- Docker with Docker Compose support.
- Node.js/npm for the `openmates` CLI.
- 4 GB RAM minimum. 8 GB or more is recommended.
- 20 GB or more free disk space.
- Internet access to download npm packages and Docker images.

Provider API keys are optional for installation. Add them later when you want AI chat, model processing, or provider-backed skills. Provider-backed features that require a missing API key are hidden or disabled by default until the key is configured.

The runtime uses one canonical `.env` file. To avoid editing a large file by hand, use the CLI env commands:

```
openmates server env list providers
openmates server env set SECRET__OPENAI__API_KEY
openmates server env check
openmates server env doctor
```

Copy selected keys into `.env` manually, or prefer `openmates server env set <KEY>` so the CLI backs up `.env`, writes restricted permissions, and redacts secret values in output. Provider setup guidance should come from provider metadata rather than extra env files.

## Quick Start

Install the CLI:

```bash
npm install -g openmates
```

Create a self-hosted runtime directory:

```bash
openmates server install --path ~/openmates
```

Start OpenMates:

```bash
openmates server start --path ~/openmates
```

Open the web app in your browser:

```text
http://localhost:5173
```

Check the backend:

```bash
curl http://localhost:8000/health
```

The first start downloads several GB of Docker images from `ghcr.io/glowingkitty`. Later starts and updates reuse Docker's image cache.

## Create Your First User

The installer prints the first signup invite code. It is also saved in `~/openmates/.env` as `SELF_HOST_FIRST_INVITE_CODE`.

1. Open `http://localhost:5173`.
2. Sign up with the invite code.
3. Promote your account from the server terminal:

```bash
openmates server make-admin your@email.com --path ~/openmates
```

The first signup creates a normal user, not an admin. After promotion, refresh the app. The `Server` and `Logs` settings entries should appear after the next auth check.

You are done with the base setup when:

- `http://localhost:5173` loads.
- `curl http://localhost:8000/health` returns healthy.
- You can sign in.
- Admin settings appear after `make-admin`.

## Optional: Enable AI

### API Provider Keys

Edit the generated `.env` file:

```bash
nano ~/openmates/.env
```

Add at least one real LLM provider key:

```env
SECRET__OPENAI__API_KEY=sk-...
SECRET__ANTHROPIC__API_KEY=sk-ant-...
SECRET__GOOGLE_AI_STUDIO__API_KEY=...
```

Restart OpenMates:

```bash
openmates server restart --path ~/openmates
```

Provider keys for search, mail, or other non-model integrations enable only those integrations. They do not make AI model processing available.

### Local AI Models

OpenMates can use Ollama, LM Studio, or another OpenAI-compatible local runtime:

```bash
openmates server ai models add
openmates server restart --path ~/openmates
```

The setup prompts for runtime, base URL, installed model ID, model creator, display name, context window, and model capabilities. It tests the model before saving it.

Common local runtime URLs:

| Runtime | Default base URL |
| --- | --- |
| Ollama | `http://host.docker.internal:11434/v1` |
| LM Studio | `http://host.docker.internal:1234/v1` |

Use `openmates server ai models list|test|remove` to manage saved local models. Local self-hosted models charge `0` credits.

## Common Commands

| Task | Command |
| --- | --- |
| Status | `openmates server status --path ~/openmates` |
| Logs | `openmates server logs --path ~/openmates --tail 200` |
| Follow API logs | `openmates server logs --path ~/openmates --container api --follow` |
| Restart | `openmates server restart --path ~/openmates` |
| Stop | `openmates server stop --path ~/openmates` |
| Preview update | `openmates server update --path ~/openmates --dry-run` |
| Update | `openmates server update --path ~/openmates` |
| Backup | `openmates server backup --path ~/openmates --role core` |
| Uninstall | `openmates server uninstall --path ~/openmates --yes` |

Backups contain secrets. Store them on encrypted disks or move them to a secure backup location.

See [CLI server management](../user-guide/cli/server-management.md) for the full command reference.

## Images And Runtime Containers

OpenMates publishes a smaller set of GHCR images than the number of runtime containers in the generated Compose file. Several worker containers reuse the `openmates-api` image with different commands and queues.

| Runtime container | Image |
| --- | --- |
| `api` | `ghcr.io/glowingkitty/openmates-api` |
| `task-worker` | `ghcr.io/glowingkitty/openmates-api` |
| `app-ai-worker` | `ghcr.io/glowingkitty/openmates-api` |
| `app-images-worker` | `ghcr.io/glowingkitty/openmates-api` |
| `openmates-docs-worker` | `ghcr.io/glowingkitty/openmates-docs-worker` |
| `webapp` | `ghcr.io/glowingkitty/openmates-webapp` |
| `directus` | `ghcr.io/glowingkitty/openmates-directus` |
| `uploads` | `ghcr.io/glowingkitty/openmates-uploads` |
| `preview` | `ghcr.io/glowingkitty/openmates-preview` |

Install, start, update, and backup through the `openmates server` commands so the CLI can keep container names, image tags, secrets, and generated Compose files in sync.

## Production Setup

For a public server, put OpenMates behind a reverse proxy such as Caddy, Traefik, or Nginx and use HTTPS.

Example Caddy shape:

```caddyfile
api.example.com {
    reverse_proxy localhost:8000
}

app.example.com {
    reverse_proxy localhost:5173
}
```

Set your public web app origin in `~/openmates/.env` before restarting:

```env
PRODUCTION_URL="https://app.example.com"
```

Use comma-separated origins if you have more than one trusted web origin.

### Signup Modes

The default install uses invite codes only. Change signup mode in `~/openmates/.env`, then restart.

| Mode | Best for | Required |
| --- | --- | --- |
| `invite_only` | Private servers | Valid invite code |
| `domain_allowlist` | Teams with one email domain | Allowed email domain |
| `invite_and_domain` | Restricted teams | Invite code and allowed email domain |

### Security Checklist

- Keep Docker and the host OS updated.
- Do not commit or share `~/openmates/.env`.
- Restrict database, Redis, Directus, and monitoring ports to trusted networks.
- Back up Docker volumes before updates.
- Rotate provider API keys if `.env` is exposed.
- Configure a small swap file on production hosts to reduce the chance of abrupt OOM kills during short memory spikes.

See [Server Hardening](server-hardening.md) for public-facing server recommendations.

## Advanced Installs

Most self-hosters should use the default install command from Quick Start. Use the options below only when you need a specific deployment shape.

### Observability Profile

The default `core` role supports `minimal`, `standard`, and `production` profiles. Use `production` when you want OpenObserve, Promtail, Prometheus, and cAdvisor:

```bash
openmates server install --role core --profile production --path ~/openmates
```

Use `--with-alerts` to add Alertmanager.

### Satellite Roles

Install only a specific role when you split services across VMs:

```bash
openmates server install --role upload --path /opt/openmates-upload
openmates server install --role preview --path /opt/openmates-preview
```

### Source Mode

Source mode is for contributors testing an existing checkout or rebuilding Docker images locally:

```bash
openmates server install --from-source --path ~/openmates-source
openmates server install --source-path /path/to/OpenMates --path /tmp/openmates-selfhost
```

Source mode requires Git for clone-based installs and updates.

### Admin UIs

To include admin UIs such as Directus CMS and Grafana, start with overrides:

```bash
openmates server start --path ~/openmates --with-overrides
```

## Troubleshooting

### Server Does Not Start

- Check Docker is running: `docker info`.
- Check port conflicts: `lsof -i :5173` and `lsof -i :8000`.
- Inspect logs: `openmates server logs --path ~/openmates --tail 200`.

### AI Chat Does Not Work

- Check server status: `curl http://localhost:8000/v1/settings/server-status`.
- If `ai_models_configured` is `false`, add an LLM provider API key or local model and restart.
- Placeholder values such as `IMPORTED_TO_VAULT` do not count as runnable LLM keys.

### Backend Is Unreachable From The Browser

- Confirm the API health endpoint: `curl http://localhost:8000/health`.
- If serving from another domain, configure your reverse proxy, frontend API URL, and `PRODUCTION_URL` consistently.
- Check browser console errors for blocked CORS or mixed-content requests.

### Complete Reset

This deletes server data unless `--keep-data` is used during uninstall:

```bash
openmates server uninstall --path ~/openmates --yes
openmates server install --path ~/openmates
openmates server start --path ~/openmates
```

## Getting Help

- GitHub Issues: report bugs and feature requests.
- Logs: include relevant `openmates server logs` output when asking for help.
- Documentation: see the rest of `docs/self-hosting/` and [CLI server management](../user-guide/cli/server-management.md).
