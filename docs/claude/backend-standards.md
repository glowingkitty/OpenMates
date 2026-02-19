# Backend Standards (Python/FastAPI)

Standards for modifying Python code in `backend/` - FastAPI routes, Pydantic models, database patterns, and security.

---

## Rebuild & Restart After Backend Changes (CRITICAL)

**Every time you modify Python code under `backend/`, you MUST rebuild and restart the affected Docker containers.** The backend runs inside Docker containers — editing files on disk does NOT automatically update the running services. If you skip this step, your changes will have no effect and the user will see stale behavior.

### Identify and rebuild only the affected containers

Rebuild only the containers whose code you actually changed. Do NOT rebuild the entire stack unless you have a specific reason to.

**Common container-to-path mappings:**

| Path changed            | Containers to rebuild                      |
| ----------------------- | ------------------------------------------ |
| `backend/core/api/`     | `api`                                      |
| `backend/core/workers/` | `task-worker`, `task-scheduler`            |
| `backend/apps/ai/`      | `app-ai`, `app-ai-worker`                  |
| `backend/apps/web/`     | `app-web`, `app-web-worker`                |
| `backend/apps/videos/`  | `app-videos`                               |
| `backend/apps/news/`    | `app-news`                                 |
| `backend/apps/maps/`    | `app-maps`                                 |
| `backend/apps/code/`    | `app-code`                                 |
| `backend/shared/`       | All app containers that import shared code |

**Rebuild and restart only the relevant containers:**

```bash
# Example: only api changed
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build api && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d api

# Example: api + task-worker changed
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build api task-worker && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d api task-worker
```

### Full stack rebuild (only when necessary)

Only do a full teardown + rebuild when:

- You changed `backend/shared/` code used across many services
- You added or removed Docker services
- You changed environment variables or Docker configs
- Something is broken and you need a clean slate

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down && \
docker volume rm openmates-cache-data && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

After restarting, verify the affected services are healthy:

```bash
# Replace with the containers you actually restarted
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=20 api task-worker
```

---

## Python Code Style

- Follow PEP 8 style guidelines
- Use type hints for all function parameters and return values
- Use `logger.debug()` or `logger.info()` instead of `print()` statements
- Add comprehensive docstrings for all functions and classes

---

## FastAPI Best Practices

- Use dependency injection for database connections and services
- Implement proper request/response models with Pydantic
- Use async/await for I/O operations
- Implement proper error handling with HTTPException
- Use background tasks for non-critical operations

---

## Error Handling (CRITICAL)

- **NEVER use fallback values to hide errors** - all errors must be visible
- **NO silent failures** - if an operation fails, log it and raise an exception
- Always use proper exception handling with logging
- Never catch exceptions without logging them

```python
# ❌ WRONG - hides errors
try:
    data = read_file()
except:
    data = None

# ✅ CORRECT - errors are visible
try:
    data = read_file()
except Exception as e:
    logger.error(f"Failed to read file: {e}", exc_info=True)
    raise
```

---

## Database Patterns

- Use repository pattern for data access
- Implement proper connection pooling
- Use transactions for multi-step operations
- Follow database naming conventions (snake_case)
- Define Directus models in YAML files under `backend/core/directus/schemas/`

---

## App Skills — REST API Documentation (CRITICAL)

When creating or modifying an app skill, you **MUST** ensure it is properly documented in the REST API docs (`/docs`). The dynamic route registration in `backend/core/api/app/routes/apps_api.py` auto-discovers Pydantic models from skill modules to generate typed OpenAPI schemas. If models are missing, the API docs will show an untyped `Dict[str, Any]` body — which is unacceptable.

### Checklist for Every New/Modified Skill

1. **Define `{Name}Request` and `{Name}Response` Pydantic models** in the skill module file (e.g., `search_skill.py`). The naming convention must end with `Request` and `Response`:

   ```python
   # ✅ CORRECT — auto-discovered by generic model lookup
   class ShareUsecaseRequest(BaseModel):
       summary: str = Field(..., description="Brief summary of use cases")
       language: str = Field(..., description="ISO 639-1 language code")

   class ShareUsecaseResponse(BaseModel):
       success: bool = Field(default=False)
       message: Optional[str] = Field(None)
       error: Optional[str] = Field(None)
   ```

2. **Define `tool_schema` in `app.yml`** — This is the JSON Schema that describes the skill's input parameters. It is used both for LLM function calling and for REST API documentation:

   ```yaml
   tool_schema:
     type: object
     properties:
       summary:
         type: string
         description: "A brief summary (2-5 sentences)"
       language:
         type: string
         description: "ISO 639-1 language code"
     required:
       - summary
       - language
   ```

3. **Ensure Request model fields match `tool_schema` properties** — The Pydantic model fields should correspond to the `tool_schema` properties so the OpenAPI docs show accurate information.

4. **Use `Field(...)` with `description` on all model fields** — This ensures the OpenAPI docs show clear parameter descriptions.

### REST API Endpoint Visibility (`api_config`)

By default, every skill gets **two** endpoints:

- `GET /v1/apps/{app_id}/skills/{skill_id}` — Returns skill metadata with pricing
- `POST /v1/apps/{app_id}/skills/{skill_id}` — Executes the skill

To make a skill **POST-only** (no GET metadata endpoint), add `api_config` in `app.yml`:

```yaml
skills:
  - id: share-usecase
    api_config:
      expose_get: false # Only POST endpoint, no GET
    # ... other fields ...
```

### How Model Auto-Discovery Works

The route registration in `apps_api.py` scans the skill module for all classes that:

- Inherit from Pydantic `BaseModel`
- Have names ending with `Request` or `Response`
- Are defined in the skill module itself (not imported base classes)

This is **fully generic** — no hardcoded model names. Any skill following the `{Name}Request` / `{Name}Response` convention will be auto-discovered.

### Common Mistakes

```python
# ❌ WRONG — no Request model, API docs show untyped Dict
class MySkill(BaseSkill):
    async def execute(self, query: str, **kwargs):
        ...

# ❌ WRONG — model name doesn't end with "Request"
class MySkillInput(BaseModel):  # Won't be discovered!
    query: str

# ✅ CORRECT — follows naming convention
class MySkillRequest(BaseModel):
    query: str = Field(..., description="Search query")

class MySkillResponse(BaseModel):
    success: bool = Field(default=False)
    results: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = Field(None)
```

---

## Security Best Practices

- Validate all input data
- Use environment variables for sensitive configuration
- Implement proper authentication and authorization
- Sanitize user inputs
- Implement rate limiting where appropriate
