# Claude AI Assistant Instructions

## Linting and Code Quality

**ALWAYS run the lint script after making code changes** to verify that your changes haven't introduced any errors.

The `scripts/lint_changed.sh` script checks uncommitted changes for linting and type errors. Use file type filters and path targeting to only check the files and folders you've modified:

**Available file type options:**

- `--py` - Python files (.py)
- `--ts` - TypeScript files (.ts, .tsx)
- `--svelte` - Svelte files (.svelte)
- `--css` - CSS files (.css)
- `--html` - HTML files (.html)
- `--yml` - YAML files (.yml, .yaml)

**Targeting options (always use these):**

- `--path <file|dir>` - Limit checks to a specific file or directory (repeatable)
- `-- <file|dir> ...` - Treat remaining args as target paths

**Examples:**

```bash
./scripts/lint_changed.sh --py --path backend/core/api              # Only Python changes in API
./scripts/lint_changed.sh --ts --svelte --path frontend/packages/ui # Only UI frontend changes
./scripts/lint_changed.sh --py --ts --path backend --path frontend/apps/web_app # Mixed changes by path
./scripts/lint_changed.sh -- backend/core/api                       # Path-only filtering
```

**Best practices:**

- Always limit checks to the specific files or folders you touched (use `--path` or `--`)
- Limit checks to changed file types (don't check TypeScript if you only modified Python)
- **CRITICAL**: Before every git commit, you MUST run the linter check script on all modified files and fix all remaining issues.
- **CRITICAL**: Only once the linter check script shows NO errors for modified files shall you commit the changes.
- Always run the lint script before considering changes complete
- Fix all errors before proceeding

## Git Commit Best Practices

### Commit Message Format
Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

**Format:** `<type>: <description>`

**Types:**
- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Changes that do not affect the meaning of the code (white-space, formatting, etc)
- `refactor`: A code change that neither fixes a bug nor adds a feature
- `perf`: A code change that improves performance
- `test`: Adding missing tests or correcting existing tests
- `build`: Changes that affect the build system or external dependencies
- `ci`: Changes to CI configuration files and scripts
- `chore`: Other changes that don't modify src or test files
- `revert`: Reverts a previous commit

**Rules:**
- Use the imperative, present tense: "change" not "changed" nor "changes"
- Don't capitalize the first letter of the description
- No dot (.) at the end of the title
- **Description/Body**: Use for complex changes. Explain the **why** and **what**, focusing on the reasoning behind the change.

**Example:**
```bash
feat: add user authentication flow

- Implement JWT token generation and validation
- Add login and registration endpoints
- Secure existing API routes with auth middleware
```

### Pre-commit Checklist
- [ ] Run linter: `./scripts/lint_changed.sh --path <your_changes>`
- [ ] Fix all linter and type errors
- [ ] Remove temporary `console.log` or `print` statements (unless permanent)
- [ ] Ensure all new files are added to git

## Debugging Backend Issues

**ALWAYS use docker compose terminal commands to check logs** when debugging backend issues. This ensures you're viewing logs from the running containerized services.

### Basic Log Commands

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs <service-name>              # View logs for a service
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f <service-name>          # Follow logs in real-time
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=100 <service-name>  # View last 100 lines
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f -t <service-name>       # Follow with timestamps
docker compose --env-file .env -f backend/core/docker-compose.yml logs api task-worker            # Multiple services
```

### Time-Based Log Filtering

Use `--since` to focus on recent issues (most useful for debugging):

```bash
# Logs from the last N minutes only
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 5m api task-worker

# Logs from the last hour
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 1h api

# Logs since a specific timestamp
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since "2026-01-15T10:00:00" api
```

### Log Level Filtering

```bash
# Only errors and warnings
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail 500 api | rg -E "ERROR|WARNING|CRITICAL"

# Errors with 3 lines of context before (to see what caused the error)
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail 1000 api | rg -B3 "ERROR"

# Errors with context before and after
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 10m api task-worker | rg -B3 -A3 "ERROR"
```

### Where to Look First (by Problem Type)

| Problem Type | Check First | Then Check |
|-------------|-------------|------------|
| AI response issues | `task-worker`, `app-ai-worker` | `api` (WebSocket logs) |
| Login/auth failures | `api` | `cms` (Directus logs) |
| Payment issues | `api` | `task-worker` (async jobs) |
| Sync/cache issues | `api` (PHASE1, SYNC_CACHE) | `cache` (Dragonfly) |
| WebSocket disconnects | `api` | Browser console |
| Scheduled task failures | `task-scheduler` | `task-worker` |
| User data issues | `cms`, `cms-database` | `api` |

### Quick Debug Commands (Common Patterns)

```bash
# Check if AI response updated sync cache
docker compose --env-file .env -f backend/core/docker-compose.yml logs task-worker --since 5m | rg "SYNC_CACHE_UPDATE.*AI response"

# Monitor Phase 1 sync in real-time
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f api | rg "PHASE1"

# Check Phase 1 sync for encrypted_chat_key
docker compose --env-file .env -f backend/core/docker-compose.yml logs api --tail 500 | rg -E "PHASE1_CHAT_METADATA.*encrypted_chat_key|PHASE1_SEND.*has_encrypted_chat_key"

# Trace full request lifecycle for a specific chat
docker compose --env-file .env -f backend/core/docker-compose.yml logs api task-worker --since 10m | rg -E "chat_id=<ID>|SYNC_CACHE|PHASE1" | head -100

# Find all errors with task context
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 5m api task-worker | rg -E "ERROR|task_id=" | rg -B2 -A2 "ERROR"
```

### Rebuilding and Restarting Services

If a container might have outdated code after a simple restart, or if you need to ensure a clean state (including clearing the cache volume), use this full rebuild and restart command:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down && \
docker volume rm openmates-cache-data && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build api cms cms-database cms-setup task-worker task-scheduler app-ai app-code app-web app-videos app-news app-maps app-ai-worker app-web-worker cache vault vault-setup prometheus cadvisor loki promtail grafana && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

**Best practices:**

- Target specific services using service names (check `docker-compose.yml` for exact names)
- Use `-f` flag for real-time debugging
- Use `--tail=N` to limit output for long-running services
- Use `-t` flag to see timestamps
- Use `--since` to focus on recent activity (most efficient for debugging)
- Verify service is running with `docker compose ps` before checking logs
- Run these commands from the `OpenMates` repo root so the paths resolve correctly

**Available containers in `backend/core/docker-compose.yml`:**
- `api` - REST API service container
- `cms` - Directus CMS container
- `cms-database` - Postgres backing store for Directus
- `cms-setup` - One-time Directus schema/setup job
- `task-worker` - Core Celery worker for shared queues
- `task-scheduler` - Celery beat scheduler
- `app-ai` - AI app service container
- `app-web` - Web app service container
- `app-videos` - Videos app service container
- `app-news` - News app service container
- `app-maps` - Maps app service container
- `app-code` - Code app service container
- `app-ai-worker` - Celery worker for AI app queues
- `app-web-worker` - Celery worker for web app queues
- `cache` - Dragonfly cache container
- `vault` - Vault secrets management container
- `vault-setup` - Vault auto-unseal/setup job
- `prometheus` - Prometheus monitoring container
- `cadvisor` - cAdvisor system metrics container
- `loki` - Loki log aggregation container
- `promtail` - Promtail log shipper container
- `grafana` - Grafana dashboards container

**Commented/optional containers (disabled in the file):**
- `backup-service` - S3 backup service
- `updater-service` - Updater service container
- `webapp` - Static SvelteKit webapp container

## Server Inspection Scripts

Use these scripts to inspect server state directly. Run from the repo root.

### Chat, Embed and User Inspection

```bash
# Inspect a specific chat (cache, storage, Directus)
docker exec api python /app/backend/scripts/inspect_chat.py <chat_id>

# Inspect a specific embed
docker exec api python /app/backend/scripts/inspect_embed.py <embed_id>

# Inspect a specific user by email (metadata, decrypted fields, counts, activities, cache)
docker exec api python /app/backend/scripts/inspect_user.py <email_address>
```

### AI Request Debugging

Debug entries are stored encrypted in cache with 30-minute TTL. Use this to see the full preprocessor/processor/postprocessor flow:

```bash
# Save all recent AI requests to YAML file
docker exec -it api python /app/backend/scripts/inspect_last_requests.py

# Filter by specific chat ID
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --chat-id <chat_id>

# Copy output file to host machine
docker cp api:/app/backend/scripts/debug_output/last_requests_<timestamp>.yml ./debug_output.yml
```

### User Debugging

```bash
# Show user statistics (counts, signups, active users)
docker exec -it api python /app/backend/scripts/show_user_stats.py

# Show all chats for a specific user
docker exec -it api python /app/backend/scripts/show_user_chats.py <user_id>

# Show most recent user
docker exec -it api python /app/backend/scripts/show_last_user.py
```

## Cache Inspection (Dragonfly)

```bash
# Connect to Dragonfly cache CLI
docker exec -it cache redis-cli

# Common inspection commands (inside redis-cli):
KEYS *sync:*           # List sync cache keys
KEYS *debug:*          # List debug entries
KEYS *chat:*           # List chat-related keys
GET <key>              # Get value for a key
TTL <key>              # Check time-to-live for a key
TYPE <key>             # Check the type of a key
DBSIZE                 # Total number of keys
```

## Celery Task Queue Inspection

```bash
# Check currently active tasks
docker exec -it task-worker celery -A backend.core.api.worker inspect active

# Check reserved (queued but not yet running) tasks
docker exec -it task-worker celery -A backend.core.api.worker inspect reserved

# Check registered task types
docker exec -it task-worker celery -A backend.core.api.worker inspect registered

# Check scheduled tasks (eta/countdown)
docker exec -it task-worker celery -A backend.core.api.worker inspect scheduled
```

## Package and Dependency Management

- **Verify Versions**: ALWAYS check for the latest stable version of a package (e.g., using `pip` or `npm` search/info commands, or web search) before installing or adding it to dependency files.
- **No Hallucinations**: NEVER assume or hallucinate version numbers. If the version is not explicitly known, verify it using terminal tools or web search.

## Logging and Error Handling

### Backend (Python)
- **Use `logging`**: ALWAYS use `logger.debug()` or `logger.info()` instead of `print()`.
- **Initialization**: Use `logger = logging.getLogger(__name__)` at the module level.
- **No Silent Failures**: NEVER use silent fallbacks. Log errors or raise exceptions so issues are visible.

### Frontend (Svelte/TypeScript)
- **Use `console.log()`**: Preferred for debugging. Ensure errors are visible in the console.

### Guidelines
- **Keep Logs**: Only remove debugging logs after the user confirms the issue is fixed.
- **Comments**: Add extensive comments explaining complex logic and architectural choices.
- **Cache First**: Update server cache BEFORE Directus/disk to ensure data consistency.
- **Directus models**: Define Directus models in YAML files under `backend/core/directus/schemas/`.

## Internationalization (i18n)

### Guidelines
- **NEVER use hardcoded text** for user-facing strings in frontend or backend.
- **ALWAYS use the translation system** for all user-facing content.
- **Source of Truth**: The primary source for translations are the `.yml` files in `frontend/packages/ui/src/i18n/sources/`.
- **Adding Translations**:
  1. Add new keys and translations to the appropriate `.yml` file in `frontend/packages/ui/src/i18n/sources/`.
  2. Follow the established format (use empty strings for missing translations):
     ```yaml
     key_name:
       context: Description of how the text is used
       en: English text
       de: German translation
       # ... other languages
     ```
  3. After modifying `.yml` files, run `npm run build:translations` in `frontend/packages/ui` to update the `.json` files in `locales/`.

### Usage
- **Frontend**: Use the `$text` store for translations: `$text('namespace.key.text')`.
- **Backend**: Use the `TranslationService` to resolve translations from the same YAML sources.
- **Metadata**: Application names and descriptions should use `name_translation_key` or `description_translation_key` instead of hardcoded strings.

## Testing Policy

### CRITICAL: No Tests Without Explicit Consent

**NEVER create unit tests, integration tests, or any test files without the user's explicit consent.** This applies to:
- Unit tests (pytest, vitest)
- Integration tests
- End-to-end tests (Playwright)
- Test fixtures or mocks

**What to do instead:**
1. When you identify a situation where tests might be valuable, make a **brief natural-language suggestion** describing what the tests could cover
2. Do NOT include code examples in test suggestions
3. Wait for the user to explicitly ask you to create the tests before writing any test code
4. If the user says "yes" or "go ahead", only then create the test files

**Example of appropriate suggestion:**
> "This change affects the message encryption flow. You might want tests covering: successful encryption/decryption, handling of missing keys, and edge cases with empty messages."

**Example of what NOT to do:**
> Creating a `test_encryption.py` file without being asked, even if it seems useful.

### Running Existing Tests

**End-to-end tests**: Run relevant Playwright tests when components related to them have changed (see `frontend/apps/web_app/tests/README.md`).

```bash
# Run a specific test file from repo root
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  -e PLAYWRIGHT_TEST_FILE="signup-flow.spec.ts" \
  playwright
```

### REST API Testing
**ALWAYS run the external REST API tests after modifying any backend endpoint code.** This ensures that public-facing endpoints remain functional and conform to the expected response structures.

```bash
# Run all external REST API tests
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py

# Run specific skill tests (e.g., ai/ask)
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py -k ask
```

## Debugging Complex Bugs

### Systematic Approach
1. **Isolate**: Find smallest reproducible case
2. **Trace**: Follow request through services using correlation IDs (`task_id`, `message_id`, `chat_id`, `user_id`)
3. **Reproduce**: Document exact steps

### Correlation IDs
**Always include in logs:**
```python
logger.info(f"[Task ID: {task_id}] Processing message {message_id} for chat {chat_id}")
logger.error(f"Error in task {task_id}: {e}", exc_info=True)
```

**Trace across services:**
```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs api task-worker --tail 2000 | rg -E "chat_id=<ID>|message_id=<ID>|task_id=<TASK_ID>"
```

### Async/Celery Tasks
- Extract `task_id = self.request.id` at start
- Log entry/exit with timing: `[PERF] Handler started/completed`
- Use `exc_info=True` for full stack traces

### Distributed Systems
- Monitor multiple services: `docker compose --env-file .env -f backend/core/docker-compose.yml logs -f api task-worker | rg "pattern"`
- Verify queue routing (`persistence`, `app_web`)
- Check cache updates BEFORE database writes
- Use prefixes: `SYNC_CACHE_UPDATE`, `CACHE_HIT`, `CACHE_MISS`

### WebSocket Flows
- **Client**: Filter console with `[CLIENT_SYNC]`, `[CLIENT_DECRYPT]`
- **Server**: Log handler entry/exit, include `user_id`, `device_fingerprint_hash`

### Structured Logging Prefixes
- `[PERF]` - Timing, `[TASK]` - Celery, `[SYNC]` - Sync ops, `[CACHE]` - Cache, `[ERROR]` - Errors

### Best Practices
- Include correlation IDs in all logs
- Log at service boundaries (entry/exit, queues, cache)
- Use structured prefixes for filtering
- Never silently fail - use `exc_info=True` for errors
