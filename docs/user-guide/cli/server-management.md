---
status: active
doc_type: reference
audience:
  - technical-users
  - contributors
last_verified: 2026-08-25
claims:
  - id: cli-server-config-saves-loads-and-removes
    type: unit
    file: frontend/packages/openmates-cli/tests/server.test.ts
    assertion: cli-server-config-saves-loads-and-removes
  - id: cli-server-path-resolution-validates-installation
    type: unit
    file: frontend/packages/openmates-cli/tests/server.test.ts
    assertion: cli-server-path-resolution-validates-installation
  - id: cli-server-compose-uses-base-and-optional-overrides
    type: unit
    file: frontend/packages/openmates-cli/tests/server.test.ts
    assertion: cli-server-compose-uses-base-and-optional-overrides
  - id: cli-server-detects-real-llm-api-key
    type: unit
    file: frontend/packages/openmates-cli/tests/server.test.ts
    assertion: cli-server-requires-real-llm-api-key
  - id: cli-server-source-path-installs-from-local-checkout
    type: e2e
    file: .github/workflows/selfhost-smoke.yml
    assertion: openmates server install --source-path starts self-host smoke stack
  - id: cli-server-make-admin-promotes-signed-up-user
    type: e2e
    file: frontend/apps/web_app/tests/selfhost-smoke.spec.ts
    assertion: openmates server make-admin promotes a self-hosted signup user to admin
  - id: public-cli-docs-exclude-private-cloud-operations
    type: unit
    file: scripts/tests/test_cloud_only_operator_exclusions.py
    assertion: public-cli-docs-exclude-private-cloud-operations
coverage:
  policy: assertion-backed
  reviewed_context:
    - frontend/packages/openmates-cli/src/server.ts
    - frontend/packages/openmates-cli/src/serverConfig.ts
    - frontend/packages/openmates-cli/src/serverHealth.ts
    - frontend/packages/openmates-cli/src/serverPlanning.ts
---

# Server Management

## Summary

- `openmates server` commands manage a local Docker Compose installation without requiring a cloud login.
- Default installs use prebuilt GHCR images, so normal operators do not need Git or a source checkout.
- The CLI stores the installation path, validates that a path looks like an OpenMates installation, and builds the Docker Compose command for core or override services.
- Server operations are role-aware: use `--role core`, `--role upload`, or `--role preview` for role-specific installs, service filters, backups, updates, and Caddy checks.
- Image-mode updates create a rotating latest pre-update backup for data-bearing roles before containers are replaced.
- Install and update provision a five-minute host runtime monitor plus an independent stale watchdog. Installing system units requires root privileges.
- Updates run a bounded runtime-contract checklist after container readiness; required failures leave the updated containers running and record a degraded update instead of rolling data back automatically.
- Self-hosted installations never run billing checks.
- Image-mode install defaults to invite-only signup; edit `.env` for email-domain allowlists or invite-plus-domain mode.
- Starting the server warns when no real LLM API key is configured, but still starts the backend and web app. AI model processing stays unavailable until a real key is added.

Commands for installing, running, and administering a self-hosted OpenMates instance. Server commands do not require login -- they operate directly on the local Docker Compose environment.

## Prerequisites

- **Docker** -- must be installed with the daemon running
- **Node.js/npm** -- used to install the OpenMates CLI package
- **Git** -- only required for source mode (`--from-source` or `--source-path`)
- Optional LLM provider API key when you want AI chat/model processing

## Installing

For normal self-hosted setup, install the CLI from npm first:

```
npm install -g openmates
```

Then run the installer:

```
openmates server install
openmates server install --path /opt/openmates
openmates server install --env-path ~/my-env-file
openmates server install --image-tag v0.18.0
openmates server install --role core --profile production
openmates server install --role upload --path /opt/openmates-upload
openmates server install --role preview --path /opt/openmates-preview
openmates server install --from-source --path /opt/openmates-source
openmates server install --source-path /path/to/OpenMates --path /tmp/openmates-selfhost
```

Default install mode creates a lightweight runtime directory, writes `.env`, stores image-mode Docker Compose files, and uses prebuilt images from `ghcr.io/glowingkitty`. It does not clone the OpenMates repository. Default install directory is `~/openmates`.

The generated `.env` includes `PRODUCTION_URL="http://localhost:5173"` so the production-mode backend allows browser API calls from the default local web app origin. If you serve the web app from another HTTPS domain, update `PRODUCTION_URL` before restarting.

Source mode is the contributor/fork path. Use `--from-source` to clone the official repository, or `--source-path <dir>` to clone from an existing local checkout. Source mode requires Git for clone-based installs and updates, and rebuilds Docker images locally.

To manage an existing checkout in place without cloning, pulling, or changing its Git state, register it as a working-tree server:

```bash
openmates server register --path /path/to/OpenMates
```

Registration records the runtime mode, Compose configuration, and default service set. Self-host registrations and installations include the bundled web app.

Image-mode install defaults to `invite_only`. The install output includes the first signup invite code. That invite creates a normal user; grant admin privileges after signup with `openmates server make-admin <email>`. Source-mode installs still use the repository setup script behavior.

| Option | Default | Description |
|--------|---------|-------------|
| `--path <dir>` | `~/openmates` | Installation directory |
| `--env-path <file>` | None | Copy a pre-existing `.env` file during install |
| `--image-tag <tag>` | CLI version tag | Use a specific prebuilt image tag |
| `--role core|upload|preview` | `core` | Install a role-specific runtime |
| `--profile minimal|standard|production` | `production` for core | Select core observability services |
| `--with-alerts` | Off | Include Alertmanager in the core production profile |
| `--from-source` | Off | Clone/build from source instead of using prebuilt GHCR images |
| `--source-path <dir>` | None | Clone from a local checkout instead of GitHub. Implies source mode and is intended for CI/testing/contributors. |

The first image-mode start downloads the OpenMates image set and third-party service images. Expect several GB of compressed image downloads on a fresh host; Docker caches layers for later starts and updates.

The GHCR package list is intentionally smaller than the runtime container list. Several containers, such as `api`, `task-worker`, `app-ai-worker`, `app-images-worker`, and other app workers, reuse the `openmates-api` image with different commands and Celery queues. `openmates-docs-worker` is split out only because document processing needs extra OS tooling. See [self-hosting setup](../../self-hosting/setup.md#images-and-runtime-containers) for the image-to-container mapping.

## Starting the Server

```
openmates server start
openmates server start --with-overrides
openmates server start --exclude webapp
openmates server start --services api,task-worker
```

Starts all Docker containers for the backend and web app. The web app is available at `http://localhost:5173`, and the backend API is available at `http://localhost:8000`.

The `--with-overrides` flag includes admin UIs such as Directus CMS and Grafana defined in `docker-compose.override.yml`.

If the `.env` file has no real LLM provider API key, startup continues with a warning. Empty, commented, non-model provider, or `IMPORTED_TO_VAULT` values do not count as configured AI model keys. Add a real key and run `openmates server restart` to enable AI chat/model processing. Provider-backed features that require a missing API key are hidden or disabled by default until the key is configured.

Manage the canonical runtime `.env` through the CLI instead of editing the full file by hand:

```
openmates server env list providers
openmates server env set SECRET__BRAVE__API_KEY
openmates server env unset SECRET__BRAVE__API_KEY --yes
openmates server env check
openmates server env doctor
```

The CLI redacts secret values in output, writes `.env` with restricted permissions, and creates a backup before changes. Docker and the CLI use one runtime `.env`; provider setup guidance should come from provider metadata rather than extra env files.

Alternatively, self-hosted servers can add a local Ollama, LM Studio, or custom OpenAI-compatible model:

```
openmates server ai models add
openmates server restart
```

The CLI writes local model entries to a runtime provider overlay, tests the selected model with a small request, and configures the model with `0` charged credits. List, test, or remove local models with:

```
openmates server ai models list
openmates server ai models test <provider/model-id>
openmates server ai models remove <provider/model-id>
```

## Stopping the Server

```
openmates server stop
```

Gracefully stops all Docker containers.

## Restarting the Server

```
openmates server restart
openmates server restart --rebuild
```

| Option | Description |
|--------|-------------|
| `--rebuild` | Source mode only. Full rebuild: stops containers, rebuilds images, then starts. Image-mode installs should use `openmates server update` to pull newer images. |

## Server Status

```
openmates server status
openmates server status --json
```

Shows the health status of all Docker containers.

## Viewing Logs

```
openmates server logs
openmates server logs --container api
openmates server logs --container api --follow
openmates server logs --tail 200
openmates server logs --services api,task-worker
```

| Option | Default | Description |
|--------|---------|-------------|
| `--container <name>` | All | Filter logs to a specific service (e.g., `api`, `cms`, `worker`) |
| `--follow`, `-f` | Off | Stream logs in real time |
| `--tail <n>` | 100 | Number of lines to show |

## Updating

```
openmates server update
openmates server update --dry-run
openmates server update --image-tag v0.18.0
openmates server update --channel stable
openmates server update --channel dev
openmates server update --services api,task-worker
openmates server update --exclude webapp
openmates server update --skip-quick-test
openmates server update --quick-test --confirm-spend-credits
openmates server update install-service --continuous --channel main --window "02:00-04:00 Europe/Berlin"
openmates server update status
openmates server update status --json
openmates server update --force
```

Image-mode installs refresh the runtime Compose template from the packaged CLI templates, update `OPENMATES_IMAGE_TAG`, create a rotating latest pre-update backup for data-bearing roles, run `docker compose pull`, restart selected services, wait for role-specific health checks, and then run the runtime-contract checklist. By default, version-pinned installs target the current CLI version tag, so update the CLI first when you want the newest released self-host images. Installs already using a channel tag keep that channel unless you pass a different target.

Managed-clone source installs run `git pull --ff-only`, rebuild containers, restart, and run the same readiness and runtime-contract checks. Registered working-tree servers never pull or alter Git state: `update` builds the current checkout exactly as it exists. Automated `git stash` is not supported.

Only one update may mutate an installation at a time, including updates requested for different roles. If a crashed process leaves `.openmates/server-update.lock`, verify that no update process is running before removing that lock explicitly; the CLI never takes over a stale lock automatically.

After the provider-free runtime checklist passes on an interactive core-server update, the CLI offers `Continue with quick server test?`. The optional test uses the CLI account logged into that self-hosted instance to create, reload, and remove one temporary encrypted AI chat, run `math.calculate`, and run a one-result `web.search`. These checks may consume account credits, so declining does not affect the successful deterministic update and `--yes` never authorizes them.

If the CLI has no session for the updated instance, it prints the instance-scoped login command. Log in and rerun the same suite without updating:

```bash
openmates --api-url https://api.example.org login
openmates --api-url https://api.example.org server test --quick
```

JSON, redirected-input, and continuous updates never prompt or spend by default. Automation must pass both `--quick-test` and `--confirm-spend-credits`; `--skip-quick-test` suppresses the interactive offer. An accepted quick-test failure marks update status degraded, leaves the updated containers running for diagnosis, and never triggers automatic rollback.

After the required checks, monitoring setup, and any accepted quick test pass, every image-mode or source-mode update sends one `Server update complete` email to the configured admin. The message identifies the installed image tag or source revision, server role, completion time, and the best available public GitHub release, pull-request, commit, or source link. The update records `success` only after the email provider accepts the message; provider acceptance does not guarantee inbox placement.

Admin email and Brevo configuration are therefore required for updates. Missing configuration or delivery failure after three bounded attempts leaves the updated containers running, records `degraded` with a redacted delivery result, and exits non-zero. It never triggers automatic rollback. Correct the host notification configuration or provider issue, then rerun the update within 30 minutes so an ambiguous delivery reuses the same provider idempotency key.

Delivery retries reuse one persisted Brevo idempotency key. After Brevo's 30-minute idempotency window expires, an unresolved pending or failed receipt blocks automatic resend to avoid duplicate mail. Check the Brevo activity log and admin inbox first; only when the operator accepts the duplicate-delivery risk should they remove the role's `.openmates/<role>-update-status.json` receipt and rerun the update. Continuous polling does not resend a completion email when the installed artifact is unchanged and that artifact already has a valid accepted completion receipt.

The checklist has a 60-second global deadline. It verifies the required role services and HTTP health first, then runs dependency-safe checks for the role:

| Role | Required runtime checks |
| --- | --- |
| `core` | API, Directus/Postgres path, cache, Vault, provider-free `app_ai` queue probe, scheduler freshness, and synthetic chat plumbing |
| `upload` | Upload API, Vault, and ClamAV connectivity |
| `preview` | Preview API and renderer health |

Core verification also reports `core.object_storage` as an optional check. A
temporary S3-compatible storage outage makes the server `degraded`, but does
not fail API liveness, text-only AI, or non-storage skills. Uploads, stored-file
reads, and generated media that require durable storage fail before paid work
with retryable `storage_temporarily_unavailable`; there is no local-disk
fallback.

When a required check fails, the CLI:

- Leaves the newly updated containers running for diagnosis.
- Records `degraded` update state and sanitized per-check results.
- Sends configured post-update failure notifications independently.
- Prints an exact role-scoped restore command only if a verified pre-update backup exists; otherwise it reports `restore_unavailable`.
- Never performs an automatic restore.

| Option | Applies to | Description |
|--------|------------|-------------|
| `--dry-run` | Both modes | Print the update plan without changing files or containers |
| `--image-tag <tag>` | Image mode | Update to a specific prebuilt image tag |
| `--channel stable|main|dev` | Image mode | Update using a mutable channel tag. `stable` maps to the published `main` tag. |
| `--services <csv>` | Image mode | Update only selected role services |
| `--exclude <csv>` | Image mode | Update all role services except selected services |
| `--skip-quick-test` | Core updates | Suppress the optional authenticated quick-test offer |
| `--quick-test --confirm-spend-credits` | Core updates | Explicitly run the bounded paid test in non-interactive automation |
| `install-service --continuous` | Image mode | Install a host-level systemd timer that runs the CLI update path |
| `--force` | Source mode | Stash local Git changes before `git pull --ff-only` |

## Runtime Verification and Monitoring

Run the same no-spend verifier without updating:

```bash
openmates server verify --role core
openmates server verify --role core --json
openmates server verify --role upload --path /opt/openmates-upload
openmates server verify --role preview --path /opt/openmates-preview
```

Install or repair the periodic monitor and independent watchdog:

```bash
sudo "$(command -v openmates)" server monitoring install-service --role core --path ~/openmates
openmates server monitoring status --role core --path ~/openmates
openmates server monitoring status --role core --path ~/openmates --json
openmates server monitoring digest --role core --path ~/openmates --channel email,discord --test --json
openmates server monitoring report-watchdog --role core --path ~/openmates --json
```

The installation always creates two five-minute runtime-health services and timers. When at least one verified report channel is configured, it also creates a daily 08:30 UTC operational digest and a five-minute report-freshness watchdog. Host systemd is the only digest scheduler, preventing duplicate Celery and host deliveries.

The digest summarizes the preceding 24 hours of aggregate resource, activity, processing, and issue data in a compact graph. Self-host reports omit billing entirely and do not query billing collections or credentials. Email is enabled only after a bounded Brevo account probe; the generated service requests only channels that passed configuration checks.

An accepted report updates host-owned freshness metrics and append-only redacted receipt history under `<install>/.openmates/runtime-health/`. A missing accepted report becomes an incident after 26 hours. Disabling all digest destinations removes the digest timers and freshness metrics rather than generating a false stale incident.

Runtime state is stored at `<install>/.openmates/runtime-health/<role>.json`. The directory uses mode `0700`, the state file uses `0600`, and writes are atomic. It stores operational check IDs, timestamps, counters, and delivery status only, never notification destinations, provider responses, user data, chat content, payment data, or secrets.

Alert behavior:

- Transient failures alert after two consecutive failures of the same check.
- Object-storage degradation escalates once after one continuous hour.
- Credential and required-configuration failures alert immediately.
- A verifier timestamp older than 15 minutes produces a stale-monitor alert.
- One recovery event is sent when an open incident clears.
- A healthy installation sends at most one green heartbeat per UTC day.
- Email, Discord, and generic webhook delivery are attempted independently, with bounded retries.
- API, host, disk, and monitor-staleness failures use the host notifier, so at least one configured email or Discord path remains independent of API and Celery health.
- Intentionally unconfigured object storage reports `not_configured` and does not open or recover a provider-outage incident.

## Runtime Notifications

Configure one or more host-level notification channels in the installation `.env`:

```env
OPENMATES_RUNTIME_HEALTH_EMAIL_TO="operator@example.com"
OPENMATES_RUNTIME_HEALTH_EMAIL_FROM="noreply@example.com"
OPENMATES_RUNTIME_HEALTH_BREVO_API_KEY="<BREVO_API_KEY>"

OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL="<DISCORD_WEBHOOK_URL>"

OPENMATES_RUNTIME_HEALTH_WEBHOOK_URL="https://monitoring.example.com/openmates"
OPENMATES_RUNTIME_HEALTH_WEBHOOK_SECRET="<RANDOM_SIGNING_SECRET>"
```

Do not commit these values or pass them on the command line. Use `openmates server env set <KEY>` so secret values are prompted for and CLI output remains redacted.

The email recipient, sender, and Brevo key form the mandatory final completion check for `openmates server update`. Discord and generic webhook configuration remain optional and are not substitutes for the admin completion email.

Test delivery after configuration:

```bash
openmates server notifications test --channel email --json
openmates server notifications test --channel discord --json
openmates server notifications test --channel webhook --json
openmates server notifications test --channel all --json
```

Generic webhooks use canonical JSON and include `X-OpenMates-Timestamp`, `X-OpenMates-Event-Id`, and `X-OpenMates-Signature` (`sha256=<HMAC>`). Production delivery requires HTTPS on port 443, disables redirects, validates every resolved address, rejects non-public destinations, pins the validated address for the connection, and bounds request time and response size.

## Backups and Restore

```bash
openmates server backup --role core
openmates server backup --role core --include-observability
openmates server backup list --role core
openmates server restore --role core --file /path/to/openmates-core-backup.tar.gz
```

Backups are written under `<install>/backups/<role>/` by default with owner-only permissions. Core backups include a Postgres logical dump, runtime `.env`, runtime config, Directus upload/extension paths when present, a manifest, and checksums. `--include-observability` also includes observability scope in the manifest and is reserved for installs that persist OpenObserve/Prometheus data.

Restore requires confirmation unless `--yes` is passed. It validates the manifest role before restoring runtime files and, for core backups, imports `postgres.sql` into the running `cms-database` container.

## Preflight and Caddy

```bash
openmates server preflight --role core
openmates server caddy status --role core
openmates server caddy check --role upload
openmates server caddy diff --role preview
openmates server caddy apply --role core --yes
```

`preflight` reports selected services, backup plan, health checks, required environment keys, and Caddy drift plan. Caddy commands use packaged role templates and never print secret values. `apply` validates the template, backs up the current Caddyfile, writes the replacement, and reloads Caddy; run it with sufficient host privileges.

## Granting Admin Privileges

```
openmates server make-admin user@example.com
openmates server make-admin user@example.com --path /opt/openmates
```

Grants admin privileges to an existing user account. Signup invites and domain allowlists create normal users only; run this command after the user has signed up. Active browser sessions see the `Server` and `Logs` settings entries after the next auth check or refresh.

## Resetting Server Data

```
openmates server reset
openmates server reset --delete-user-data-only
openmates server reset --yes
```

Requires confirmation by typing a phrase. This is a destructive operation.

| Option | Description |
|--------|-------------|
| `--delete-user-data-only` | Only delete database and cache data, preserve configuration |
| `--yes` | Skip the confirmation prompt |

## Uninstalling

```
openmates server uninstall
openmates server uninstall --keep-data
openmates server uninstall --yes
```

Completely removes the OpenMates installation. Requires confirmation.

| Option | Description |
|--------|-------------|
| `--keep-data` | Preserve Docker volumes (data can be restored later by reinstalling) |
| `--yes` | Skip the confirmation prompt |

## Global Server Options

All server commands accept:

| Option | Description |
|--------|-------------|
| `--path <dir>` | Override the server installation directory |
| `--json` | Output machine-readable JSON |

## Key Files

- See [server.ts](../../../frontend/packages/openmates-cli/src/server.ts) for all server command handlers
- See [serverConfig.ts](../../../frontend/packages/openmates-cli/src/serverConfig.ts) for server configuration persistence

## Related Docs

- [README](./README.md) -- CLI overview and installation
- [Authentication](./authentication.md) -- server commands do not require login
