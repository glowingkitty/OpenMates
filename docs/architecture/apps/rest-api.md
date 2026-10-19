---
status: active
last_verified: 2026-03-24
key_files:
- backend/core/api/app/routes/apps_api.py
- backend/apps/base_skill.py
- backend/apps/ai/processing/rate_limiting.py
claims:
- id: arch-apps-rest-api-behavior
  type: unit
  claim: REST API is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - backend/core/api/app/routes/apps_api.py
  - backend/apps/base_skill.py
  - backend/apps/ai/processing/rate_limiting.py
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-apps-rest-api-behavior
  verified: '2026-06-11'
- id: arch-apps-rest-api-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-apps-rest-api-source-1
  anchors:
  - type: file_exists
    path: backend/apps/ai/processing/rate_limiting.py
- id: arch-apps-rest-api-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-apps-rest-api-source-2
  anchors:
  - type: file_exists
    path: backend/apps/base_skill.py
- id: arch-apps-rest-api-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-apps-rest-api-source-3
  anchors:
  - type: file_exists
    path: backend/core/api/app/routes/apps_api.py
---

# REST API

> Developer-facing API for programmatic access to app skills and focus modes. For full request/response schemas, see the [OpenAPI docs](https://docs.openmates.org/api).

## Why This Exists

Provides programmatic access to OpenMates app skills for automation, integrations, and the CLI package. The REST API cannot decrypt/encrypt chats (zero-knowledge architecture) -- use the CLI/SDK package for chat operations. See [CLI Package](../platforms/cli-package.md).

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

### Anonymous REST, CLI and SDK Calls

The official cloud also accepts logged-out REST, CLI and SDK calls at
`POST /v1/anonymous/apps/{app_id}/skills/{skill_id}` without an API key or
custom identity header. The body uses the same skill schema, with
one logical skill operation per call. Batch-style skills accept exactly one
request; `ai.decide` accepts bounded state and typed questions directly.
Provider rate-limit waits are rejected
instead of queued. Only skills explicitly marked
`anonymous_access: inline` in `app.yml` are eligible: they return an immediate
result, require no connected account, and create no file or background job.
File generation, uploads, account actions, and private chat/embed references
require authentication.

The server quotes and reserves credits before dispatch against the same
public-IP and server-wide daily, weekly, and monthly anonymous limits used
by web and CLI chat. When the budget is inactive or cannot cover a request,
anonymous work returns HTTP 429 with `detail.signup_required: true` and a human
message explaining that the free allowance is unavailable and an account is
needed. This is an admission refusal, separate from provider or meter failures
(HTTP 503). Both SDKs expose `OpenMatesSignupRequiredError` for this response;
authenticated users with account credits continue through the authenticated
endpoint. Anonymous calls pass no user, chat, message, embed, or upload context
to skills and create no permanent Directus content records. The anonymous route
is intentionally outside the authenticated developer OpenAPI schema.

`GET /v1/anonymous/free-usage/status` needs no identity header or query parameter.
Without an installation identity, `daily_remaining_percent` is `null`; IP limits
still gate availability. SDKs may supply their internal installation identity
and receive a personal daily percentage. The public response does not expose
credit counts or identity hashes; `can_send_text` and `reason` reflect the
applicable daily, weekly, and monthly limits. Status is informational and does
not reserve allowance. REST callers need no identity setup.

Both SDKs support eligible skills and transient text chat without an API key.
Use `new OpenMates()` in JavaScript or `OpenMates()` in Python: the constructor
uses guest access without a key and account access when `OPENMATES_API_KEY` is
configured. The clients expose `anonymous.status()` and use
`/v1/anonymous/chat/stream` for `chats.send`. An advanced free-only override,
`anonymous: true` / `anonymous=True`, ignores an environment API key.
Saved chats, files, account data and caller-selected models require an account.
An invalid authenticated key never falls back to anonymous execution.

### Inline Decisions

`POST /v1/anonymous/apps/ai/skills/decide` accepts JSON `state` and a map of
1–16 named `questions`, each with a `type` and `instructions`. Types are `noul`
(yes/no probability), `choice` (2–16 named criteria), and `score` (2–10 ordered
criteria). Normalized state and questions are limited to 16,384 UTF-8 bytes, separately from image assets.
The authenticated route is `/v1/apps/ai/skills/decide`. Neither route accepts
provider, model, or usage overrides.

The same operation is available as `apps.ai.decide(input)` in both SDKs and
`openmates apps ai decide --input '<JSON>' --json` in the CLI. Results use the
standard skill envelope; typed answers are in `data.answers`, and server usage
is in `data.usage`.

The server pins Jev 1.14 (`jev-1.14.0` at TypeSafe). Text requests make at most
one direct TypeSafe attempt and one OpenRouter fallback attempt, without retries.
Image requests make one direct TypeSafe attempt and never use OpenRouter.
Reservations use reviewed provider context ceilings and the catalogue tariff;
actual native usage, including image input tokens, settles the reservation.
Ambiguous incurred spend retains its corresponding conservative charge. A small
request may need more credit headroom for admission than its final charge.
Decisions create no saved chat, embed, or file.

#### Experimental image decisions

Add an `assets` map to the same JSON request. The example shape is:

```json
{
  "state": { "game_board": "902f1e2a-1869-4d54-8e08-91db56598c53" },
  "questions": {
    "clear": { "type": "noul", "instructions": "Is there a clear path to the exit on the game board?" }
  },
  "assets": {
    "902f1e2a-1869-4d54-8e08-91db56598c53": { "type": "image", "format": "png", "data_base64": "<base64 file bytes>" }
  }
}
```

Replace the placeholder with standard base64 from an actual PNG/JPEG file.
References are string values in state, instructions, or criteria; every asset
must be referenced. Use canonical lowercase UUID reference keys, generated anew for each image. SDKs accept this same JSON shape; they do not use a separate upload
method. OpenMates sets the required TypeSafe image header on the provider call.

OpenMates accepts at most four still images, each at most 1 MiB decoded and at
most 4 MiB decoded in total. Both width and height must be 280–1568 pixels, and
real image content is validated. The whole JSON body is limited to 6 MiB; the
16 KiB state/questions bound remains separate. Supported formats are `png`,
`jpg`, and `jpeg`. Remote URL fetching, multipart bodies, stored-upload refs,
audio, and video are not part of this interface. Existing upload flows still
require an account. Question types remain `noul`, `choice`, and `score`.

Treat this as a prototype feature. Image tokens consume the same applicable
free allowance or account credits as other input tokens; no separate image
free pool is promised. Caller state, questions, and images are sent to TypeSafe.
Text-only requests may use OpenRouter fallback; images do not. Transient handling
by OpenMates does not guarantee zero provider retention. See [TypeSafe integration](../../apis/typesafe-jev.md),
[TypeSafe images](https://docs.typesafe.ai/images), and [TypeSafe models](https://docs.typesafe.ai/models).

### Auto-Registration

REST routes are **auto-registered per discovered app** at `api` startup by `register_app_and_skill_routes()` in [apps_api.py](../../backend/core/api/app/routes/apps_api.py). There is no manual registration step and no hardcoded app/hostname map.

Discovery flow (in-process since OPE-342):
1. `discover_apps()` in [main.py](../../backend/core/api/main.py) delegates to `build_skill_registry()` in [skill_registry.py](../../backend/core/api/app/services/skill_registry.py).
2. `build_skill_registry()` filesystem-scans `backend/apps/*/app.yml`, applies feature availability filtering, and instantiates a `BaseApp(register_http_routes=False)` per app. Each `BaseApp` resolves every skill `class_path` via `importlib`.
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

## Direct use from the Apps workspace

The public web workspace uses `/#apps/<app>/<skill>` URLs. Compact `/apps/...`
paths and previous Settings Apps links forward to the corresponding hash URL;
URL hyphens resolve to the catalog's underscore identifiers.
App details separate Skills, Focus modes, Memories, Embeds and Workflows;
skill details retain Overview, Embeds and Workflows.

`GET /v1/apps/{app_id}/skills/{skill_id}/details` lazily supplies the direct
request schema, declared defaults, primary field paths, pricing, providers,
models and execution availability. `sdk_tool_schema` takes precedence over the
assistant schema. The shared schema renderer projects at most two primary
controls and puts additional fields in Show settings. Required input is
validated without inserting workflow test examples as defaults.
Optional `x-ui.apps` hints override presentation on a copied Apps schema only.
For example, Audio uses a prompt textarea while optional duration and format
fields appear in Show settings; its original Workflow hints and defaults remain
unchanged.

Execution continues through the existing `/v1/apps/.../skills/...` endpoints.
First-party Team execution supplies an authorized `team_id` query parameter;
the server checks membership and spending role and preserves that billing
context through asynchronous jobs. CLI requests retain their existing
temporary-history behavior. Guests use the existing anonymous direct endpoint
after a request-specific `/availability` quote; execution still performs atomic
budget admission and rejects background, storage-dependent and account-dependent
skills.

The browser encrypts Apps results before posting a chatless root and its children
to `/v1/apps/workspace/results`. `expected_user_id` binds the upload to the
submitting user; Team key wrappers, app indexes and creator ownership are checked
before writes. Existing generated asset IDs are reused. The paginated result
catalog also indexes saved chat and memory embeds using server-verified account
context. Saved workflows are selected by app references in their current graph,
including workflows that have not run.

Older chat embeds are classified in the browser. While an authenticated Embeds
tab is open, resumable discovery pages scoped chat metadata and requests at most
50 encrypted root embeds from one verified chat at a time, without message
histories or media bytes. The existing content-batch WebSocket request accepts
the opt-in `apps_legacy_embeds_only` flag. Classification preserves original key
wrappers and posts app projections in batches of at most 50. Bulk sync also
notifies an already-open library to revisit newly received roots. Leaving the
library or switching account stops discovery and guards pending local writes.

Guest graphs remain encrypted in IndexedDB and are promoted into Personal storage
after signup without another skill execution. Failed or interrupted promotion
keeps the local source. Retained task IDs allow processing results to resume
polling after reload. Generated media obtains a fresh download URL through the
session-authenticated generated-assets endpoint after owner or Team membership
verification.

Implementation: `apps_workspace_metadata.py`, `apps_workspace_results_service.py`,
`AppsWorkspace.svelte`, `AppsSkillForm.svelte`, `appsWorkspaceService.ts` and
`appsWorkspaceResultsService.ts`. Product intent is recorded in
`feature.apps-workspace@1` and `feature.workspace-shell@3`.

## Related Docs

- [Function Calling](./function-calling.md) -- LLM tool integration
- [CLI Package](../platforms/cli-package.md) -- SDK with chat encryption support
- [Action Confirmation](./action-confirmation.md) -- confirmation flow differences
- [OpenAPI Docs](https://docs.openmates.org/api) -- auto-generated interactive reference
