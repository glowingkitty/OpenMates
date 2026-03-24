---
status: planned
last_verified: 2026-03-24
---

# CLI — Remote Access, Server Management & Secret Processing

> **Status: Planned** — This feature is not yet implemented.
>
> Split from [cli-package.md](./cli-package.md) — this doc covers the planned `remote-access` and `server` commands, secret tokenization architecture, web app integration, and security design.

---

## Server Management Commands (Planned)

| Command | Description |
|---------|-------------|
| `openmates server install [--env-path PATH]` | Install and configure OpenMates server via Docker |
| `openmates server logs [--container NAME] [--follow]` | Display server logs with optional filtering |
| `openmates server start` | Start the server |
| `openmates server stop` | Stop the server |
| `openmates server restart` | Restart the server |
| `openmates server update` | Update server to latest version (pulls Docker images) |
| `openmates server reset [--delete-user-data-only]` | Reset server with data deletion (requires confirmation phrase) |

---

## Remote Access

### `openmates remote-access start [--full-access] [--dev-server] [--name SERVER_NAME]`

Enables remote access for the web app to interact with the server's file system and execute commands. The security model is determined by the flags used when starting the service.

**What Happens on Start:**

1. If not logged in, prompts for authentication via magic link
2. Registers this server with the OpenMates backend under the user's account
3. Automatically creates a Settings & Memory entry: `Server | Connected Servers | {server_name}`
4. Establishes persistent connection to OpenMates backend
5. Server is now accessible from the web app via the Settings & Memory reference

**Security Model:**

| Mode                         | Access Scope                     | Command Confirmation           | Use Case                                  |
| ---------------------------- | -------------------------------- | ------------------------------ | ----------------------------------------- |
| **Default** (no flags)       | Current folder + subfolders only | Required for all operations    | Production servers, safe default          |
| `--full-access`              | Full machine access              | Required for all operations    | Production servers needing broader access |
| `--dev-server`               | Current folder + subfolders only | Autonomous execution           | Development/temporary environments        |
| `--full-access --dev-server` | Full machine access              | Autonomous execution           | Use with extreme caution                  |

**Command Confirmations (when required):**
When not in `--dev-server` mode, the user must explicitly approve each command that writes, deletes, or moves files, starts/installs/uninstalls services, or makes any potentially destructive changes. Read operations generally do NOT require confirmation.

---

## Sensitive Files Protection

Certain file types that commonly contain secrets are **never read automatically**, even when the LLM requests them:

- Environment files (`.env`, `.env.*`, `.envrc`)
- Private keys (`.pem`, `.key`, `.p12`, `.pfx`, `.keystore`)
- SSH keys (`id_rsa`, `id_ed25519`, `id_dsa`, `authorized_keys`, `known_hosts`)
- Cloud credentials (`~/.aws/credentials`, `~/.config/gcloud/`, `~/.azure/`)
- Database connection files (`.pgpass`, `.my.cnf`, `database.yml` with credentials)
- Password manager files (`.kdbx`, `1Password.sqlite`)
- API key files (`secrets.json`, `credentials.json`, `*.credentials`)
- Git credentials (`.git-credentials`, `.netrc`)

**Special Handling for Environment Files:**
When a user explicitly requests access to environment files, the system employs **zero-knowledge processing**: file contents are NOT shown directly to the LLM. Instead, only secret names and the last few characters are revealed (e.g., `OPENAI_API_KEY: ***39d9`). This aligns with the zero-knowledge principle from `docs/architecture/zero-knowledge-storage.md`.

---

## Reversible Secret Tokenization (CLI + Web UI)

Secrets are replaced with structured tokens before LLM processing and restored to real values afterward. This is the same architectural pattern used for PII redaction in chat messages.

### Core Flow: Redact -> Process -> Restore

```
Real value:     OPENAI_API_KEY=sk-proj-abc123def456ghi789
                         | REDACT (before LLM sees it)
Tokenized:      OPENAI_API_KEY=<SECRET:env:OPENAI_API_KEY:sk-...789>
                         | LLM processes (sees token, not value)
LLM output:     "Set <SECRET:env:OPENAI_API_KEY:sk-...789> in production"
                         | RESTORE (before user/code sees it)
Restored:       "Set sk-proj-abc123def456ghi789 in production"
```

### Token Format

```
<SECRET:source:name:hint>
```

- **source**: where the secret came from (`env`, `aws`, `ssh`, `settings`, etc.)
- **name**: the variable/key name (`OPENAI_API_KEY`, `DATABASE_URL`, etc.)
- **hint**: prefix + `...` + suffix — enough to identify which key it is, not enough to reconstruct it

### Secret Registry

At session start (and on file changes via watchdog), the system builds an in-memory registry mapping real secret values to their tokens.

**Secret sources scanned:**

| Source | Scope | When |
|--------|-------|------|
| `.env`, `.env.*`, `.envrc` in CWD + parent dirs | Always | Session start |
| `~/.aws/credentials` | `--full-access` mode | Session start |
| `~/.ssh/id_rsa`, `id_ed25519`, etc. | `--full-access` mode | Session start |
| `~/.config/gcloud/application_default_credentials.json` | `--full-access` mode | Session start |
| Process env vars matching patterns (`*_KEY`, `*_SECRET`, `*_TOKEN`, `*_PASSWORD`) | Always | Session start |
| Settings & Memories secrets (synced from web UI) | Always | Session start + sync events |
| User-configured additional paths | If configured | Session start |

For each secret value, the scanner also pre-computes **encoded variants** (base64, URL-encoded, JSON-escaped, shell-escaped) so the same secret is caught regardless of how it appears in output.

### Aho-Corasick Multi-Pattern Matching

All secret values and their encoded variants are compiled into an **Aho-Corasick automaton** — finds all pattern matches in a single pass through the text, regardless of how many patterns exist.

| Operation | Complexity | Typical Time |
|-----------|-----------|--------------|
| Automaton build | O(total_pattern_length) | ~50-200ms at session start |
| Output scan | O(output_length) | Microseconds per KB |
| Automaton rebuild (secret change) | O(total_pattern_length) | ~50-200ms |

**Streaming support:** For long-running commands, the scanner processes output in chunks with a lookback buffer of `max_secret_length` bytes to catch secrets that span chunk boundaries.

**Cross-platform implementations:** Python: `ahocorasick` library (C extension). Node.js: `aho-corasick` npm package.

### Where Redaction and Restoration Apply

| Context | Redact? | Restore? | Reason |
|---------|---------|----------|--------|
| Tool results -> LLM | **Yes** | — | Core protection: LLM never sees real values |
| User message input (web UI + CLI) | **Yes** | — | Auto-detect secrets user pastes into chat |
| LLM response -> user display | — | **Yes** | User sees real values in their terminal/UI |
| LLM-generated commands -> execution | — | **Yes** | Commands need real secret values to work |
| LLM-generated file writes -> disk | — | **Yes** | Written files need real secrets |
| Chat history storage | **Tokens** | — | Stored chats keep redacted form |
| Audit logs | **Tokens** | — | Never log real secrets |

### Heuristic Secret Detection (Catch Unknowns)

Beyond the known-secret registry, the scanner also applies regex patterns for common secret formats:

- OpenAI keys: `sk-proj-...`, `sk-...`
- GitHub tokens: `ghp_...`, `gho_...`, `ghu_...`
- AWS keys: `AKIA...`
- JWT tokens: `eyJ...` (3-segment base64)
- Private key blocks: `-----BEGIN RSA PRIVATE KEY-----`
- Generic high-entropy strings in assignment context

These are lower-confidence matches, so they use a distinct marker: `<POSSIBLE_SECRET:...>` to signal uncertainty.

### Environment Variable Stripping

Before spawning any child process for LLM-triggered commands, sensitive environment variables are stripped from the child's env. This prevents `env`, `printenv`, or `echo $OPENAI_API_KEY` from leaking secrets even before output scrubbing runs.

### Secret Generation Tool

The LLM can request secret generation via a privileged tool call. Generation runs in trusted runtime code — the raw value never enters the LLM context.

Supported types: `random`, `uuid`, `pin`, `password`, `hex`, `base64`.

**User-provided secrets:** When a user provides a secret (e.g., a third-party API key), the CLI prompts them directly on stdin (outside the LLM context). The value goes straight to the secret store and the LLM receives only the token.

### Secrets as Settings & Memories (Cross-Device)

Secrets are a **first-class data type** in the Settings & Memories system, accessible from both web UI and CLI. Cross-device sync uses the existing encrypted sync infrastructure.

**Secret lifecycle operations:**

| Operation | Description |
|-----------|-------------|
| `list` | Show all secrets (names + hints, never full values) |
| `create` | Store a new secret (user-provided or generated) |
| `rotate` | Generate new value for existing secret |
| `revoke` | Delete a secret from the store |
| `sync` | Force sync with Settings & Memories backend |
| `validate` | Check if a secret is still valid (API key test, etc.) |

### Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Secret value < 8 characters | Still tokenized, but with longer hint. Excluded from heuristic detection to avoid false positives. |
| Secret appears in a filename | Tokenized — filenames in `find`/`ls` output go through the same scanner |
| Binary command output | Skip scanning (detect via null bytes). Binary output doesn't go to LLM. |
| Secret changes mid-session | File watcher triggers registry + automaton rebuild |
| LLM hallucinates a token format | Restore layer won't find it in registry, leaves it as-is |
| Multiple secrets with same suffix | Extend hint length or add numeric disambiguator |
| Compound values (e.g., DATABASE_URL) | Tokenize the entire value as one token |
| Encoded secrets (base64, URL-encoded) | Pre-computed variants in the registry catch all encodings |

### Auditability

Every secret operation is logged: who (user/session ID), when, what (secret name, never value), and action (list, create, rotate, revoke, read-attempt, auto-detected-in-input).

**Differentiated handling for sensitive files:**
- **Environment files**: Zero-knowledge processing applied automatically (names + last few chars only)
- **Other sensitive files** (`.pem`, `.key`, SSH keys, etc.): Detailed warning shown before proceeding, user must confirm, advice to rotate credentials after session

**Use cases by mode:**
- Production servers (default): Secure folder-scoped access with explicit approval
- Production servers (--full-access): Broader access, still requires confirmation
- E2B VMs (--dev-server): Auto-installed for executing untrusted code autonomously
- Development environments (--dev-server): Fast iteration without confirmations

---

## Web App Integration with Connected Servers

### Architecture Overview

The integration uses a hybrid approach combining **Settings & Memories** (for server registry) with **App Skills** (for chat-level connection management).

**Settings & Memories:** Store account-level server registry
- Created automatically when CLI runs `remote-access start`
- Contains: `server_id`, `server_name`, `connection_status`, `access_mode`
- Referenceable in any chat via `@Server-Connected-Servers-{server_name}`
- Deletable by user to fully revoke a server's access

**App Skills:** Manage chat-level server context and execute operations

| Skill | App | Input | Purpose |
|-------|-----|-------|---------|
| Server \| Connect | Server | server_id (from S&M reference) | Activate server for this chat |
| Server \| Disconnect | Server | none | Deactivate server for this chat |
| Server \| Run Command | Server | command(s) | Execute terminal commands |
| Server \| Dashboard | Server | none | Show server status/resources |
| Files \| Read | Files | filepath | Read file (works on local or connected server) |
| Files \| Write | Files | filepath, content | Write file (works on local or connected server) |
| Files \| List | Files | directory path | List directory contents |

File operations belong to the "Files" app, which is context-aware. When a server is connected in the chat, file operations route through that server connection.

### Constraints

- **Single server per chat**: Connecting to a different server automatically disconnects the previous one
- **Multi-server workflows**: Use explicit `@Server-Connected-Servers-{name}` references per message, or separate chats
- **Chat sharing safety**: Viewers can see command outputs and `@Server` references, but cannot execute commands (they don't own the server). No credentials or tokens are embedded in chat history.

---

## Security Principles

- **Default settings**: Conservative and limited access for production safety
- **Opt-in features**: Full access and autonomous operation require explicit flags
- **Confirmation required**: All potentially harmful operations require user confirmation by default
- **Terminal command blocking**: The CLI prevents the LLM from executing arbitrary terminal commands to read files. Instead, a dedicated file-reading function enforces the sensitive files list and applies zero-knowledge processing.
- **Prompt injection prevention**: Blocks attackers from embedding commands like `cat .env` in user inputs to bypass security checks. See [Prompt Injection Protection](../architecture/prompt-injection.md).
