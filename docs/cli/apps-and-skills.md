# Apps & Skills

List available apps, inspect skill schemas, and execute skills directly from the terminal. Skills can also be invoked via @mentions in chat messages.

## Listing Apps

```
openmates apps list
openmates apps list --json
```

Shows all available apps with their IDs and descriptions.

## App Info

```
openmates apps web
openmates apps info web
openmates apps web --json
```

Both `openmates apps <app-id>` and `openmates apps info <app-id>` display details about an app, including its available skills.

## Skill Info

```
openmates apps skill-info web search
openmates apps web search --help
openmates apps skill-info web search --json
```

Shows the skill's description, required parameters, and input schema. Use this to understand what a skill expects before running it.

## Running a Skill

For single-parameter skills (most common), pass the query as inline text:

```
openmates apps web search "latest AI news"
openmates apps news search "climate change"
openmates apps ai ask "Summarise this: ..."
```

Inline text is wrapped as `{ requests: [{ query: text }] }`, which matches the convention used by most query-based skills.

For multi-parameter skills, use `--input` with a JSON payload:

```
openmates apps travel search_connections --input '{"requests":[{"legs":[{"origin":"BER","destination":"LHR","date":"2026-04-15"}]}]}'
```

### Travel Booking Links

A specialized command for resolving booking URLs from travel search results:

```
openmates apps travel booking-link --token "<booking_token>"
openmates apps travel booking-link --token "<booking_token>" --context '{"currency":"EUR"}'
```

The `booking_token` is included in the output of `openmates apps travel search_connections`.

## Authentication

Skills use your logged-in session by default. Alternatively, pass an API key:

```
openmates apps web search "query" --api-key <key>
```

Or set the `OPENMATES_API_KEY` environment variable.

## Memories

Memories are per-app key-value entries stored in Settings & Memories. They are encrypted and synced via WebSocket.

### Listing Memories

```
openmates settings memories list
openmates settings memories list --app-id code
openmates settings memories list --app-id code --item-type preferred_tech
openmates settings memories list --json
```

### Listing Memory Types

Shows available memory types and their field schemas for a given app:

```
openmates settings memories types
openmates settings memories types --app-id code
openmates settings memories types --json
```

### Creating a Memory

```
openmates settings memories create --app-id code --item-type preferred_tech --data '{"name":"Python","proficiency":"advanced"}'
```

Field values are validated against the `MEMORY_TYPE_REGISTRY` in the CLI before sending. See the `types` command to discover required fields.

### Updating a Memory

```
openmates settings memories update --id <uuid> --app-id code --item-type preferred_tech --data '{"name":"Python","proficiency":"expert"}'
openmates settings memories update --id <uuid> --app-id code --item-type preferred_tech --data '...' --version 2
```

The `--version` flag enables optimistic concurrency control.

### Deleting a Memory

```
openmates settings memories delete --id <uuid>
```

## Key Files

- See [cli.ts](../../frontend/packages/openmates-cli/src/cli.ts) for `handleApps()` and `handleMemories()`
- See [client.ts](../../frontend/packages/openmates-cli/src/client.ts) for `runSkill()`, `listApps()`, `getSkillInfo()`, `getSkillSchema()`, and the `MEMORY_TYPE_REGISTRY`

## Related Docs

- [README](./README.md) -- CLI overview
- [Settings](./settings.md) -- settings management (memories are a sub-command of settings)
- [Embeds & Sharing](./embeds-and-sharing.md) -- @mentions for skills in chat messages
- [CLI Standards](../claude/cli-standards.md) -- Rule 3 on keeping `MEMORY_TYPE_REGISTRY` in sync with `app.yml`
