---
status: active
doc_type: reference
audience:
  - end-users
  - technical-users
last_verified: 2026-06-11
claims:
  - id: cli-apps-code-run-uses-app-skill-endpoint
    type: unit
    claim: CLI app skill execution uses the canonical app-skill run endpoint for Code Run.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-apps-code-run-uses-app-skill-endpoint
    verified: '2026-06-11'
  - id: cli-apps-memory-type-registry-is-available
    type: unit
    claim: CLI app and memory docs are grounded in the exported memory type registry.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-apps-memory-type-registry-is-available
    verified: '2026-06-11'
  - id: cli-apps-docs-cover-code-run-commands
    type: unit
    claim: Apps docs cover the Code Run command forms exposed by CLI help.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
      - frontend/packages/openmates-cli/src/codeRunInput.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-apps-docs-cover-code-run-commands
    verified: '2026-06-11'
---

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

## Code Run

The Code app has a dedicated convenience command for running local snippets or project files through the app-skill endpoint:

```
openmates apps code run --language python --code 'print("Hello")'
openmates apps code run --entry main.py --file main.py --file requirements.txt
openmates apps code run --entry main.py --dir ./project --exclude node_modules
```

Use inline `--code` for short snippets, repeated `--file` flags for a small set of files, or `--dir` plus `--entry` for a project folder. The command streams status/output when available and falls back to polling the execution status endpoint.

## Authentication

Skills use your logged-in session by default. Alternatively, pass an API key:

```
openmates apps web search "query" --api-key <key>
```

Or set the `OPENMATES_API_KEY` environment variable.

## Memories

Memories are per-app key-value entries stored in Memories. They are encrypted and synced via WebSocket.

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

- See [cli.ts](../../../frontend/packages/openmates-cli/src/cli.ts) for `handleApps()` and `handleMemories()`
- See [client.ts](../../../frontend/packages/openmates-cli/src/client.ts) for `runSkill()`, `listApps()`, `getSkillInfo()`, `getSkillSchema()`, and the `MEMORY_TYPE_REGISTRY`

## Related Docs

- [README](./README.md) -- CLI overview
- [Settings](./settings.md) -- settings management (memories are a sub-command of settings)
- [Embeds & Sharing](./embeds-and-sharing.md) -- @mentions for skills in chat messages
- [CLI Standards](../../contributing/standards/cli.md) -- Rule 3 on keeping `MEMORY_TYPE_REGISTRY` in sync with `app.yml`
