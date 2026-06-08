---
status: active
doc_type: reference
audience:
  - technical-users
  - contributors
last_verified: 2026-06-08
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
coverage:
  policy: assertion-backed
  reviewed_context:
    - frontend/packages/openmates-cli/src/server.ts
    - frontend/packages/openmates-cli/src/serverConfig.ts
---

# Server Management

## Summary

- `openmates server` commands manage a local Docker Compose installation without requiring a cloud login.
- Default installs use prebuilt GHCR images, so normal operators do not need Git or a source checkout.
- The CLI stores the installation path, validates that a path looks like an OpenMates installation, and builds the Docker Compose command for core or override services.
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
openmates server install --image-tag v0.11.0-alpha.0
openmates server install --from-source --path /opt/openmates-source
openmates server install --source-path /path/to/OpenMates --path /tmp/openmates-selfhost
```

Default install mode creates a lightweight runtime directory, writes `.env`, stores image-mode Docker Compose files, and uses prebuilt images from `ghcr.io/glowingkitty`. It does not clone the OpenMates repository. Default install directory is `~/openmates`.

The generated `.env` includes `PRODUCTION_URL="http://localhost:5173"` so the production-mode backend allows browser API calls from the default local web app origin. If you serve the web app from another HTTPS domain, update `PRODUCTION_URL` before restarting.

Source mode is the contributor/fork path. Use `--from-source` to clone the official repository, or `--source-path <dir>` to clone from an existing local checkout. Source mode requires Git for clone-based installs and updates, and rebuilds Docker images locally.

Image-mode install defaults to `invite_only`. The install output includes the first signup invite code. That invite creates a normal user; grant admin privileges after signup with `openmates server make-admin <email>`. Source-mode installs still use the repository setup script behavior.

| Option | Default | Description |
|--------|---------|-------------|
| `--path <dir>` | `~/openmates` | Installation directory |
| `--env-path <file>` | None | Copy a pre-existing `.env` file during install |
| `--image-tag <tag>` | CLI version tag | Use a specific prebuilt image tag |
| `--from-source` | Off | Clone/build from source instead of using prebuilt GHCR images |
| `--source-path <dir>` | None | Clone from a local checkout instead of GitHub. Implies source mode and is intended for CI/testing/contributors. |

The first image-mode start downloads the OpenMates image set and third-party service images. Expect several GB of compressed image downloads on a fresh host; Docker caches layers for later starts and updates.

## Starting the Server

```
openmates server start
openmates server start --with-overrides
```

Starts all Docker containers for the backend and web app. The web app is available at `http://localhost:5173`, and the backend API is available at `http://localhost:8000`.

The `--with-overrides` flag includes admin UIs such as Directus CMS and Grafana defined in `docker-compose.override.yml`.

If the `.env` file has no real LLM provider API key, startup continues with a warning. Empty, commented, non-model provider, or `IMPORTED_TO_VAULT` values do not count as configured AI model keys. Add a real key and run `openmates server restart` to enable AI chat/model processing.

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
```

| Option | Default | Description |
|--------|---------|-------------|
| `--container <name>` | All | Filter logs to a specific service (e.g., `api`, `cms`, `worker`) |
| `--follow`, `-f` | Off | Stream logs in real time |
| `--tail <n>` | 100 | Number of lines to show |

## Updating

```
openmates server update
openmates server update --force
```

Image-mode installs run `docker compose pull` and restart the stack. Source-mode installs run `git pull --ff-only`, rebuild containers, and restart. The `--force` flag only applies to source-mode Git updates.

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

- See [server.ts](../../frontend/packages/openmates-cli/src/server.ts) for all server command handlers
- See [serverConfig.ts](../../frontend/packages/openmates-cli/src/serverConfig.ts) for server configuration persistence

## Related Docs

- [README](./README.md) -- CLI overview and installation
- [Authentication](./authentication.md) -- server commands do not require login
