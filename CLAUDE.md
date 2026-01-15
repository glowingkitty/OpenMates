# Claude AI Assistant Instructions

## Linting and Code Quality

**ALWAYS run the lint script after making code changes** to verify that your changes haven't introduced any errors.

The `scripts/lint_changed.sh` script checks uncommitted changes for linting and type errors. Use file type filters to only check the types of files you've modified:

**Available file type options:**

- `--py` - Python files (.py)
- `--ts` - TypeScript files (.ts, .tsx)
- `--svelte` - Svelte files (.svelte)
- `--css` - CSS files (.css)
- `--html` - HTML files (.html)
- `--yml` - YAML files (.yml, .yaml)

**Examples:**

```bash
./scripts/lint_changed.sh --py                    # Only Python changes
./scripts/lint_changed.sh --ts --svelte          # Only frontend changes
./scripts/lint_changed.sh --py --ts              # Mixed changes
./scripts/lint_changed.sh                        # All file types
```

**Best practices:**

- Limit checks to changed file types (don't check TypeScript if you only modified Python)
- Always run the lint script before considering changes complete
- Fix all errors before proceeding

## Debugging Backend Issues

**ALWAYS use docker compose terminal commands to check logs** when debugging backend issues. This ensures you're viewing logs from the running containerized services.

**Common commands:**

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs <service-name>              # View logs for a service
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f <service-name>          # Follow logs in real-time
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=100 <service-name>  # View last 100 lines
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f -t <service-name>       # Follow with timestamps
docker compose --env-file .env -f backend/core/docker-compose.yml logs backend worker             # Multiple services
```

**Best practices:**

- Target specific services using service names (check `docker-compose.yml` for exact names)
- Use `-f` flag for real-time debugging
- Use `--tail=N` to limit output for long-running services
- Use `-t` flag to see timestamps
- Verify service is running with `docker compose ps` before checking logs
- Run these commands from the `OpenMates` repo root so the paths resolve correctly
- For a quick look at recent activity, use `docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=200 <service-name>` to focus on the latest entries

**Common service names:** `backend`, `api`, `worker`, `scheduler`

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
- **Server inspection**: Use `docker exec api python /app/backend/scripts/inspect_chat.py {chatid}` or `docker exec api python /app/backend/scripts/inspect_embed.py {embedid}` to gather more details about a chat or embed on the server/server cache/server storage.
- **Test considerations**: Consider when end-to-end tests and unit tests are warranted, but never build them without the user first clearly consenting; only make short, natural-language suggestions describing what the tests should cover (no code examples).
- **End-to-end coverage**: Run relevant end-to-end tests when components related to them have changed (see `frontend/apps/web_app/tests/README.md`, e.g., after signup or login changes). Example for a specific test file from the repo root: `docker compose -f docker-compose.playwright.yml run --rm -e SIGNUP_TEST_EMAIL_DOMAINS -e MAILOSAUR_API_KEY -e PLAYWRIGHT_TEST_BASE_URL -e PLAYWRIGHT_TEST_FILE="tests/signup-flow.spec.ts" playwright`.

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
docker compose --env-file .env -f backend/core/docker-compose.yml logs api task-worker --tail 2000 | grep -E "chat_id=<ID>|message_id=<ID>|task_id=<TASK_ID>"
```

### Async/Celery Tasks
- Extract `task_id = self.request.id` at start
- Log entry/exit with timing: `[PERF] Handler started/completed`
- Use `exc_info=True` for full stack traces

### Distributed Systems
- Monitor multiple services: `docker compose --env-file .env -f backend/core/docker-compose.yml logs -f api task-worker | grep "pattern"`
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
