---
status: active
last_verified: 2026-03-24
---

# Server Management

Commands for installing, running, and administering a self-hosted OpenMates instance. Server commands do not require login -- they operate directly on the local Docker Compose environment.

## Prerequisites

- **Docker** -- must be installed with the daemon running
- **Git** -- required for `install` and `update`
- At least one LLM provider API key (OpenAI, Anthropic, or Google) in the `.env` file

## Installing

```
openmates server install
openmates server install --path /opt/openmates
openmates server install --env-path ~/my-env-file
```

Clones the OpenMates repository, runs setup, and prepares the Docker environment. Default install directory is `~/openmates`.

| Option | Default | Description |
|--------|---------|-------------|
| `--path <dir>` | `~/openmates` | Installation directory |
| `--env-path <file>` | None | Copy a pre-existing `.env` file during install |

## Starting the Server

```
openmates server start
openmates server start --with-overrides
```

Starts all Docker containers. The `--with-overrides` flag includes admin UIs (Directus CMS, Grafana) defined in `docker-compose.override.yml`.

Requires at least one LLM provider API key in the `.env` file. The CLI checks for `SECRET__*__API_KEY` entries before starting.

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
