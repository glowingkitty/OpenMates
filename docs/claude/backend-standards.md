# Backend Standards — Rules

Python/FastAPI coding standards. For full rebuild commands, REST API docs guide, and detailed patterns, run:
`python3 scripts/sessions.py context --doc backend-standards-ref`

---

## Rule 1: Rebuild After Every Backend Change (CRITICAL)

Every Python change under `backend/` requires rebuilding affected Docker containers. Editing files on disk does NOT update running services.

| Path changed | Containers to rebuild |
|---|---|
| `backend/core/api/` | `api` |
| `backend/core/workers/` | `task-worker`, `task-scheduler` |
| `backend/apps/<app>/` | `app-<app>`, `app-<app>-worker` (if exists) |
| `backend/shared/` | All services importing shared code |

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build <services> && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d <services>
```

New app containers: always restart `api` after starting for discovery.

## Rule 2: Error Handling — No Silent Failures

Never use fallback values to hide errors. All errors must be logged and raised.

```python
# WRONG
try:
    data = read_file()
except:
    data = None

# CORRECT
try:
    data = read_file()
except Exception as e:
    logger.error(f"Failed to read file: {e}", exc_info=True)
    raise
```

Always include context: what operation failed, relevant IDs (request_id, provider, user), original error.

## Rule 3: Code Style

- PEP 8, type hints on all function params and returns
- `logger.debug()`/`logger.info()` — never `print()`
- Named constants — no magic values
- Docstrings on all functions and classes

## Rule 4: Module Boundaries

- Skills must NOT import from other skills → use `BaseSkill` or `backend/shared/`
- Providers must NOT depend on skill-specific code — pure API wrappers only

## Rule 5: Dependency Versions (CRITICAL)

Never write a version from memory. Always look up first:
- pip: `pip index versions <pkg>` or web search
- Docker: web search for Docker Hub tags
- Pin exact versions. No `latest`, `*`, or unpinned deps.

## Rule 6: REST API Documentation

Every skill needs `{Name}Request` and `{Name}Response` Pydantic models (auto-discovered by naming convention). Use `Field(...)` with `description` on all fields. Match `tool_schema` properties in `app.yml`.
