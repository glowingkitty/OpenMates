---
status: active
doc_type: reference
audience:
  - technical-users
  - contributors
last_verified: 2026-06-06
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
coverage:
  policy: assertion-backed
  reviewed_context:
    - frontend/packages/openmates-cli/src/server.ts
    - frontend/packages/openmates-cli/src/serverConfig.ts
---

# Server Management

## Summary

- `openmates server` commands manage a local Docker Compose installation without requiring a cloud login.
- The CLI stores the installation path, validates that a path looks like an OpenMates checkout, and builds the Docker Compose command for core or override services.
- Install asks how signup should work on self-hosted servers: invite codes, email-domain allowlist, or both.
- Starting the server warns when no real LLM API key is configured, but still starts the backend and web app. AI model processing stays unavailable until a real key is added.

Commands for installing, running, and administering a self-hosted OpenMates instance. Server commands do not require login -- they operate directly on the local Docker Compose environment.

## Prerequisites

- **Docker** -- must be installed with the daemon running
- **Git** -- required for `install` and `update`
- **Node.js/npm** -- used to install the OpenMates CLI package
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
openmates server install --source-path /path/to/OpenMates --path /tmp/openmates-selfhost
```

Clones the OpenMates repository, runs setup, and prepares the Docker environment. Default install directory is `~/openmates`.

Interactive installs ask for the self-host signup mode. Non-interactive installs default to `invite_only`. If the selected mode uses invite codes, the install output includes the first signup invite code. That invite creates a normal user; grant admin privileges after signup with `openmates server make-admin <email>`.

| Option | Default | Description |
|--------|---------|-------------|
| `--path <dir>` | `~/openmates` | Installation directory |
| `--env-path <file>` | None | Copy a pre-existing `.env` file during install |
| `--source-path <dir>` | None | Clone from a local checkout instead of GitHub. Intended for CI/testing. |

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
| `--rebuild` | Full rebuild: stops containers, rebuilds images, then starts. Use after configuration changes. |

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

Pulls the latest version from Git and rebuilds Docker containers. The `--force` flag stashes local changes before pulling.

## Granting Admin Privileges

```
openmates server make-admin user@example.com
```

Grants admin privileges to an existing user account.

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
