---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/routes/apps_api.py
  - backend/apps/base_skill.py
  - backend/apps/ai/processing/rate_limiting.py
---

# REST API

> Developer-facing API for programmatic access to app skills and focus modes. For full request/response schemas, see the [OpenAPI docs](https://docs.openmates.org/api).

## Why This Exists

Provides programmatic access to OpenMates app skills for automation, integrations, and the CLI package. The REST API cannot decrypt/encrypt chats (zero-knowledge architecture) -- use the CLI/SDK package for chat operations. See [CLI Package](./cli-package.md).

## How It Works

### Base URL and Authentication

```
https://api.openmates.org/v1
Authorization: Bearer YOUR_API_TOKEN
```

API keys can be scoped to specific apps/skills. Write operations via API do not require user confirmation (unlike the web app) -- security comes from key scopes, rate limiting, and logging. See [Action Confirmation](./action-confirmation.md).

### Unified Endpoint Pattern

All app skill endpoints follow:

```
POST /v1/apps/{app_id}/skills/{skill_id}
```

Examples: `POST /v1/apps/web/skills/search`, `POST /v1/apps/videos/skills/get_transcript`, `POST /v1/apps/images/skills/generate`

### Auto-Registration

REST routes are **auto-registered per discovered app** at `api` startup by `register_app_and_skill_routes()` in [apps_api.py](../../backend/core/api/app/routes/apps_api.py). There is no manual registration step and no hardcoded app/hostname map.

Discovery flow (in-process since OPE-342):
1. `discover_apps()` in [main.py](../../backend/core/api/main.py) delegates to `build_skill_registry()` in [skill_registry.py](../../backend/core/api/app/services/skill_registry.py).
2. `build_skill_registry()` filesystem-scans `backend/apps/*/app.yml`, applies stage filtering, and instantiates a `BaseApp(register_http_routes=False)` per app. Each `BaseApp` resolves every skill `class_path` via `importlib`.
3. The result is published as `app.state.skill_registry` (and as a process-global singleton for code paths without FastAPI app context).
4. `register_app_and_skill_routes()` registers `GET /v1/apps/{id}`, `GET /v1/apps/{id}/skills/{skill_id}`, and `POST /v1/apps/{id}/skills/{skill_id}` for every loaded app.
5. `call_app_skill()` dispatches via `SkillRegistry.dispatch_skill()` — directly in-process, no HTTP to sibling containers.

**To add a new app:** drop a folder under `backend/apps/`, restart api. There is no `docker-compose.yml` edit step. If a skill's `class_path` import fails at startup, `BaseApp._resolve_skill_classes` logs an ERROR and the skill returns 404 — the rest of the app and the api itself stay up.

### Request Format

```json
{ "requests": [{ /* skill-specific parameters */ }] }
```

Up to 5 parallel requests per call. Each spawns a separate Celery task. Rate limits tracked per provider/skill/model via Dragonfly cache counters.

### Response Patterns

**Quick-executing skills** (e.g., web search): returns results directly with `previews` array.

**Long-running skills** (e.g., image generation): returns `task_id` + `embed_id`. Poll via `GET /v1/tasks/{task_id}`. Download files via `GET /v1/embeds/{embed_id}/file?format=preview|full|original`.

### Focus Modes

Activated via the chats endpoint (chat IDs in body, never URL, for privacy):

```
POST /v1/chats
{ "chat_id": "chat_abc123", "focus_mode_on": "web.research" }
```

Deactivate: `{ "chat_id": "chat_abc123", "focus_mode_off": true }`

### Error Handling

Standard HTTP status codes (200, 400, 401, 403, 404, 429, 500, 503). Error response:

```json
{ "error": { "code": "INVALID_PARAMETER", "message": "...", "details": {} } }
```

### Rate Limiting

- Per-user limits based on subscription tier
- Max 5 parallel requests per skill call
- Provider API rate limits tracked per provider/skill/model
- Tasks queued (not rejected) when limits reached, auto-retry on reset
- Headers: `X-RateLimit-Remaining`, `X-RateLimit-Reset`

### Privacy

- Chat IDs always in body, never URLs
- Minimal data transfer
- Client-side encryption (REST API cannot decrypt chats)
- No tracking or profiling

## Related Docs

- [Function Calling](./function-calling.md) -- LLM tool integration
- [CLI Package](./cli-package.md) -- SDK with chat encryption support
- [Action Confirmation](./action-confirmation.md) -- confirmation flow differences
- [OpenAPI Docs](https://docs.openmates.org/api) -- auto-generated interactive reference
