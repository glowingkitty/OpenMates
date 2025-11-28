# REST API Architecture

> **Status:** Developer-focused API documentation
>
> **Note:** This document covers the common patterns and structure of the OpenMates REST API. For detailed endpoint documentation with request/response schemas, see the [OpenAPI documentation](https://docs.openmates.org/api) (auto-generated from FastAPI code).

## Overview

The OpenMates REST API provides programmatic access to app skills and focus modes. The API follows a unified structure and uses POST requests by default for all skill endpoints.

**Important:** The REST API is separate from the CLI package (pip/npm). The REST API cannot decrypt/encrypt chats, so for chat management you need to use the pip or npm packages. See [CLI Package Architecture](./cli_package.md) for details.

## Base URL

```text
https://api.openmates.org/api/v1
```

## Authentication

All API requests require authentication. Include your API token in the request headers:

```text
Authorization: Bearer YOUR_API_TOKEN
```

**API Key Security**: API keys can be scoped to specific apps/skills for fine-grained permissions. See [Developer Settings](./developer_settings.md) for API key management.

**Action Confirmation**: Write and sensitive operations via REST API do **not** require user confirmation (unlike web app access). Security is provided through:
- API key scopes/permissions
- Rate limiting on write actions
- Logging of all actions
- Device confirmation for new devices
- Optional enhanced security mode (can require confirmation even for API keys)

For details on action confirmation architecture, see [Action Confirmation Architecture](./apps/action_confirmation.md).

## Unified API Structure

All app skill endpoints follow this pattern:

```text
POST /api/v1/apps/{appname_slug}/{skill_slug}
```

**Examples:**

- `POST /api/v1/apps/web/search` - Web search skill
- `POST /api/v1/apps/videos/get_transcript` - Video transcript skill
- `POST /api/v1/apps/images/generate` - Image generation skill

### Request Format

All skill endpoints use POST requests with JSON body. The request body structure varies by skill, but typically includes:

```json
{
  "requests": [
    {
      // Skill-specific parameters
    }
  ]
}
```

### Response Format

**Quick-executing skills** (e.g., web search):

- Returns results directly in the response body
- Response includes `previews` array with results

**Long-running skills** (e.g., image generation):

- Returns a task ID immediately
- Use the task polling endpoint to check status

## Multiple Requests Pattern

All skills support processing multiple requests in a single API call. This enables parallel processing of related tasks.

**Example:**

```json
{
  "requests": [
    {"query": "Python async programming"},
    {"query": "FastAPI best practices"},
    {"query": "Celery task queues"}
  ]
}
```

**Rate Limiting:**

- Maximum 5 parallel requests per skill call
- Requests are processed simultaneously when API rate limits allow
- Each request creates a separate Celery task for parallel execution

**Implementation Details:**

- **Task Execution**: One API call with multiple requests spawns multiple Celery tasks in the app's Celery worker container. Each task independently calls the external provider API (e.g., Brave Search API) while respecting rate limits.
- **Rate Limit Tracking**: Rate limits are tracked per provider, per skill, and per model (when applicable) using Dragonfly cache-based counters. Keys use format `{provider_id}.{skill_id}` or `{provider_id}.{skill_id}.{model_id}`.
- **Queue Management**: When rate limits are reached, tasks are queued rather than rejected. Tasks automatically retry once the rate limit key expires (with calculated retry timing).
- **Result Delivery**: Results are sent incrementally via WebSocket as each sub-request completes. A request is considered complete once all sub-requests finish.

For more details on the multiple requests pattern, see [App Skills Architecture](./apps/app_skills.md#multiple-requests-per-skill-call).

## Task Polling

For long-running skills that return a task ID, use the unified task polling endpoint:

```text
GET /api/v1/tasks/{task_id}
```

**Response:**

```json
{
  "task_id": "abc123",
  "status": "processing|completed|failed",
  "result": {
    // Skill-specific result data (only when status is "completed")
  },
  "error": {
    // Error details (only when status is "failed")
  }
}
```

**Polling Strategy:**

- Poll every 1-2 seconds for active tasks
- Exponential backoff recommended for failed requests
- Task results are cached for a limited time after completion

## Focus Modes

Focus modes are activated via the chats endpoint (not app-specific endpoints) for privacy reasons:

```text
POST /api/v1/chats
```

**Request Body:**

```json
{
  "chat_id": "chat_abc123",
  "focus_mode_on": "web.research"
}
```

**Activate Focus Mode:**

- `focus_mode_on`: Format is `{appname_slug}.{focus_slug}` (e.g., `web.research`, `code.write_code`)
- `chat_id`: The chat ID (sent in body, not URL, for privacy)

**Deactivate Focus Mode:**

```json
{
  "chat_id": "chat_abc123",
  "focus_mode_off": true
}
```

**Privacy Note:** Chat IDs are always sent in the request body, never in the URL, to maintain privacy and prevent URL-based tracking.

For user-facing documentation on focus modes, see [Focus Modes](./apps/focus_modes.md).

## Request/Response Patterns

### Quick-Executing Skills

Skills that complete quickly (typically < 1 second, e.g., web search) return results directly:

**Request:**

```http
POST /api/v1/apps/web/search
Authorization: Bearer YOUR_API_TOKEN
Content-Type: application/json

{
  "requests": [
    {"query": "OpenMates documentation"}
  ]
}
```

**Response:**

```json
{
  "previews": [
    {
      "type": "search_result",
      "title": "OpenMates Documentation",
      "url": "https://docs.openmates.org",
      "snippet": "...",
      "hash": "abc123..."
    }
  ],
  "suggestions_follow_up_requests": [
    "Search more in depth.",
    "Create a PDF report."
  ]
}
```

### Long-Running Skills

Skills that take longer to execute return a task ID:

**Request:**

```http
POST /api/v1/apps/images/generate
Authorization: Bearer YOUR_API_TOKEN
Content-Type: application/json

{
  "requests": [
    {"prompt": "A futuristic cityscape at sunset"}
  ]
}
```

**Response:**

```json
{
  "task_id": "task_xyz789",
  "status": "processing"
}
```

**Poll for Result:**

```http
GET /api/v1/tasks/task_xyz789
Authorization: Bearer YOUR_API_TOKEN
```

**Response (when completed):**

```json
{
  "task_id": "task_xyz789",
  "status": "completed",
  "result": {
    "previews": [
      {
        "type": "image",
        "url": "https://cdn.openmates.org/images/xyz789.png",
        "hash": "def456..."
      }
    ]
  }
}
```

## Error Handling

All endpoints return standard HTTP status codes:

- `200 OK` - Request successful
- `201 Created` - Resource created successfully
- `400 Bad Request` - Invalid request parameters
- `401 Unauthorized` - Missing or invalid authentication
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - Service temporarily unavailable

**Error Response Format:**

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "The 'query' parameter is required",
    "details": {}
  }
}
```

## Rate Limiting

- **Per-user rate limits:** Applied based on your subscription tier
- **Parallel requests:** Maximum 5 parallel requests per skill call
- **Rate limit headers:** Check `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers

When rate limits are exceeded, you'll receive a `429 Too Many Requests` response.

**Provider API Rate Limits:**

The system tracks and enforces rate limits for external provider APIs at a granular level:
- **Per Provider**: Each provider (e.g., Brave Search, OpenAI, Google) has separate rate limits
- **Per Skill**: Each skill within a provider may have different rate limits (different API endpoints)
- **Per Model** (when applicable): Some providers have different rate limits per AI model

Rate limits are tracked using Dragonfly cache-based counters that auto-expire after the rate limit reset time. When provider rate limits are reached, tasks are queued and automatically retried once the limit resets, ensuring requests are never rejected due to rate limit issues.

## OpenAPI Documentation

Complete API documentation with request/response schemas is available at:

- **Interactive Docs:** <https://docs.openmates.org/api>
- **OpenAPI JSON:** <https://docs.openmates.org/api/openapi.json>

The OpenAPI documentation is auto-generated from FastAPI code using Swagger/OpenAPI, ensuring it stays in sync with the implementation.

## Privacy Considerations

OpenMates is designed with privacy as a core principle:

- **Chat IDs in body:** Never include sensitive identifiers in URLs
- **Minimal data transfer:** Only send the minimum data required for processing
- **Encryption:** Chat data is encrypted client-side (REST API cannot decrypt chats)
- **No tracking:** API requests are not used for user tracking or profiling

## Related Documentation

- [App Skills Architecture](./apps/app_skills.md) - Detailed skill implementation patterns
- [Focus Modes](./apps/focus_modes.md) - User-facing focus mode documentation
- [Function Calling](./apps/function_calling.md) - How LLM function calling integrates with apps
- [CLI Package Architecture](./cli_package.md) - CLI and SDK access (includes chat encryption/decryption)
- [Servers Architecture](./servers.md) - Docker container architecture for apps
